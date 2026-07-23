from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from server.codex_backend import MockCodexBackend, RuntimeContext
from server.codex_runtime import StageExecution
from tests.golden_cases import VALID_UNDERSTANDING
from tests.test_parallel_fragment_generation import PHYSICS_FRAGMENT, VISUAL_FRAGMENT

FAILURE_CODE = "scientific_output_reference_required"
RAW_CONTRACT_MESSAGE = "scientific geometry must consume a declared output"
INVALID_FRAGMENT_CANARY = "#C0FFEE"
RECOVERED_VISUAL_COLOR = "#1A2B3C"
RECOVERED_PHYSICS_SUMMARY = "Recovered from fixed understanding fixtures."
VERIFIED_ARTIFACT = (
    "<!doctype html><html><body>recovered-valid-visual-fragment</body></html>"
)


def _semantic_invalid_visual() -> dict[str, Any]:
    visual = deepcopy(VISUAL_FRAGMENT)
    visual["background"]["top_color"] = INVALID_FRAGMENT_CANARY
    visual["commands"][0]["opacity"] = "0.75"
    return visual


def _valid_retry_visual() -> dict[str, Any]:
    visual = deepcopy(VISUAL_FRAGMENT)
    visual["commands"][0]["fill_color"] = RECOVERED_VISUAL_COLOR
    return visual


def _assert_schema_valid_but_semantic_invalid(visual: dict[str, Any]) -> None:
    from server.fragment_generation import validate_visual_fragment
    from server.schemas import ContractError, load_schema, validate_document

    assert (
        validate_document(deepcopy(visual), load_schema("visual_fragment.schema.json"))
        == visual
    )
    with pytest.raises(ContractError, match=RAW_CONTRACT_MESSAGE):
        validate_visual_fragment(deepcopy(visual), deepcopy(VALID_UNDERSTANDING))


def test_every_semantic_fragment_failure_has_topic_agnostic_retry_guidance() -> None:
    from server.codex_backend import FRAGMENT_RETRY_HINTS
    from server.fragment_generation import _SEMANTIC_FAILURE_CODES

    emitted_codes = {code for _message, code in _SEMANTIC_FAILURE_CODES}
    assert emitted_codes <= set(FRAGMENT_RETRY_HINTS)
    for code in emitted_codes:
        assert len(FRAGMENT_RETRY_HINTS[code].split()) >= 6
    serialized = " ".join(FRAGMENT_RETRY_HINTS.values()).casefold()
    for topic in ("moon", "ship", "heat", "car", "plane"):
        assert topic not in serialized


def test_visual_prompt_classifies_fixed_context_as_non_scientific() -> None:
    from pathlib import Path

    prompt = (
        Path(__file__).parents[1] / "server" / "prompts" / "generate_visual.md"
    ).read_text(encoding="utf-8")

    assert "Fixed contextual shapes must set `scientific: false`" in prompt
    assert "visibly consume `output_<declared_output_name>`" in prompt


class _FragmentRecoveryBackend(MockCodexBackend):
    def __init__(self, retry_visual: dict[str, Any]) -> None:
        super().__init__()
        self.retry_visual = deepcopy(retry_visual)
        self.fragment_generation_calls: list[dict[str, Any]] = []
        self.regeneration_calls: list[dict[str, Any]] = []

    async def understand(
        self,
        _question: str,
        _locale: str | None,
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> dict[str, Any]:
        self.understand_calls += 1
        assert runtime_context == RuntimeContext(public=True)
        return deepcopy(VALID_UNDERSTANDING)

    async def generate(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        raise AssertionError("the public fragment route must not call monolithic generation")

    async def generate_fragments(
        self,
        understanding: dict[str, Any],
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> tuple[StageExecution, StageExecution]:
        self.fragment_generation_calls.append(
            {
                "understanding": deepcopy(understanding),
                "runtime_context": runtime_context,
            }
        )
        return (
            StageExecution(
                data=deepcopy(PHYSICS_FRAGMENT),
                thread_id="private-initial-physics-fragment",
                model="gpt-5.6-sol",
                elapsed_ms=2,
            ),
            StageExecution(
                data=_semantic_invalid_visual(),
                thread_id="private-initial-visual-fragment",
                model="gpt-5.6-terra",
                elapsed_ms=3,
            ),
        )

    async def regenerate_fragment(
        self,
        role: str,
        understanding: dict[str, Any],
        failure_code: str,
        *,
        repair_attempt: int = 1,
        runtime_context: RuntimeContext | None = None,
    ) -> StageExecution:
        del repair_attempt
        self.regeneration_calls.append(
            {
                "role": role,
                "understanding": deepcopy(understanding),
                "failure_code": failure_code,
                "runtime_context": runtime_context,
            }
        )
        return StageExecution(
            data=deepcopy(self.retry_visual),
            thread_id="private-regenerated-visual-fragment",
            model="gpt-5.6-terra",
            elapsed_ms=5,
        )


class _PhysicsPreflightRecoveryBackend(_FragmentRecoveryBackend):
    def __init__(self) -> None:
        super().__init__(_valid_retry_visual())

    async def generate_fragments(
        self,
        understanding: dict[str, Any],
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> tuple[StageExecution, StageExecution]:
        self.fragment_generation_calls.append(
            {
                "understanding": deepcopy(understanding),
                "runtime_context": runtime_context,
            }
        )
        return (
            StageExecution(
                data=deepcopy(PHYSICS_FRAGMENT),
                thread_id="private-initial-physics-fragment",
                model="gpt-5.6-sol",
                elapsed_ms=2,
            ),
            StageExecution(
                data=deepcopy(VISUAL_FRAGMENT),
                thread_id="private-initial-visual-fragment",
                model="gpt-5.6-terra",
                elapsed_ms=3,
            ),
        )

    async def regenerate_fragment(
        self,
        role: str,
        understanding: dict[str, Any],
        failure_code: str,
        *,
        repair_attempt: int = 1,
        runtime_context: RuntimeContext | None = None,
    ) -> StageExecution:
        del repair_attempt
        self.regeneration_calls.append(
            {
                "role": role,
                "understanding": deepcopy(understanding),
                "failure_code": failure_code,
                "runtime_context": runtime_context,
            }
        )
        recovered = {**deepcopy(PHYSICS_FRAGMENT), "brief_summary": RECOVERED_PHYSICS_SUMMARY}
        return StageExecution(
            data=recovered,
            thread_id="private-regenerated-physics-fragment",
            model="gpt-5.6-sol",
            elapsed_ms=5,
        )


class _VisualPreflightRecoveryBackend(_FragmentRecoveryBackend):
    def __init__(self) -> None:
        super().__init__(_valid_retry_visual())

    async def generate_fragments(
        self,
        understanding: dict[str, Any],
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> tuple[StageExecution, StageExecution]:
        self.fragment_generation_calls.append(
            {
                "understanding": deepcopy(understanding),
                "runtime_context": runtime_context,
            }
        )
        return (
            StageExecution(
                data=deepcopy(PHYSICS_FRAGMENT),
                thread_id="private-initial-physics-fragment",
                model="gpt-5.6-sol",
                elapsed_ms=2,
            ),
            StageExecution(
                data=deepcopy(VISUAL_FRAGMENT),
                thread_id="private-initial-visual-fragment",
                model="gpt-5.6-terra",
                elapsed_ms=3,
            ),
        )


class _SecondBoundedVisualRetryBackend(_FragmentRecoveryBackend):
    def __init__(self) -> None:
        super().__init__(_valid_retry_visual())
        self.repair_attempts: list[int] = []

    async def regenerate_fragment(
        self,
        role: str,
        understanding: dict[str, Any],
        failure_code: str,
        *,
        repair_attempt: int = 1,
        runtime_context: RuntimeContext | None = None,
    ) -> StageExecution:
        self.repair_attempts.append(repair_attempt)
        self.regeneration_calls.append(
            {
                "role": role,
                "understanding": deepcopy(understanding),
                "failure_code": failure_code,
                "runtime_context": runtime_context,
            }
        )
        return StageExecution(
            data=(
                _semantic_invalid_visual()
                if repair_attempt == 1
                else _valid_retry_visual()
            ),
            thread_id=f"private-regenerated-visual-fragment-{repair_attempt}",
            model="gpt-5.6-terra" if repair_attempt == 1 else "gpt-5.6-sol",
            elapsed_ms=5,
        )


class _RecordingCache:
    def __init__(self) -> None:
        self.lookups: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []

    def lookup(self, **kwargs: Any) -> None:
        self.lookups.append(deepcopy(kwargs))
        return None

    def write_verified(self, **kwargs: Any) -> None:
        self.writes.append(deepcopy(kwargs))


def _public_surface(record: Any) -> str:
    return json.dumps(
        {
            "result": record.public_result().model_dump(mode="json"),
            "sse_events": [event.model_dump(mode="json") for event in record.events],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _assert_public_surface_is_sanitized(record: Any) -> None:
    public_surface = _public_surface(record)
    for private_value in (
        "ContractError",
        RAW_CONTRACT_MESSAGE,
        INVALID_FRAGMENT_CANARY,
        "private-initial-physics-fragment",
        "private-initial-visual-fragment",
        "private-regenerated-visual-fragment",
    ):
        assert private_value not in public_surface


@pytest.mark.asyncio
async def test_codex_backend_regenerates_one_role_with_safe_fixed_feedback() -> None:
    from pathlib import Path

    from server.codex_backend import CodexBackend
    from server.settings import Settings

    class RecordingExecutor:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def execute_stage(self, **kwargs: Any) -> StageExecution:
            self.calls.append(kwargs)
            return StageExecution(
                data=_valid_retry_visual(),
                thread_id="private-runtime-thread",
                model=kwargs["model"],
                elapsed_ms=4,
            )

    executor = RecordingExecutor()
    backend = CodexBackend(executor=executor, settings=Settings())

    result = await backend.regenerate_fragment(
        "visual",
        deepcopy(VALID_UNDERSTANDING),
        FAILURE_CODE,
        runtime_context=RuntimeContext(public=True),
    )

    assert result.data == _valid_retry_visual()
    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert Path(call["schema_path"]).name == "visual_fragment.schema.json"
    assert call["model"] == "gpt-5.6-terra"
    assert call["effort"] == "medium"
    assert call["public"] is True
    assert f"Failure code: {FAILURE_CODE}." in call["prompt"]
    retry_guidance = call["prompt"].split("DETERMINISTIC_RETRY:", 1)[1]
    assert "every scientific circle or ellipse" in retry_guidance.casefold()
    assert "scientific false" in retry_guidance.casefold()
    assert "visibly use output_<declared_name>" in retry_guidance.casefold()
    assert RAW_CONTRACT_MESSAGE not in call["prompt"]
    assert INVALID_FRAGMENT_CANARY not in call["prompt"]


@pytest.mark.asyncio
async def test_second_visual_fragment_retry_routes_to_sol_medium() -> None:
    from pathlib import Path

    from server.codex_backend import CodexBackend
    from server.settings import Settings

    class RecordingExecutor:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def execute_stage(self, **kwargs: Any) -> StageExecution:
            self.calls.append(kwargs)
            return StageExecution(
                data=_valid_retry_visual(),
                thread_id="private-final-visual-retry",
                model=kwargs["model"],
                elapsed_ms=4,
            )

    executor = RecordingExecutor()
    backend = CodexBackend(executor=executor, settings=Settings())

    await backend.regenerate_fragment(
        "visual",
        deepcopy(VALID_UNDERSTANDING),
        FAILURE_CODE,
        repair_attempt=2,
        runtime_context=RuntimeContext(public=True),
    )

    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert Path(call["schema_path"]).name == "visual_fragment.schema.json"
    assert call["model"] == "gpt-5.6-sol"
    assert call["effort"] == "medium"
    assert "attempt 2 of 2" in call["prompt"]


@pytest.mark.asyncio
async def test_ellipse_relation_retry_receives_actionable_safe_contract_guidance() -> None:
    from server.codex_backend import CodexBackend
    from server.settings import Settings

    class RecordingExecutor:
        def __init__(self) -> None:
            self.prompt = ""

        async def execute_stage(self, **kwargs: Any) -> StageExecution:
            self.prompt = kwargs["prompt"]
            return StageExecution(
                data=_valid_retry_visual(),
                thread_id="private-runtime-thread",
                model=kwargs["model"],
                elapsed_ms=4,
            )

    executor = RecordingExecutor()
    backend = CodexBackend(executor=executor, settings=Settings())

    await backend.regenerate_fragment(
        "visual",
        deepcopy(VALID_UNDERSTANDING),
        "unsupported_ellipse_relation",
        runtime_context=RuntimeContext(public=True),
    )

    assert "use one scientific ellipse" in executor.prompt.casefold()
    assert "supporting pieces" in executor.prompt.casefold()


@pytest.mark.asyncio
async def test_undeclared_physics_name_retry_explains_how_to_inline_constants() -> None:
    from server.codex_backend import CodexBackend
    from server.settings import Settings

    class RecordingExecutor:
        def __init__(self) -> None:
            self.prompt = ""

        async def execute_stage(self, **kwargs: Any) -> StageExecution:
            self.prompt = kwargs["prompt"]
            return StageExecution(
                data=deepcopy(PHYSICS_FRAGMENT),
                thread_id="private-runtime-thread",
                model=kwargs["model"],
                elapsed_ms=4,
            )

    executor = RecordingExecutor()
    backend = CodexBackend(executor=executor, settings=Settings())

    await backend.regenerate_fragment(
        "physics",
        deepcopy(VALID_UNDERSTANDING),
        "undeclared_expression_name",
        runtime_context=RuntimeContext(public=True),
    )

    prompt = executor.prompt.casefold()
    assert "finite numeric literals" in prompt
    assert "exact declared parameter ids" in prompt
    assert "symbolic constants" in prompt


@pytest.mark.asyncio
async def test_visual_quality_retry_receives_bounded_general_guidance() -> None:
    from server.codex_backend import CodexBackend
    from server.settings import Settings

    class RecordingExecutor:
        def __init__(self) -> None:
            self.prompt = ""

        async def execute_stage(self, **kwargs: Any) -> StageExecution:
            self.prompt = kwargs["prompt"]
            return StageExecution(
                data=_valid_retry_visual(),
                thread_id="private-runtime-thread",
                model=kwargs["model"],
                elapsed_ms=4,
            )

    executor = RecordingExecutor()
    backend = CodexBackend(executor=executor, settings=Settings())

    await backend.regenerate_fragment(
        "visual",
        deepcopy(VALID_UNDERSTANDING),
        "visual_quality_review_failed",
        runtime_context=RuntimeContext(public=True),
    )

    prompt = executor.prompt.casefold()
    assert "scene depth" in prompt
    assert "reactive feedback" in prompt
    assert "preserving the fixed physics" in prompt
    assert "mobile" in prompt


@pytest.mark.asyncio
async def test_public_job_regenerates_only_the_invalid_visual_then_verifies_and_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager
    from server.verify import VerificationResult

    invalid_visual = _semantic_invalid_visual()
    _assert_schema_valid_but_semantic_invalid(invalid_visual)
    backend = _FragmentRecoveryBackend(_valid_retry_visual())
    cache = _RecordingCache()
    deterministic_inputs: list[dict[str, Any]] = []
    browser_inputs: list[str] = []

    def deterministic_verifier(
        module_output: dict[str, Any],
        understanding: dict[str, Any],
    ) -> VerificationResult:
        deterministic_inputs.append(deepcopy(module_output))
        assert understanding == VALID_UNDERSTANDING
        assert RECOVERED_VISUAL_COLOR in module_output["module_js"]
        assert INVALID_FRAGMENT_CANARY not in module_output["module_js"]
        return VerificationResult(
            passed=True,
            check_count=7,
            failures=[],
            artifact=VERIFIED_ARTIFACT,
            node_report={"passed": True},
        )

    def browser_verifier(artifact: str) -> BrowserVerificationResult:
        browser_inputs.append(artifact)
        return BrowserVerificationResult.passing()

    monkeypatch.setattr("server.pipeline.verify_candidate", deterministic_verifier)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=browser_verifier,
        cache=cache,
    )

    record = manager.start("success", "ar")
    assert record.task is not None
    await record.task

    assert record.status == "complete"
    assert backend.fragment_generation_calls == [
        {
            "understanding": VALID_UNDERSTANDING,
            "runtime_context": RuntimeContext(public=True),
        }
    ]
    assert backend.regeneration_calls == [
        {
            "role": "visual",
            "understanding": VALID_UNDERSTANDING,
            "failure_code": FAILURE_CODE,
            "runtime_context": RuntimeContext(public=True),
        }
    ]
    assert len(deterministic_inputs) == 2
    assert browser_inputs == [VERIFIED_ARTIFACT]
    assert len(cache.writes) == 1
    assert cache.writes[0]["artifact"] == VERIFIED_ARTIFACT
    assert record.artifact == VERIFIED_ARTIFACT
    assert list(manager.artifacts.values()) == [VERIFIED_ARTIFACT]
    assert record.simulation is not None
    assert record.fallback is None
    _assert_public_surface_is_sanitized(record)


@pytest.mark.asyncio
async def test_public_job_uses_second_bounded_visual_retry_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager
    from server.verify import VerificationResult

    backend = _SecondBoundedVisualRetryBackend()
    deterministic_inputs: list[dict[str, Any]] = []

    def deterministic_verifier(
        module_output: dict[str, Any],
        understanding: dict[str, Any],
    ) -> VerificationResult:
        deterministic_inputs.append(deepcopy(module_output))
        assert understanding == VALID_UNDERSTANDING
        assert RECOVERED_VISUAL_COLOR in module_output["module_js"]
        assert INVALID_FRAGMENT_CANARY not in module_output["module_js"]
        return VerificationResult(
            passed=True,
            check_count=39,
            failures=[],
            artifact=VERIFIED_ARTIFACT,
            node_report={"passed": True},
        )

    monkeypatch.setattr("server.pipeline.verify_candidate", deterministic_verifier)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _artifact: BrowserVerificationResult.passing(),
    )

    record = manager.start("success", "ar")
    assert record.task is not None
    await record.task

    assert record.status == "complete"
    assert backend.repair_attempts == [1, 2]
    assert len(backend.regeneration_calls) == 2
    assert backend.heal_calls == 0
    assert len(deterministic_inputs) == 2


@pytest.mark.asyncio
async def test_public_fragment_fixture_failure_regenerates_physics_before_heal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager
    from server.verify import VerificationResult

    backend = _PhysicsPreflightRecoveryBackend()
    deterministic_inputs: list[dict[str, Any]] = []

    def deterministic_verifier(
        module_output: dict[str, Any],
        understanding: dict[str, Any],
    ) -> VerificationResult:
        deterministic_inputs.append(deepcopy(module_output))
        assert understanding == VALID_UNDERSTANDING
        if len(deterministic_inputs) == 1:
            return VerificationResult(
                passed=False,
                check_count=22,
                failures=[
                    {
                        "gate": "invariant",
                        "code": "numeric_fixture_mismatch",
                        "expected": {"fixture_match": True},
                        "actual": {"fixture_match": False},
                    }
                ],
                artifact=None,
                node_report={"passed": False},
            )
        assert RECOVERED_PHYSICS_SUMMARY in module_output["brief_summary"]
        return VerificationResult(
            passed=True,
            check_count=30,
            failures=[],
            artifact=VERIFIED_ARTIFACT,
            node_report={"passed": True},
        )

    monkeypatch.setattr("server.pipeline.verify_candidate", deterministic_verifier)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _artifact: BrowserVerificationResult.passing(),
    )

    record = manager.start("success", "ar")
    assert record.task is not None
    await record.task

    assert record.status == "complete"
    assert backend.regeneration_calls == [
        {
            "role": "physics",
            "understanding": VALID_UNDERSTANDING,
            "failure_code": "physics_fixture_mismatch",
            "runtime_context": RuntimeContext(public=True),
        }
    ]
    assert len(deterministic_inputs) == 2
    assert backend.heal_calls == 0


@pytest.mark.asyncio
async def test_public_causal_preflight_failure_regenerates_visual_before_heal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager
    from server.verify import VerificationResult

    backend = _VisualPreflightRecoveryBackend()
    deterministic_inputs: list[dict[str, Any]] = []

    def deterministic_verifier(
        module_output: dict[str, Any],
        understanding: dict[str, Any],
    ) -> VerificationResult:
        deterministic_inputs.append(deepcopy(module_output))
        assert understanding == VALID_UNDERSTANDING
        if len(deterministic_inputs) == 1:
            return VerificationResult(
                passed=False,
                check_count=31,
                failures=[
                    {
                        "gate": "causal_response",
                        "code": "causal_relation_mismatch",
                        "expected": {"monotonic_actor_response": True},
                        "actual": {"monotonic_actor_response": False},
                    }
                ],
                artifact=None,
                node_report={"passed": False},
            )
        return VerificationResult(
            passed=True,
            check_count=39,
            failures=[],
            artifact=VERIFIED_ARTIFACT,
            node_report={"passed": True},
        )

    monkeypatch.setattr("server.pipeline.verify_candidate", deterministic_verifier)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _artifact: BrowserVerificationResult.passing(),
    )

    record = manager.start("success", "ar")
    assert record.task is not None
    await record.task

    assert record.status == "complete"
    assert backend.regeneration_calls == [
        {
            "role": "visual",
            "understanding": VALID_UNDERSTANDING,
            "failure_code": "visual_causality_mismatch",
            "runtime_context": RuntimeContext(public=True),
        }
    ]
    assert len(deterministic_inputs) == 2
    assert backend.heal_calls == 0


@pytest.mark.asyncio
async def test_public_fragment_verification_failure_regenerates_visual_and_reassembles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager
    from server.verify import VerificationResult

    backend = _VisualPreflightRecoveryBackend()
    verification_calls = 0
    browser_inputs: list[str] = []

    def deterministic_verifier(
        module_output: dict[str, Any],
        understanding: dict[str, Any],
    ) -> VerificationResult:
        nonlocal verification_calls
        verification_calls += 1
        assert understanding == VALID_UNDERSTANDING
        if verification_calls == 2:
            return VerificationResult(
                passed=False,
                check_count=31,
                failures=[
                    {
                        "gate": "causal_response",
                        "code": "causal_relation_mismatch",
                        "expected": {"monotonic_actor_response": True},
                        "actual": {"monotonic_actor_response": False},
                    }
                ],
                artifact=None,
                node_report={"passed": False},
            )
        if verification_calls == 3:
            assert "/* LAYSH_CAUSAL_RESPONSE_V1 */" in module_output["module_js"]
            assert RECOVERED_VISUAL_COLOR in module_output["module_js"]
        return VerificationResult(
            passed=True,
            check_count=39,
            failures=[],
            artifact=VERIFIED_ARTIFACT,
            node_report={"passed": True},
        )

    def browser_verifier(artifact: str) -> BrowserVerificationResult:
        browser_inputs.append(artifact)
        return BrowserVerificationResult.passing()

    monkeypatch.setattr("server.pipeline.verify_candidate", deterministic_verifier)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=browser_verifier,
    )

    record = manager.start("success", "ar")
    assert record.task is not None
    await record.task

    assert record.status == "complete"
    assert backend.regeneration_calls == [
        {
            "role": "visual",
            "understanding": VALID_UNDERSTANDING,
            "failure_code": "visual_causality_mismatch",
            "runtime_context": RuntimeContext(public=True),
        }
    ]
    assert backend.heal_calls == 0
    assert verification_calls == 3
    assert browser_inputs == [VERIFIED_ARTIFACT]


@pytest.mark.asyncio
async def test_public_fragment_route_rejects_unmapped_failure_without_generic_heal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager
    from server.verify import VerificationResult

    backend = _VisualPreflightRecoveryBackend()
    verification_calls = 0
    browser_inputs: list[str] = []

    def deterministic_verifier(
        _module_output: dict[str, Any],
        _understanding: dict[str, Any],
    ) -> VerificationResult:
        nonlocal verification_calls
        verification_calls += 1
        if verification_calls == 2:
            return VerificationResult(
                passed=False,
                check_count=31,
                failures=[
                    {
                        "gate": "runtime_init",
                        "code": "runtime_error",
                        "expected": {"runtime_error": False},
                        "actual": {"runtime_error": True},
                    }
                ],
                artifact=None,
                node_report={"passed": False},
            )
        return VerificationResult(
            passed=True,
            check_count=39,
            failures=[],
            artifact=VERIFIED_ARTIFACT,
            node_report={"passed": True},
        )

    def browser_verifier(artifact: str) -> BrowserVerificationResult:
        browser_inputs.append(artifact)
        return BrowserVerificationResult.passing()

    monkeypatch.setattr("server.pipeline.verify_candidate", deterministic_verifier)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=browser_verifier,
    )

    record = manager.start("success", "ar")
    assert record.task is not None
    await record.task

    assert record.status == "answer_only"
    assert record.fallback is not None
    assert record.fallback.reason_code == "verification_exhausted"
    assert backend.regeneration_calls == []
    assert backend.heal_calls == 0
    assert verification_calls == 2
    assert browser_inputs == []


@pytest.mark.asyncio
async def test_public_fragment_qa_revision_regenerates_visual_and_reverifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager
    from server.verify import VerificationResult

    class RevisingQaBackend(_VisualPreflightRecoveryBackend):
        async def qa(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            del args, kwargs
            self.qa_calls += 1
            visual_richness = {
                "scene_depth": self.qa_calls > 1,
                "physical_light": True,
                "idle_motion": True,
                "reactive_feedback": True,
                "readable_overlays": True,
            }
            return {
                "approved": self.qa_calls > 1,
                "issues": [] if self.qa_calls > 1 else ["scene needs more depth"],
                "replacement_module_js": None,
                "visual_richness": visual_richness,
            }

    backend = RevisingQaBackend()
    verification_calls = 0
    browser_inputs: list[str] = []

    def deterministic_verifier(
        module_output: dict[str, Any],
        _understanding: dict[str, Any],
    ) -> VerificationResult:
        nonlocal verification_calls
        verification_calls += 1
        if verification_calls == 2:
            return VerificationResult(
                passed=False,
                check_count=31,
                failures=[
                    {
                        "gate": "causal_response",
                        "code": "causal_relation_mismatch",
                        "expected": {"monotonic_actor_response": True},
                        "actual": {"monotonic_actor_response": False},
                    }
                ],
                artifact=None,
                node_report={"passed": False},
            )
        if verification_calls >= 3:
            assert "/* LAYSH_CAUSAL_RESPONSE_V1 */" in module_output["module_js"]
        return VerificationResult(
            passed=True,
            check_count=39,
            failures=[],
            artifact=VERIFIED_ARTIFACT,
            node_report={"passed": True},
        )

    def browser_verifier(artifact: str) -> BrowserVerificationResult:
        browser_inputs.append(artifact)
        return BrowserVerificationResult.passing()

    monkeypatch.setattr("server.pipeline.verify_candidate", deterministic_verifier)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=browser_verifier,
    )

    record = manager.start("success", "ar")
    assert record.task is not None
    await record.task

    assert record.status == "complete"
    assert [call["failure_code"] for call in backend.regeneration_calls] == [
        "visual_causality_mismatch",
        "visual_quality_review_failed",
    ]
    assert backend.heal_calls == 0
    assert backend.qa_calls == 2
    assert verification_calls == 4
    assert browser_inputs == [VERIFIED_ARTIFACT, VERIFIED_ARTIFACT]


@pytest.mark.asyncio
async def test_public_job_stops_after_two_invalid_visual_retries_without_verify_or_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager

    invalid_visual = _semantic_invalid_visual()
    _assert_schema_valid_but_semantic_invalid(invalid_visual)
    backend = _FragmentRecoveryBackend(invalid_visual)
    cache = _RecordingCache()
    deterministic_inputs: list[dict[str, Any]] = []
    browser_inputs: list[str] = []

    def unexpected_deterministic_verifier(
        module_output: dict[str, Any],
        understanding: dict[str, Any],
    ) -> None:
        deterministic_inputs.append(
            {
                "module_output": deepcopy(module_output),
                "understanding": deepcopy(understanding),
            }
        )
        raise AssertionError("semantic-invalid fragments must not reach verification")

    def unexpected_browser_verifier(artifact: str) -> BrowserVerificationResult:
        browser_inputs.append(artifact)
        return BrowserVerificationResult.passing()

    monkeypatch.setattr(
        "server.pipeline.verify_candidate",
        unexpected_deterministic_verifier,
    )
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=unexpected_browser_verifier,
        cache=cache,
    )

    record = manager.start("success", "ar")
    assert record.task is not None
    await record.task

    assert backend.regeneration_calls == [
        {
            "role": "visual",
            "understanding": VALID_UNDERSTANDING,
            "failure_code": FAILURE_CODE,
            "runtime_context": RuntimeContext(public=True),
        },
        {
            "role": "visual",
            "understanding": VALID_UNDERSTANDING,
            "failure_code": FAILURE_CODE,
            "runtime_context": RuntimeContext(public=True),
        },
    ]
    assert record.status == "answer_only"
    assert record.answer is not None and record.answer.tldr
    assert record.fallback is not None
    assert record.fallback.reason_code == "generation_failed"
    assert record.simulation is None
    assert record.artifact is None
    assert manager.artifacts == {}
    assert deterministic_inputs == []
    assert browser_inputs == []
    assert cache.writes == []
    _assert_public_surface_is_sanitized(record)
