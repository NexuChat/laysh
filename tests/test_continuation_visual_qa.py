from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError

from server.codex_runtime import StageExecution
from tests.golden_cases import VALID_UNDERSTANDING

VISUAL_VERDICT = {
    "actor_visible": True,
    "action_performed": True,
    "physically_consistent": True,
    "defects": [],
}


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute_stage(self, **kwargs):
        self.calls.append(kwargs)
        return StageExecution(
            data=VISUAL_VERDICT,
            thread_id="visual-qa-thread",
            model=kwargs["model"],
            elapsed_ms=19,
        )


class FakeProcess:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout.encode()
        self.stderr = b""
        self.returncode = None
        self.pid = 43211
        self.stdin_data: bytes | None = None

    async def communicate(self, value: bytes):
        self.stdin_data = value
        self.returncode = 0
        return self.stdout, self.stderr


def _success_jsonl(document: dict[str, object]) -> str:
    return "\n".join(
        (
            json.dumps({"type": "thread.started", "thread_id": "visual-thread"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": json.dumps(document)},
                }
            ),
            json.dumps({"type": "turn.completed"}),
        )
    )


def _screenshots(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "screens"
    root.mkdir(parents=True)
    paths = tuple(root / f"state-{index}.png" for index in range(3))
    for path in paths:
        path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    return paths


def test_visual_qa_schema_is_closed_strict_and_requires_the_four_verdict_fields():
    from server.codex_runtime import validate_strict_output_schema
    from server.schemas import load_schema, validate_document

    schema = load_schema("visual_qa.schema.json")

    assert validate_document(VISUAL_VERDICT, schema) == VISUAL_VERDICT
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "actor_visible",
        "action_performed",
        "physically_consistent",
        "defects",
    }
    assert validate_strict_output_schema(schema) == []
    with pytest.raises(ValidationError):
        validate_document({**VISUAL_VERDICT, "reasoning": "not allowed"}, schema)


@pytest.mark.asyncio
async def test_curated_visual_qa_routes_three_bounded_images_to_terra(tmp_path):
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.settings import Settings

    screenshots = _screenshots(tmp_path)
    executor = RecordingExecutor()
    backend = CodexBackend(executor=executor, settings=Settings())

    result = await backend.visual_qa(
        VALID_UNDERSTANDING,
        screenshots,
        {"passed": True, "gate_names": ["physics_motion", "browser"]},
        runtime_context=RuntimeContext(
            public=False,
            evidence_fixture_id="moon_phases_ar",
        ),
    )

    assert result.data == VISUAL_VERDICT
    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert call["model"] == "gpt-5.6-terra"
    assert call["effort"] == "low"
    assert call["schema_path"].name == "visual_qa.schema.json"
    assert call["image_paths"] == screenshots
    assert call["public"] is False
    assert call["evidence_fixture_id"] == "moon_phases_ar"
    assert "moon" in call["prompt"] and "orbits" in call["prompt"]
    assert "module_js" not in call["prompt"]


@pytest.mark.asyncio
async def test_visual_qa_is_not_available_on_the_public_learner_path(tmp_path):
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.codex_runtime import CodexPolicyError
    from server.settings import Settings

    executor = RecordingExecutor()
    backend = CodexBackend(executor=executor, settings=Settings())

    with pytest.raises(CodexPolicyError, match="visual_qa_curated_only"):
        await backend.visual_qa(
            VALID_UNDERSTANDING,
            _screenshots(tmp_path),
            {"passed": True, "gate_names": ["browser"]},
            runtime_context=RuntimeContext(public=True),
        )
    assert executor.calls == []

    with pytest.raises(CodexPolicyError, match="visual_qa_requires_passing_gates"):
        await backend.visual_qa(
            VALID_UNDERSTANDING,
            _screenshots(tmp_path / "failed-gate"),
            {"passed": False, "gate_names": ["physics_motion"]},
            runtime_context=RuntimeContext(
                public=False,
                evidence_fixture_id="moon_phases_ar",
            ),
        )
    assert executor.calls == []


@pytest.mark.asyncio
async def test_executor_attaches_only_three_allowlisted_evidence_images(tmp_path):
    from server.codex_runtime import CodexExecutor, CodexPolicyError

    screenshots = _screenshots(tmp_path)
    process = FakeProcess(_success_jsonl(VISUAL_VERDICT))
    captured: dict[str, object] = {}

    async def factory(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return process

    executor = CodexExecutor(
        process_factory=factory,
        record_runtime=True,
        evidence_allowlist=frozenset({"moon_phases_ar"}),
        evidence_image_roots=(tmp_path / "screens",),
    )
    schema = Path("server/schemas/visual_qa.schema.json").resolve()
    result = await executor.execute_stage(
        prompt="bounded visual verdict",
        schema_path=schema,
        model="gpt-5.6-terra",
        effort="low",
        public=False,
        evidence_fixture_id="moon_phases_ar",
        image_paths=screenshots,
    )

    args = captured["args"]
    image_index = args.index("--image")
    assert args[image_index + 1 : image_index + 4] == tuple(
        str(path.resolve()) for path in screenshots
    )
    assert "bounded visual verdict" not in args
    assert process.stdin_data == b"bounded visual verdict"
    assert result.data == VISUAL_VERDICT

    with pytest.raises(CodexPolicyError, match="visual_evidence_image_count"):
        await executor.execute_stage(
            prompt="too few",
            schema_path=schema,
            model="gpt-5.6-terra",
            effort="low",
            public=False,
            evidence_fixture_id="moon_phases_ar",
            image_paths=screenshots[:2],
        )
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"fixture")
    with pytest.raises(CodexPolicyError, match="visual_evidence_path_not_allowlisted"):
        await executor.execute_stage(
            prompt="outside root",
            schema_path=schema,
            model="gpt-5.6-terra",
            effort="low",
            public=False,
            evidence_fixture_id="moon_phases_ar",
            image_paths=(screenshots[0], screenshots[1], outside),
        )


def test_visual_qa_can_never_promote_a_failed_deterministic_gate():
    from scripts.generate_goldens import _semantic_visual_qa_passed
    from server.visual_qa import semantic_visual_qa_report

    approved = semantic_visual_qa_report(
        VISUAL_VERDICT,
        deterministic_passed=True,
        browser_passed=True,
    )
    blocked = semantic_visual_qa_report(
        VISUAL_VERDICT,
        deterministic_passed=False,
        browser_passed=True,
    )

    assert approved["passed"] is True
    assert blocked["passed"] is False
    assert blocked["failures"][0]["code"] == "deterministic_gates_authoritative"
    assert _semantic_visual_qa_passed(
        VISUAL_VERDICT,
        deterministic_passed=False,
        browser_passed=True,
    ) is False


def test_golden_promotion_stops_at_a_failed_gate_even_with_a_passing_visual_verdict(
    tmp_path, monkeypatch
):
    import scripts.generate_goldens as goldens
    from server.settings import Settings

    fixture_id = "moon_phases_ar"
    golden_id = "moon_phases"
    candidate_root = tmp_path / "candidates"
    evidence_root = tmp_path / "evidence"
    candidate_root.mkdir()
    evidence_root.mkdir()
    (candidate_root / f"{golden_id}.json").write_text(
        json.dumps(
            {
                "fixture_id": fixture_id,
                "builder_outputs": {
                    "understanding": {},
                    "module_output": {},
                    "qa": {"approved": True},
                    "visual_qa": VISUAL_VERDICT,
                },
            }
        ),
        encoding="utf-8",
    )
    (evidence_root / f"{golden_id}-manual-review.json").write_text(
        "{}\n", encoding="utf-8"
    )
    monkeypatch.setattr(goldens, "CANDIDATE_ROOT", candidate_root)
    monkeypatch.setattr(goldens, "EVIDENCE_ROOT", evidence_root)
    cache_secret = f"fixture-{tmp_path.name}"
    monkeypatch.setattr(
        goldens.Settings,
        "from_env",
        classmethod(lambda _cls: Settings(cache_key_secret=cache_secret)),
    )
    monkeypatch.setattr(goldens, "load_golden_fixtures", lambda: {fixture_id: {}})
    monkeypatch.setattr(goldens, "review_golden_candidate", lambda **_kwargs: {"passed": True})
    monkeypatch.setattr(goldens, "_manual_review_passed", lambda _review: True)
    monkeypatch.setattr(goldens, "_qa_visual_richness_passed", lambda _qa: True)
    monkeypatch.setattr(
        goldens,
        "verify_candidate",
        lambda *_args, **_kwargs: SimpleNamespace(passed=False, artifact=None),
    )

    with pytest.raises(
        ValueError, match="candidate failed authoritative deterministic promotion gates"
    ):
        goldens.promote_candidate(fixture_id, revision="v1.1")


def test_visual_qa_model_setting_is_terra_and_gpt_5_6_only(monkeypatch):
    from server.settings import ALLOWED_RUNTIME_MODELS, Settings

    settings = Settings()
    assert settings.visual_qa_model == "gpt-5.6-terra"
    assert settings.visual_qa_model in ALLOWED_RUNTIME_MODELS

    monkeypatch.setenv("LAYSH_VISUAL_QA_MODEL", "not-gpt-5.6")
    with pytest.raises(ValueError, match="GPT-5.6"):
        Settings.from_env()
