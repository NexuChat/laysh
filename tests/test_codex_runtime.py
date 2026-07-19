import asyncio
import json
import os
import signal
from pathlib import Path

import pytest

from tests.golden_cases import VALID_MODULE_OUTPUT


class FakeProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0, delay: float = 0):
        self.stdout = stdout.encode()
        self.stderr = stderr.encode()
        self.returncode = None
        self.final_returncode = returncode
        self.delay = delay
        self.pid = 43210
        self.stdin_data = None
        self.waited = False

    async def communicate(self, value: bytes):
        self.stdin_data = value
        if self.delay:
            await asyncio.sleep(self.delay)
        self.returncode = self.final_returncode
        return self.stdout, self.stderr

    async def wait(self):
        self.waited = True
        self.returncode = self.final_returncode
        return self.returncode


def success_jsonl(document: dict, thread_id: str = "thread-curated-123") -> str:
    return "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": thread_id}),
            json.dumps({"type": "turn.started"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": json.dumps(document)},
                }
            ),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 2}}),
        ]
    )


def executor_with_process(process, captured, **overrides):
    from server.codex_runtime import CodexExecutor

    async def factory(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        captured["cwd_was_empty"] = not any(Path(kwargs["cwd"]).iterdir())
        return process

    return CodexExecutor(
        process_factory=factory,
        stage_timeout_seconds=overrides.pop("stage_timeout_seconds", 1),
        record_runtime=overrides.pop("record_runtime", False),
        evidence_allowlist=frozenset({"moon_phases_ar"}),
        **overrides,
    )


def test_every_codex_output_schema_matches_strict_structured_output_subset():
    from server.codex_backend import CODEX_OUTPUT_SCHEMAS
    from server.codex_runtime import validate_strict_output_schema

    violations = {
        path.name: validate_strict_output_schema(json.loads(path.read_text(encoding="utf-8")))
        for path in CODEX_OUTPUT_SCHEMAS
    }
    assert violations == {path.name: [] for path in CODEX_OUTPUT_SCHEMAS}


@pytest.mark.parametrize(
    ("schema", "violation"),
    [
        (
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"value": {"enum": ["x"]}},
                "required": ["value"],
            },
            "$.properties.value:missing_type",
        ),
        (
            {
                "type": "object",
                "properties": {},
                "required": [],
            },
            "$:object_must_set_additionalProperties_false",
        ),
        (
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"value": {"type": "string"}},
                "required": [],
            },
            "$:required_must_list_every_property",
        ),
        (
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"value": {"type": "string", "format": "uri"}},
                "required": ["value"],
            },
            "$.properties.value:forbidden_keyword:format",
        ),
        (
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "value": {
                        "type": ["string", "null"],
                        "anyOf": [{"type": "string"}, {"enum": [None]}],
                    }
                },
                "required": ["value"],
            },
            "$.properties.value.anyOf[1]:missing_type",
        ),
        (
            {
                "type": "array",
                "items": {"enum": ["x", "y"]},
            },
            "$.items:missing_type",
        ),
        (
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
                "required": [],
                "$defs": {"choice": {"enum": ["x"]}},
            },
            "$.$defs.choice:missing_type",
        ),
        (
            {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string"},
            },
            "$:forbidden_keyword:uniqueItems",
        ),
        (
            {
                "type": "object",
                "$ref": "#/$defs/value",
                "$defs": {
                    "value": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {},
                        "required": [],
                    }
                },
            },
            "$:ref_cannot_have_sibling_keywords",
        ),
    ],
)
def test_strict_output_schema_guard_reports_every_restricted_shape(schema, violation):
    from server.codex_runtime import validate_strict_output_schema

    assert violation in validate_strict_output_schema(schema)


@pytest.mark.asyncio
async def test_executor_rejects_incompatible_schema_before_spawning(tmp_path):
    from server.codex_runtime import CodexPolicyError

    incompatible = tmp_path / "incompatible.schema.json"
    incompatible.write_text(
        json.dumps(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"value": {"oneOf": [{"type": "null"}, {"type": "string"}]}},
                "required": ["value"],
            }
        ),
        encoding="utf-8",
    )
    spawned = False

    async def factory(*_args, **_kwargs):
        nonlocal spawned
        spawned = True
        return FakeProcess()

    from server.codex_runtime import CodexExecutor

    executor = CodexExecutor(process_factory=factory)
    with pytest.raises(CodexPolicyError, match="unsupported_output_schema_keyword:oneOf"):
        await executor.execute_stage(
            prompt="must not run",
            schema_path=incompatible,
            model="gpt-5.6-luna",
            effort="low",
        )
    assert spawned is False


@pytest.mark.asyncio
async def test_public_stage_uses_stdin_argument_array_isolated_cwd_and_ephemeral(monkeypatch):
    process = FakeProcess(success_jsonl(VALID_MODULE_OUTPUT))
    captured = {}
    monkeypatch.setenv("LAYSH_CANARY_SECRET", "must-not-be-inherited")
    executor = executor_with_process(process, captured)
    schema = Path("server/schemas/module.schema.json").resolve()

    result = await executor.execute_stage(
        prompt="private prompt via stdin",
        schema_path=schema,
        model="gpt-5.6-sol",
        effort="medium",
        public=True,
    )

    args = captured["args"]
    kwargs = captured["kwargs"]
    assert args[:3] == (executor.codex_path, "exec", "-")
    assert "private prompt via stdin" not in args
    assert process.stdin_data == b"private prompt via stdin"
    assert "--ephemeral" in args
    assert "--ignore-user-config" in args and "--ignore-rules" in args
    sandbox_index = args.index("--sandbox")
    model_index = args.index("--model")
    assert ("--sandbox", "read-only") == args[sandbox_index : sandbox_index + 2]
    assert ("--model", "gpt-5.6-sol") == args[model_index : model_index + 2]
    assert 'model_reasoning_effort="medium"' in args
    assert kwargs["stdin"] == asyncio.subprocess.PIPE
    assert kwargs["stdout"] == asyncio.subprocess.PIPE
    assert kwargs["stderr"] == asyncio.subprocess.PIPE
    assert kwargs["start_new_session"] is True
    assert "shell" not in kwargs
    assert captured["cwd_was_empty"] is True
    assert "LAYSH_CANARY_SECRET" not in kwargs["env"]
    assert result.data == VALID_MODULE_OUTPUT
    assert result.thread_id == "thread-curated-123"
    assert result.model == "gpt-5.6-sol"
    assert result.elapsed_ms >= 0


@pytest.mark.asyncio
async def test_evidence_mode_is_disabled_by_default():
    from server.codex_runtime import CodexPolicyError

    executor = executor_with_process(FakeProcess(), {})
    with pytest.raises(CodexPolicyError, match="evidence_mode_disabled"):
        await executor.execute_stage(
            prompt="curated",
            schema_path=Path("server/schemas/module.schema.json").resolve(),
            model="gpt-5.6-sol",
            effort="medium",
            public=False,
            evidence_fixture_id="moon_phases_ar",
        )


@pytest.mark.asyncio
async def test_evidence_mode_accepts_only_allowlisted_fixture_and_omits_ephemeral():
    from server.codex_runtime import CodexPolicyError

    captured = {}
    executor = executor_with_process(
        FakeProcess(success_jsonl(VALID_MODULE_OUTPUT)),
        captured,
        record_runtime=True,
    )
    schema = Path("server/schemas/module.schema.json").resolve()

    with pytest.raises(CodexPolicyError, match="fixture_not_allowlisted"):
        await executor.execute_stage(
            prompt="arbitrary public input",
            schema_path=schema,
            model="gpt-5.6-sol",
            effort="medium",
            public=False,
            evidence_fixture_id="arbitrary",
        )

    await executor.execute_stage(
        prompt="repository-owned moon fixture",
        schema_path=schema,
        model="gpt-5.6-sol",
        effort="medium",
        public=False,
        evidence_fixture_id="moon_phases_ar",
    )
    assert "--ephemeral" not in captured["args"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stdout", "returncode", "code"),
    [
        ("not-json\n", 0, "malformed_jsonl"),
        (json.dumps({"type": "turn.completed"}), 0, "missing_final_message"),
        (success_jsonl({**VALID_MODULE_OUTPUT, "extra": True}), 0, "schema_validation_failed"),
        ("", 7, "nonzero_exit"),
    ],
)
async def test_protocol_failures_are_sanitized(stdout, returncode, code):
    from server.codex_runtime import CodexRuntimeError

    process = FakeProcess(stdout=stdout, stderr="SECRET-STDERR", returncode=returncode)
    executor = executor_with_process(process, {})
    with pytest.raises(CodexRuntimeError, match=code) as captured:
        await executor.execute_stage(
            prompt="SECRET-PROMPT",
            schema_path=Path("server/schemas/module.schema.json").resolve(),
            model="gpt-5.6-sol",
            effort="medium",
        )
    assert "SECRET" not in str(captured.value)


@pytest.mark.asyncio
async def test_curated_evidence_failure_retains_builder_detail_outside_public_message():
    from server.codex_runtime import CodexRuntimeError

    process = FakeProcess(stderr="CURATED-UPSTREAM-DETAIL", returncode=7)
    executor = executor_with_process(process, {}, record_runtime=True)
    with pytest.raises(CodexRuntimeError, match="nonzero_exit") as captured:
        await executor.execute_stage(
            prompt="repository-owned fixture",
            schema_path=Path("server/schemas/module.schema.json").resolve(),
            model="gpt-5.6-sol",
            effort="medium",
            public=False,
            evidence_fixture_id="moon_phases_ar",
        )
    assert str(captured.value) == "nonzero_exit"
    assert captured.value.builder_detail == "CURATED-UPSTREAM-DETAIL"


@pytest.mark.asyncio
async def test_curated_nonzero_failure_captures_stdout_error_items_and_stderr():
    from server.codex_runtime import CodexRuntimeError

    stdout = "\n".join(
        [
            json.dumps({"type": "error", "message": "UPSTREAM-SCHEMA-ERROR"}),
            json.dumps(
                {
                    "type": "turn.failed",
                    "error": {"message": "TURN-FAILED-DETAIL"},
                }
            ),
        ]
    )
    process = FakeProcess(stdout=stdout, stderr="STDERR-DETAIL", returncode=1)
    executor = executor_with_process(process, {}, record_runtime=True)

    with pytest.raises(CodexRuntimeError, match="nonzero_exit") as captured:
        await executor.execute_stage(
            prompt="repository-owned fixture",
            schema_path=Path("server/schemas/module.schema.json").resolve(),
            model="gpt-5.6-sol",
            effort="medium",
            public=False,
            evidence_fixture_id="moon_phases_ar",
        )

    assert "UPSTREAM-SCHEMA-ERROR" in captured.value.builder_detail
    assert "TURN-FAILED-DETAIL" in captured.value.builder_detail
    assert "STDERR-DETAIL" in captured.value.builder_detail


@pytest.mark.asyncio
async def test_zero_exit_stdout_error_item_is_recognized_and_publicly_sanitized():
    from server.codex_runtime import CodexRuntimeError

    stdout = json.dumps({"type": "error", "message": "PRIVATE-UPSTREAM-DETAIL"})
    process = FakeProcess(stdout=stdout)
    executor = executor_with_process(process, {})

    with pytest.raises(CodexRuntimeError, match="upstream_error") as captured:
        await executor.execute_stage(
            prompt="public question",
            schema_path=Path("server/schemas/module.schema.json").resolve(),
            model="gpt-5.6-sol",
            effort="medium",
        )

    assert str(captured.value) == "upstream_error"
    assert captured.value.builder_detail is None


@pytest.mark.asyncio
async def test_timeout_terminates_the_process_group(monkeypatch):
    from server.codex_runtime import CodexRuntimeError

    process = FakeProcess(delay=5)
    signals = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    executor = executor_with_process(process, {}, stage_timeout_seconds=0.01)

    with pytest.raises(CodexRuntimeError, match="stage_timeout"):
        await executor.execute_stage(
            prompt="prompt",
            schema_path=Path("server/schemas/module.schema.json").resolve(),
            model="gpt-5.6-sol",
            effort="low",
        )
    assert signals[0] == (process.pid, signal.SIGTERM)
    assert process.waited is True


@pytest.mark.asyncio
async def test_curated_stage_uses_scaled_timeout_profile():
    process = FakeProcess(success_jsonl(VALID_MODULE_OUTPUT), delay=0.03)
    executor = executor_with_process(
        process,
        {},
        stage_timeout_seconds=0.01,
        evidence_stage_timeout_seconds=0.1,
        record_runtime=True,
    )

    result = await executor.execute_stage(
        prompt="repository-owned fixture",
        schema_path=Path("server/schemas/module.schema.json").resolve(),
        model="gpt-5.6-sol",
        effort="medium",
        public=False,
        evidence_fixture_id="moon_phases_ar",
    )

    assert result.data == VALID_MODULE_OUTPUT


@pytest.mark.asyncio
async def test_call_specific_timeout_overrides_the_stage_profile(monkeypatch):
    from server.codex_runtime import CodexRuntimeError

    process = FakeProcess(success_jsonl(VALID_MODULE_OUTPUT), delay=0.03)
    signals = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    executor = executor_with_process(process, {}, stage_timeout_seconds=0.1)

    with pytest.raises(CodexRuntimeError, match="stage_timeout"):
        await executor.execute_stage(
            prompt="bounded QA",
            schema_path=Path("server/schemas/module.schema.json").resolve(),
            model="gpt-5.6-sol",
            effort="medium",
            timeout_seconds=0.01,
        )

    assert signals[0] == (process.pid, signal.SIGTERM)


@pytest.mark.asyncio
async def test_cancellation_terminates_process_group_and_propagates(monkeypatch):
    process = FakeProcess(delay=5)
    signals = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    executor = executor_with_process(process, {})
    task = asyncio.create_task(
        executor.execute_stage(
            prompt="prompt",
            schema_path=Path("server/schemas/module.schema.json").resolve(),
            model="gpt-5.6-sol",
            effort="low",
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert signals[0] == (process.pid, signal.SIGTERM)
