from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING


def test_generation_candidate_spec_is_closed_and_immutable():
    from server.codex_backend import GenerationCandidateSpec

    spec = GenerationCandidateSpec(
        candidate_id="fast",
        ordinal=1,
        model="gpt-5.6-terra",
        effort="medium",
    )

    assert (
        spec.candidate_id,
        spec.ordinal,
        spec.model,
        spec.effort,
    ) == ("fast", 1, "gpt-5.6-terra", "medium")
    with pytest.raises(FrozenInstanceError):
        spec.model = "gpt-5.6-sol"


@pytest.mark.parametrize("candidate_count", [1, 2])
def test_candidate_race_settings_accept_only_the_bounded_public_count(candidate_count):
    from server.settings import Settings

    settings = Settings(
        public_candidate_count=candidate_count,
        max_parallel_model_calls=2,
        max_parallel_browser_gates=1,
    )

    assert settings.public_candidate_count == candidate_count
    assert settings.max_parallel_model_calls == 2
    assert settings.max_parallel_browser_gates == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"public_candidate_count": 0},
        {"public_candidate_count": 3},
        {"max_parallel_model_calls": 0},
        {"max_parallel_browser_gates": 0},
    ],
)
def test_candidate_race_settings_fail_closed_on_unsafe_limits(overrides):
    from server.settings import Settings

    with pytest.raises(ValueError, match="candidate|parallel"):
        Settings(**overrides)


def test_settings_load_candidate_race_limits_from_the_runtime_environment(monkeypatch):
    from server.settings import Settings

    monkeypatch.setenv("LAYSH_PUBLIC_CANDIDATE_COUNT", "2")
    monkeypatch.setenv("LAYSH_MAX_PARALLEL_MODEL_CALLS", "2")
    monkeypatch.setenv("LAYSH_MAX_PARALLEL_BROWSER_GATES", "1")

    settings = Settings.from_env()

    assert settings.public_candidate_count == 2
    assert settings.max_parallel_model_calls == 2
    assert settings.max_parallel_browser_gates == 1


class _ImmediateExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute_stage(self, **kwargs):
        from server.codex_runtime import StageExecution

        self.calls.append(kwargs)
        return StageExecution(
            data=VALID_MODULE_OUTPUT,
            thread_id=f"offline-{len(self.calls)}",
            model=kwargs["model"],
            elapsed_ms=1,
        )


def _complex_understanding() -> dict[str, Any]:
    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["secondary_parameter"] = {
        "id": "distance_m",
        "label": "المسافة",
        "unit": "m",
        "min": 1,
        "max": 10,
        "default": 5,
        "step": 1,
    }
    return understanding


@pytest.mark.asyncio
async def test_bounded_public_generation_plans_terra_medium_and_sol_medium():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.settings import Settings

    backend = CodexBackend(
        executor=_ImmediateExecutor(),
        settings=Settings(public_candidate_count=2),
    )

    plan = backend.generation_candidate_specs(
        VALID_UNDERSTANDING,
        runtime_context=RuntimeContext(public=True),
    )

    assert [
        (spec.candidate_id, spec.ordinal, spec.model, spec.effort) for spec in plan
    ] == [
        ("fast", 1, "gpt-5.6-terra", "medium"),
        ("quality", 2, "gpt-5.6-sol", "medium"),
    ]


@pytest.mark.asyncio
async def test_complex_public_generation_races_terra_and_sol_medium_candidates():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.settings import Settings

    backend = CodexBackend(
        executor=_ImmediateExecutor(),
        settings=Settings(public_candidate_count=2),
    )

    plan = backend.generation_candidate_specs(
        _complex_understanding(),
        runtime_context=RuntimeContext(public=True),
    )

    assert [
        (spec.candidate_id, spec.ordinal, spec.model, spec.effort) for spec in plan
    ] == [
        ("fast", 1, "gpt-5.6-terra", "medium"),
        ("quality", 2, "gpt-5.6-sol", "medium"),
    ]


class _BlockingExecutor:
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.two_entered = asyncio.Event()
        self.release = asyncio.Event()

    async def execute_stage(self, **kwargs):
        from server.codex_runtime import StageExecution

        self.active += 1
        self.peak = max(self.peak, self.active)
        if self.active == 2:
            self.two_entered.set()
        try:
            await self.release.wait()
            return StageExecution(
                data=VALID_MODULE_OUTPUT,
                thread_id=f"offline-{kwargs['model']}",
                model=kwargs["model"],
                elapsed_ms=1,
            )
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_model_call_limit_is_global_across_concurrent_candidates():
    from server.codex_backend import CodexBackend, GenerationCandidateSpec, RuntimeContext
    from server.settings import Settings

    executor = _BlockingExecutor()
    backend = CodexBackend(
        executor=executor,
        settings=Settings(max_parallel_model_calls=2),
    )
    context = RuntimeContext(public=True)
    specs = [
        GenerationCandidateSpec("fast", 1, "gpt-5.6-terra", "medium"),
        GenerationCandidateSpec("quality", 2, "gpt-5.6-sol", "low"),
        GenerationCandidateSpec("quality", 2, "gpt-5.6-sol", "low"),
    ]

    tasks = [
        asyncio.create_task(
            backend.generate(
                VALID_UNDERSTANDING,
                runtime_context=context,
                candidate_spec=spec,
            )
        )
        for spec in specs
    ]
    await asyncio.wait_for(executor.two_entered.wait(), timeout=1)
    await asyncio.sleep(0)

    assert executor.active == 2
    assert executor.peak == 2

    executor.release.set()
    await asyncio.gather(*tasks)
    assert executor.peak == 2


class _RecordingCache:
    def __init__(self, backend: _RaceBackend) -> None:
        self.backend = backend
        self.writes: list[dict[str, Any]] = []

    def lookup(self, **kwargs):
        del kwargs
        return None

    def write_verified(self, **kwargs):
        assert self.backend.qa_calls == 1, "QA must finish before publication/cache"
        self.writes.append(kwargs)


class _RaceBackend:
    backend_name = "mock"

    def __init__(self, outcomes: dict[str, tuple[float | None, str]]) -> None:
        from server.codex_backend import MockCodexBackend
        from server.settings import Settings

        self._delegate = MockCodexBackend()
        self.settings = Settings(
            public_candidate_count=2,
            max_parallel_model_calls=2,
            max_parallel_browser_gates=1,
        )
        self.outcomes = outcomes
        self.generate_calls = 0
        self.heal_calls = 0
        self.qa_calls = 0
        self.generated: list[str] = []
        self.cancelled: list[str] = []
        self.qa_sources: list[str] = []

    def scenario_for(self, question: str) -> str:
        return self._delegate.scenario_for(question)

    async def understand(self, *args, **kwargs):
        return await self._delegate.understand(*args, **kwargs)

    def generation_candidate_specs(self, understanding, *, runtime_context=None):
        from server.codex_backend import CodexBackend

        return CodexBackend.generation_candidate_specs(
            self,
            understanding,
            runtime_context=runtime_context,
        )

    async def generate(
        self,
        understanding,
        scenario="success",
        *,
        runtime_context=None,
        candidate_spec,
    ):
        from server.codex_runtime import StageExecution
        from server.schemas import validate_module_output

        del scenario, runtime_context
        self.generate_calls += 1
        candidate_id = candidate_spec.candidate_id
        self.generated.append(candidate_id)
        delay, outcome = self.outcomes[candidate_id]
        try:
            if delay is None:
                await asyncio.Future()
            elif delay:
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            self.cancelled.append(candidate_id)
            raise
        source = f"/* {outcome.upper()}_CANDIDATE:{candidate_id} */\n" + self._delegate._good_source
        data = validate_module_output(
            {
                **VALID_MODULE_OUTPUT,
                "module_js": source,
                "output_names": list(understanding["module_spec"]["outputs"]),
            }
        )
        return StageExecution(
            data=data,
            thread_id=f"offline-{candidate_id}",
            model=candidate_spec.model,
            elapsed_ms=max(1, int((delay or 0) * 1_000)),
        )

    async def heal(self, *args, **kwargs):
        self.heal_calls += 1
        return await self._delegate.heal(*args, **kwargs)

    async def qa(self, module_output, *args, **kwargs):
        self.qa_calls += 1
        self.qa_sources.append(module_output["module_js"])
        return await self._delegate.qa(module_output, *args, **kwargs)


def _verification_for_candidate(module_output, _understanding):
    from server.verify import VerificationResult

    source = module_output["module_js"]
    normalized_source = source.casefold()
    if "bad_candidate" in normalized_source:
        return VerificationResult(
            passed=False,
            check_count=7,
            failures=[
                {
                    "gate": "invariant",
                    "code": "synthetic_candidate_failure",
                    "expected": {"candidate_valid": True},
                    "actual": {"candidate_valid": False},
                }
            ],
            artifact=None,
            node_report={},
        )
    marker = "quality" if "candidate:quality" in normalized_source else "fast"
    return VerificationResult(
        passed=True,
        check_count=11,
        failures=[],
        artifact=f"<!doctype html><html><body>{marker}</body></html>",
        node_report={"candidate": marker},
    )


@pytest.mark.asyncio
async def test_bad_fast_candidate_does_not_preempt_later_good_sol_candidate(
    monkeypatch,
):
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager

    monkeypatch.setattr("server.pipeline.verify_candidate", _verification_for_candidate)
    backend = _RaceBackend(
        {
            "fast": (0, "bad"),
            "quality": (0.02, "good"),
        }
    )
    cache = _RecordingCache(backend)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=cache,
    )

    record = manager.start("success", "ar")
    await record.task

    assert record.status == "complete"
    assert record.simulation is not None
    assert record.simulation.effective_model == "gpt-5.6-sol"
    assert backend.generate_calls == 2
    assert backend.heal_calls == 0
    assert backend.qa_calls == 1
    assert "candidate:quality" in backend.qa_sources[0].casefold()
    assert len(cache.writes) == 1
    assert "quality" in cache.writes[0]["artifact"]
    assert "fast" not in cache.writes[0]["artifact"]
    event_types = [event.type for event in record.events]
    assert event_types[0] == "answer"
    assert event_types.index("answer") < event_types.index("result")


@pytest.mark.asyncio
async def test_good_fast_candidate_wins_and_cancels_the_slow_quality_candidate(
    monkeypatch,
):
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager

    monkeypatch.setattr("server.pipeline.verify_candidate", _verification_for_candidate)
    backend = _RaceBackend(
        {
            "fast": (0, "good"),
            "quality": (None, "good"),
        }
    )
    cache = _RecordingCache(backend)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=cache,
    )

    record = manager.start("success", "ar")
    await record.task

    assert record.status == "complete"
    assert record.simulation is not None
    assert record.simulation.effective_model == "gpt-5.6-terra"
    assert backend.generate_calls == 2
    assert backend.cancelled == ["quality"]
    assert backend.qa_calls == 1
    assert "candidate:fast" in backend.qa_sources[0].casefold()
    assert len(cache.writes) == 1
    assert "fast" in cache.writes[0]["artifact"]
    assert "quality" not in cache.writes[0]["artifact"]
    event_types = [event.type for event in record.events]
    assert event_types[0] == "answer"
    assert event_types.index("answer") < event_types.index("verification")
    assert event_types.index("answer") < event_types.index("result")
