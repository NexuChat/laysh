from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

import pytest

from tests.golden_cases import VALID_UNDERSTANDING
from tests.test_parallel_fragment_generation import PHYSICS_FRAGMENT, VISUAL_FRAGMENT


class _RecordingCache:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    def lookup(self, **kwargs):
        del kwargs
        return None

    def write_verified(self, **kwargs):
        self.writes.append(kwargs)


class _HybridBackend:
    """Quota-free backend exposing only the proposed neutral public hybrid seams."""

    backend_name = "mock"
    public_generation_strategy = "hybrid"
    public_heal_attempt_limit = 1

    def __init__(self, *, block_stages: bool = False) -> None:
        from server.fragment_generation import assemble_fragments
        from server.settings import Settings

        self.settings = Settings(
            public_generation_strategy="hybrid",
            physics_model="gpt-5.6-luna",
            visual_model="gpt-5.6-terra",
            public_heal_attempt_limit=1,
            max_parallel_model_calls=2,
        )
        self.block_stages = block_stages
        self.release_physics = asyncio.Event()
        self.release_visuals = asyncio.Event()
        if not block_stages:
            self.release_physics.set()
            self.release_visuals.set()
        self.physics_started = asyncio.Event()
        self.physics_completed = asyncio.Event()
        self.visuals_started = {
            "trusted_scene_plan": asyncio.Event(),
            "direct_canvas": asyncio.Event(),
        }
        self.active_visuals = 0
        self.peak_visuals = 0
        self.calls: list[tuple[str, str, str, bool]] = []
        self.heal_calls = 0
        self.heal_requests: list[dict[str, Any]] = []
        self.qa_calls = 0
        self.understand_calls = 0
        self._direct_module = assemble_fragments(
            deepcopy(PHYSICS_FRAGMENT),
            deepcopy(VISUAL_FRAGMENT),
            deepcopy(VALID_UNDERSTANDING),
        )
        self._direct_module["module_js"] = (
            "/* HYBRID_STRATEGY:direct_canvas */\n"
            + self._direct_module["module_js"]
        )

    @staticmethod
    def scenario_for(question: str) -> str:
        del question
        return "success"

    async def understand(self, question, locale, *, runtime_context=None):
        from server.codex_runtime import StageExecution

        del question, locale, runtime_context
        self.understand_calls += 1
        return StageExecution(
            data=deepcopy(VALID_UNDERSTANDING),
            thread_id="private-understand-thread",
            model="gpt-5.6-luna",
            elapsed_ms=3,
        )

    async def generate(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("hybrid strategy must not enter monolithic generation")

    async def generate_fragments(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("hybrid strategy must not enter the legacy fragment route")

    async def generate_hybrid_physics(
        self,
        understanding,
        *,
        runtime_context=None,
    ):
        from server.codex_runtime import StageExecution

        del understanding, runtime_context
        self.calls.append(("physics", "gpt-5.6-luna", "medium", True))
        self.physics_started.set()
        await self.release_physics.wait()
        self.physics_completed.set()
        return StageExecution(
            data=deepcopy(PHYSICS_FRAGMENT),
            thread_id="private-physics-thread",
            model="gpt-5.6-luna",
            elapsed_ms=5,
        )

    async def _enter_visual(self, role: str) -> None:
        assert self.physics_completed.is_set(), (
            "both visual strategies must consume completed, validated physics"
        )
        self.calls.append((role, "gpt-5.6-terra", "medium", True))
        self.active_visuals += 1
        self.peak_visuals = max(self.peak_visuals, self.active_visuals)
        self.visuals_started[role].set()
        try:
            await self.release_visuals.wait()
        finally:
            self.active_visuals -= 1

    async def generate_hybrid_visual_plan(
        self,
        understanding,
        physics_document,
        discovery_plan,
        *,
        runtime_context=None,
    ):
        from server.codex_runtime import StageExecution

        del understanding, physics_document, discovery_plan, runtime_context
        await self._enter_visual("trusted_scene_plan")
        return StageExecution(
            data=deepcopy(VISUAL_FRAGMENT),
            thread_id="private-trusted-visual-thread",
            model="gpt-5.6-terra",
            elapsed_ms=7,
        )

    async def generate_hybrid_visual_module(
        self,
        understanding,
        physics_document,
        discovery_plan,
        *,
        runtime_context=None,
    ):
        from server.codex_runtime import StageExecution

        del understanding, physics_document, discovery_plan, runtime_context
        await self._enter_visual("direct_canvas")
        return StageExecution(
            data=deepcopy(self._direct_module),
            thread_id="private-direct-visual-thread",
            model="gpt-5.6-terra",
            elapsed_ms=8,
        )

    async def heal(
        self,
        module_output,
        understanding,
        failures,
        attempt,
        *,
        runtime_context=None,
    ):
        from server.codex_runtime import StageExecution

        del understanding, runtime_context
        self.heal_calls += 1
        self.heal_requests.append(
            {
                "module_output": deepcopy(module_output),
                "failures": deepcopy(failures),
                "attempt": attempt,
            }
        )
        return StageExecution(
            data=deepcopy(self._direct_module),
            thread_id="private-heal-thread",
            model="gpt-5.6-sol",
            elapsed_ms=9,
        )

    async def qa(self, *args, **kwargs):
        from server.codex_runtime import StageExecution

        del args, kwargs
        self.qa_calls += 1
        return StageExecution(
            data={
                "approved": True,
                "issues": [],
                "replacement_module_js": None,
                "visual_richness": {
                    "scene_depth": True,
                    "physical_light": True,
                    "idle_motion": True,
                    "reactive_feedback": True,
                    "readable_overlays": True,
                },
            },
            thread_id="private-qa-thread",
            model="gpt-5.6-sol",
            elapsed_ms=4,
        )


def _candidate_name(value: str) -> str:
    return (
        "direct_canvas"
        if "HYBRID_STRATEGY:direct_canvas" in value or "direct_canvas" in value
        else "trusted_scene_plan"
    )


class _ProductionGateProbe:
    def __init__(
        self,
        *,
        browser_failures: set[str],
        missing_representation: set[str] | None = None,
        deterministic_check_counts: dict[str, int] | None = None,
    ) -> None:
        self.browser_failures = browser_failures
        self.missing_representation = missing_representation or set()
        self.deterministic_check_counts = deterministic_check_counts or {}
        self.deterministic_calls: list[str] = []
        self.browser_calls: list[str] = []

    def deterministic(self, module_output, understanding):
        from server.verify import VerificationResult

        del understanding
        candidate = _candidate_name(module_output["module_js"])
        self.deterministic_calls.append(candidate)
        representation_missing = candidate in self.missing_representation
        self.missing_representation.discard(candidate)
        return VerificationResult(
            passed=True,
            check_count=self.deterministic_check_counts.get(candidate, 17),
            failures=[],
            artifact=f"<!doctype html><html><body>{candidate}</body></html>",
            node_report={
                "passed": True,
                "candidate": candidate,
                "causal_response": {"passed": True},
                "temporal_causal_matrix": (
                    None if representation_missing else {"passed": True}
                ),
            },
        )

    def browser(self, artifact):
        from server.browser_verify import BrowserVerificationResult

        candidate = _candidate_name(artifact)
        self.browser_calls.append(candidate)
        if candidate not in self.browser_failures:
            return BrowserVerificationResult.passing()
        return BrowserVerificationResult(
            passed=False,
            check_count=8,
            failures=[
                {
                    "gate": "causal_response",
                    "code": "causal_evidence_invalid",
                    "expected": {"causal_response": True},
                    "actual": {"causal_response": False},
                }
            ],
            evidence={
                "ready": True,
                "controlChanged": False,
                "frameChanged": False,
                "runtimeError": False,
                "externalRequests": 0,
            },
        )


class _PhysicsRetryHybridBackend(_HybridBackend):
    def __init__(self) -> None:
        super().__init__()
        self.physics_retry_calls: list[dict[str, Any]] = []

    async def generate_hybrid_physics(
        self,
        understanding,
        *,
        runtime_context=None,
    ):
        result = await super().generate_hybrid_physics(
            understanding,
            runtime_context=runtime_context,
        )
        invalid = deepcopy(result.data)
        invalid["output_names"] = ["unfixed_output"]
        return type(result)(
            data=invalid,
            thread_id=result.thread_id,
            model=result.model,
            elapsed_ms=result.elapsed_ms,
        )

    async def regenerate_fragment(
        self,
        role,
        understanding,
        failure_code,
        **kwargs,
    ):
        from server.codex_runtime import StageExecution

        del understanding
        self.physics_retry_calls.append(
            {
                "role": role,
                "failure_code": failure_code,
                **kwargs,
            }
        )
        return StageExecution(
            data=deepcopy(PHYSICS_FRAGMENT),
            thread_id="private-physics-retry-thread",
            model="gpt-5.6-luna",
            elapsed_ms=6,
        )


class _MarkerlessDirectHybridBackend(_HybridBackend):
    def __init__(self) -> None:
        super().__init__()
        self._direct_module["module_js"] = self._direct_module["module_js"].replace(
            "/* LAYSH_CAUSAL_RESPONSE_V1 */",
            "",
        )


class _ExhaustedPhysicsRetryHybridBackend(_PhysicsRetryHybridBackend):
    async def regenerate_fragment(
        self,
        role,
        understanding,
        failure_code,
        **kwargs,
    ):
        result = await super().regenerate_fragment(
            role,
            understanding,
            failure_code,
            **kwargs,
        )
        invalid = deepcopy(result.data)
        invalid["output_names"] = ["still_unfixed"]
        return type(result)(
            data=invalid,
            thread_id=result.thread_id,
            model=result.model,
            elapsed_ms=result.elapsed_ms,
        )


class _InvalidDirectHybridBackend(_HybridBackend):
    async def generate_hybrid_visual_module(
        self,
        understanding,
        physics_document,
        discovery_plan,
        *,
        runtime_context=None,
    ):
        result = await super().generate_hybrid_visual_module(
            understanding,
            physics_document,
            discovery_plan,
            runtime_context=runtime_context,
        )
        invalid = deepcopy(result.data)
        invalid.pop("output_names")
        return type(result)(
            data=invalid,
            thread_id=result.thread_id,
            model=result.model,
            elapsed_ms=result.elapsed_ms,
        )


class _RepairableTrustedInvalidDirectHybridBackend(_InvalidDirectHybridBackend):
    async def generate_hybrid_visual_plan(
        self,
        understanding,
        physics_document,
        discovery_plan,
        *,
        runtime_context=None,
    ):
        result = await super().generate_hybrid_visual_plan(
            understanding,
            physics_document,
            discovery_plan,
            runtime_context=runtime_context,
        )
        repairable = deepcopy(result.data)
        repairable["commands"][0]["opacity"] = (
            "0.5 + output_lit_fraction * 0"
        )
        return type(result)(
            data=repairable,
            thread_id=result.thread_id,
            model=result.model,
            elapsed_ms=result.elapsed_ms,
        )


class _RepairableTrustedRepresentationHybridBackend(
    _InvalidDirectHybridBackend
):
    async def generate_hybrid_visual_plan(
        self,
        understanding,
        physics_document,
        discovery_plan,
        *,
        runtime_context=None,
    ):
        result = await super().generate_hybrid_visual_plan(
            understanding,
            physics_document,
            discovery_plan,
            runtime_context=runtime_context,
        )
        repairable = deepcopy(result.data)
        repairable["representation"]["proof_channels"][0]["channel"] = "size"
        repairable["commands"][0]["radius"] = (
            "min_dim * 0.12 + output_lit_fraction * 0"
        )
        return type(result)(
            data=repairable,
            thread_id=result.thread_id,
            model=result.model,
            elapsed_ms=result.elapsed_ms,
        )


class _UnrepairableTrustedInvalidDirectHybridBackend(
    _RepairableTrustedInvalidDirectHybridBackend
):
    async def understand(self, *args, **kwargs):
        result = await super().understand(*args, **kwargs)
        insufficient = deepcopy(result.data)
        insufficient["checks"] = insufficient["checks"][:2]
        return type(result)(
            data=insufficient,
            thread_id=result.thread_id,
            model=result.model,
            elapsed_ms=result.elapsed_ms,
        )


class _FixtureRefreshHybridBackend(_HybridBackend):
    async def understand(self, *args, **kwargs):
        result = await super().understand(*args, **kwargs)
        if self.understand_calls == 2:
            refreshed = deepcopy(result.data)
            refreshed["checks"][0]["tolerance"] = 0.02
            return type(result)(
                data=refreshed,
                thread_id=result.thread_id,
                model=result.model,
                elapsed_ms=result.elapsed_ms,
            )
        return result


class _IncompatibleFixtureRefreshHybridBackend(_HybridBackend):
    async def understand(self, *args, **kwargs):
        result = await super().understand(*args, **kwargs)
        if self.understand_calls == 2:
            refreshed = deepcopy(result.data)
            refreshed["key_formula"] = "g = θ"
            return type(result)(
                data=refreshed,
                thread_id=result.thread_id,
                model=result.model,
                elapsed_ms=result.elapsed_ms,
            )
        return result


@pytest.mark.asyncio
async def test_public_hybrid_is_answer_first_then_races_two_post_physics_visuals(
    monkeypatch,
):
    from server.jobs import JobManager

    backend = _HybridBackend(block_stages=True)
    gates = _ProductionGateProbe(browser_failures={"trusted_scene_plan"})
    cache = _RecordingCache()
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
        cache=cache,
    )

    record = manager.start("offline hybrid fixture", "ar")
    await asyncio.wait_for(backend.physics_started.wait(), timeout=1)

    assert [event.type for event in record.events][0] == "answer"
    assert not any(event.is_set() for event in backend.visuals_started.values())

    backend.release_physics.set()
    await asyncio.wait_for(
        asyncio.gather(
            *(event.wait() for event in backend.visuals_started.values())
        ),
        timeout=1,
    )
    assert backend.physics_completed.is_set()
    assert backend.active_visuals == backend.peak_visuals == 2

    backend.release_visuals.set()
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "complete"
    assert record.artifact is not None and "direct_canvas" in record.artifact
    assert sorted(gates.deterministic_calls) == [
        "direct_canvas",
        "trusted_scene_plan",
    ]
    assert sorted(gates.browser_calls) == [
        "direct_canvas",
        "trusted_scene_plan",
    ]
    assert backend.heal_calls == 0
    assert backend.qa_calls == 0
    assert len(cache.writes) == 1
    assert "direct_canvas" in cache.writes[0]["artifact"]
    assert [event.type for event in record.events].index("answer") < [
        event.type for event in record.events
    ].index("result")


@pytest.mark.asyncio
async def test_public_hybrid_repairs_invalid_physics_once_before_visual_generation(
    monkeypatch,
):
    from server.jobs import JobManager

    backend = _PhysicsRetryHybridBackend()
    gates = _ProductionGateProbe(browser_failures=set())
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
    )

    record = manager.start("offline hybrid physics repair", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "complete"
    assert len(backend.physics_retry_calls) == 1
    retry = backend.physics_retry_calls[0]
    assert retry["role"] == "physics"
    assert retry["failure_code"] == "physics_output_contract_mismatch"
    assert retry["repair_attempt"] == 1
    assert retry["prior_fragment"]["output_names"] == ["unfixed_output"]
    assert retry["exact_gate_failures"] == [
        {
            "gate": "fragment_contract",
            "code": "physics_output_contract_mismatch",
            "expected": {"fragment_contract_valid": True},
            "actual": {
                "fragment_contract_valid": False,
                "failure_code": "physics_output_contract_mismatch",
            },
        }
    ]
    assert sorted(gates.browser_calls) == [
        "direct_canvas",
        "trusted_scene_plan",
    ]


@pytest.mark.asyncio
async def test_public_hybrid_exhausted_physics_repair_never_starts_visuals_or_cache(
    monkeypatch,
):
    from server.jobs import JobManager

    backend = _ExhaustedPhysicsRetryHybridBackend()
    gates = _ProductionGateProbe(browser_failures=set())
    cache = _RecordingCache()
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
        cache=cache,
    )

    record = manager.start("offline exhausted physics repair", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "answer_only"
    assert record.answer is not None
    assert len(backend.physics_retry_calls) == 1
    assert not any(event.is_set() for event in backend.visuals_started.values())
    assert gates.deterministic_calls == []
    assert gates.browser_calls == []
    assert cache.writes == []


@pytest.mark.asyncio
async def test_public_hybrid_keeps_valid_candidate_when_sibling_contract_is_invalid(
    monkeypatch,
):
    from server.jobs import JobManager

    backend = _InvalidDirectHybridBackend()
    gates = _ProductionGateProbe(browser_failures=set())
    cache = _RecordingCache()
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
        cache=cache,
    )

    record = manager.start("offline invalid direct sibling", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "complete"
    assert record.artifact is not None
    assert "trusted_scene_plan" in record.artifact
    assert gates.deterministic_calls == ["trusted_scene_plan"]
    assert gates.browser_calls == ["trusted_scene_plan"]
    assert backend.heal_calls == 0
    assert len(cache.writes) == 1


@pytest.mark.asyncio
async def test_public_hybrid_repairs_trusted_causal_channel_before_assembly(
    monkeypatch,
):
    from server.jobs import JobManager

    backend = _RepairableTrustedInvalidDirectHybridBackend()
    gates = _ProductionGateProbe(browser_failures=set())
    cache = _RecordingCache()
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
        cache=cache,
    )

    record = manager.start("offline repairable trusted candidate", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "complete"
    assert record.artifact is not None
    assert gates.deterministic_calls == ["trusted_scene_plan"]
    assert gates.browser_calls == ["trusted_scene_plan"]
    assert backend.heal_calls == 0
    assert len(cache.writes) == 1
    assert record.builder_diagnostics == [
        {
            "type": "deterministic_causal_repair",
            "role": "visual",
            "strategy": "trusted_scene_plan",
            "code": "causal_channel_fixture_response_required",
        }
    ]


@pytest.mark.asyncio
async def test_public_hybrid_repairs_trusted_representation_channel_before_assembly(
    monkeypatch,
):
    from server.jobs import JobManager

    backend = _RepairableTrustedRepresentationHybridBackend()
    gates = _ProductionGateProbe(browser_failures=set())
    cache = _RecordingCache()
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
        cache=cache,
    )

    record = manager.start("offline repairable representation candidate", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "complete"
    assert gates.deterministic_calls == ["trusted_scene_plan"]
    assert gates.browser_calls == ["trusted_scene_plan"]
    assert backend.heal_calls == 0
    assert len(cache.writes) == 1
    assert record.builder_diagnostics == [
        {
            "type": "deterministic_causal_repair",
            "role": "visual",
            "strategy": "trusted_scene_plan",
            "code": "representation_actor_fixture_response_required",
        }
    ]


@pytest.mark.asyncio
async def test_public_hybrid_fails_closed_when_trusted_channel_cannot_be_repaired(
    monkeypatch,
):
    from server.jobs import JobManager

    backend = _UnrepairableTrustedInvalidDirectHybridBackend()
    gates = _ProductionGateProbe(browser_failures=set())
    cache = _RecordingCache()
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
        cache=cache,
    )

    record = manager.start("offline unrepairable trusted candidate", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "answer_only"
    assert record.artifact is None
    assert gates.deterministic_calls == []
    assert gates.browser_calls == []
    assert backend.heal_calls == 0
    assert cache.writes == []
    assert record.builder_diagnostics == []


@pytest.mark.asyncio
async def test_public_hybrid_refreshes_one_suspect_relation_fixture_before_heal(
    monkeypatch,
):
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager
    from server.verify import VerificationResult

    backend = _FixtureRefreshHybridBackend()
    cache = _RecordingCache()
    observed_tolerances: list[float] = []

    def deterministic(module_output, understanding):
        del module_output
        observed_tolerances.append(understanding["checks"][0]["tolerance"])
        call = len(observed_tolerances)
        if call <= 2:
            failures = [
                {
                    "gate": "fixture_integrity",
                    "code": "suspect_relation_fixture",
                    "expected": {"relation": "right_gt_left"},
                    "actual": {"relation": "right_lt_left"},
                }
            ]
        elif call == 3:
            failures = [
                {
                    "gate": "causal_response",
                    "code": "causal_relation_mismatch",
                    "expected": {"monotonic_actor_response": True},
                    "actual": {"monotonic_actor_response": False},
                }
            ]
        else:
            return VerificationResult(
                passed=True,
                check_count=17,
                failures=[],
                artifact="<!doctype html><html><body>verified refresh</body></html>",
                node_report={
                    "passed": True,
                    "causal_response": {"passed": True},
                    "temporal_causal_matrix": {"passed": True},
                },
            )
        return VerificationResult(
            passed=False,
            check_count=9,
            failures=failures,
            artifact=None,
            node_report={"passed": False},
        )

    monkeypatch.setattr("server.pipeline.verify_candidate", deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=cache,
    )

    record = manager.start("offline suspect relation refresh", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "complete"
    assert backend.understand_calls == 2
    assert backend.heal_calls == 1
    assert observed_tolerances == [0.01, 0.01, 0.02, 0.02]
    assert len(cache.writes) == 1


@pytest.mark.asyncio
async def test_public_hybrid_rejects_fixture_refresh_that_changes_fixed_contract(
    monkeypatch,
):
    from server.jobs import JobManager
    from server.verify import VerificationResult

    backend = _IncompatibleFixtureRefreshHybridBackend()
    cache = _RecordingCache()
    verification_calls = 0

    def suspect_fixture_verifier(module_output, understanding):
        nonlocal verification_calls
        del module_output, understanding
        verification_calls += 1
        return VerificationResult(
            passed=False,
            check_count=9,
            failures=[
                {
                    "gate": "fixture_integrity",
                    "code": "suspect_relation_fixture",
                    "expected": {"relation": "right_gt_left"},
                    "actual": {"relation": "right_lt_left"},
                }
            ],
            artifact=None,
            node_report={"passed": False},
        )

    monkeypatch.setattr(
        "server.pipeline.verify_candidate",
        suspect_fixture_verifier,
    )
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: pytest.fail("browser gate must not run"),
        cache=cache,
    )

    record = manager.start("offline incompatible fixture refresh", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "answer_only"
    assert backend.understand_calls == 2
    assert backend.heal_calls == 0
    assert verification_calls == 2
    assert cache.writes == []


@pytest.mark.asyncio
async def test_public_hybrid_rejects_direct_canvas_without_causal_contract(
    monkeypatch,
):
    from server.jobs import JobManager

    backend = _MarkerlessDirectHybridBackend()
    gates = _ProductionGateProbe(browser_failures={"trusted_scene_plan"})
    cache = _RecordingCache()
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
        cache=cache,
    )

    record = manager.start("offline markerless direct candidate", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "answer_only"
    assert record.answer is not None
    assert record.artifact is None
    assert cache.writes == []
    assert gates.deterministic_calls == ["trusted_scene_plan"]
    assert gates.browser_calls == ["trusted_scene_plan"]
    assert backend.heal_calls == 1
    assert backend.heal_requests[0]["attempt"] == 1
    assert backend.heal_requests[0]["failures"][0]["gate"] == "causal_response"


@pytest.mark.asyncio
async def test_public_hybrid_accepts_direct_causal_proof_without_fragment_representation(
    monkeypatch,
):
    from server.jobs import JobManager

    backend = _HybridBackend()
    gates = _ProductionGateProbe(
        browser_failures={"trusted_scene_plan"},
        missing_representation={"direct_canvas"},
        deterministic_check_counts={"direct_canvas": 30},
    )
    cache = _RecordingCache()
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
        cache=cache,
    )

    record = manager.start("offline representation evidence failure", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "complete"
    assert record.artifact is not None
    assert cache.writes
    assert sorted(gates.deterministic_calls[:2]) == [
        "direct_canvas",
        "trusted_scene_plan",
    ]
    assert gates.browser_calls == [
        "trusted_scene_plan",
        "direct_canvas",
    ]
    assert backend.heal_calls == 0
    assert len(cache.writes) == 1


@pytest.mark.asyncio
async def test_public_hybrid_rejects_trusted_scene_without_representation_evidence(
    monkeypatch,
):
    from server.jobs import JobManager

    backend = _HybridBackend()
    gates = _ProductionGateProbe(
        browser_failures={"direct_canvas"},
        missing_representation={"trusted_scene_plan"},
        deterministic_check_counts={"trusted_scene_plan": 30},
    )
    cache = _RecordingCache()
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
        cache=cache,
    )

    record = manager.start("offline trusted representation failure", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "answer_only"
    assert record.artifact is None
    assert cache.writes == []
    assert "trusted_scene_plan" not in gates.browser_calls
    assert backend.heal_calls == 1
    assert backend.heal_requests[0]["failures"] == [
        {
            "gate": "representation_consistency",
            "code": "representation_contract_missing",
            "expected": {"temporal_causal_matrix_passed": True},
            "actual": {"temporal_causal_matrix_passed": None},
        }
    ]


@pytest.mark.asyncio
async def test_public_hybrid_receipts_identify_fixed_role_models_and_efforts(
    monkeypatch,
):
    from server.jobs import JobManager

    backend = _HybridBackend()
    gates = _ProductionGateProbe(browser_failures=set())
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
    )

    record = manager.start("offline hybrid receipts", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert backend.calls == [
        ("physics", "gpt-5.6-luna", "medium", True),
        ("trusted_scene_plan", "gpt-5.6-terra", "medium", True),
        ("direct_canvas", "gpt-5.6-terra", "medium", True),
    ]
    assert sorted(
        (
            execution.get("fragment_role"),
            execution["model"],
            execution["outcome"],
        )
        for execution in record.stage_executions
        if execution["stage"] == "generate"
    ) == [
        ("direct_canvas", "gpt-5.6-terra", "completed"),
        ("physics", "gpt-5.6-luna", "completed"),
        ("trusted_scene_plan", "gpt-5.6-terra", "completed"),
    ]
    assert sorted(
        (receipt.model, receipt.outcome)
        for receipt in record.runtime_receipts
        if receipt.stage == "generate"
    ) == [
        ("gpt-5.6-luna", "completed"),
        ("gpt-5.6-terra", "completed"),
        ("gpt-5.6-terra", "completed"),
    ]


@pytest.mark.asyncio
async def test_public_hybrid_all_candidates_failing_preserves_answer_and_never_caches(
    monkeypatch,
):
    from server.jobs import JobManager

    backend = _HybridBackend()
    gates = _ProductionGateProbe(
        browser_failures={"trusted_scene_plan", "direct_canvas"}
    )
    cache = _RecordingCache()
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
        cache=cache,
    )

    record = manager.start("offline hybrid all fail", "ar")
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "answer_only"
    assert record.answer is not None
    assert record.simulation is None
    assert record.artifact is None
    assert manager.artifacts == {}
    assert cache.writes == []
    assert backend.heal_calls == backend.public_heal_attempt_limit == 1
    assert backend.heal_requests[0]["attempt"] == 1
    assert backend.heal_requests[0]["failures"] == [
        {
            "gate": "causal_response",
            "code": "causal_evidence_invalid",
            "expected": {"causal_response": True},
            "actual": {"causal_response": False},
        }
    ]
    assert sorted(gates.deterministic_calls[:2]) == [
        "direct_canvas",
        "trusted_scene_plan",
    ]
    assert sorted(gates.browser_calls[:2]) == [
        "direct_canvas",
        "trusted_scene_plan",
    ]
    assert len(gates.deterministic_calls) == 3
    assert len(gates.browser_calls) == 3
    event_types = [event.type for event in record.events]
    assert event_types[0] == "answer"
    assert "result" not in event_types
    assert event_types[-1] == "fallback"


@pytest.mark.asyncio
async def test_public_hybrid_cancellation_awaits_both_visual_children(monkeypatch):
    from server.jobs import JobManager

    backend = _HybridBackend(block_stages=True)
    gates = _ProductionGateProbe(browser_failures=set())
    cache = _RecordingCache()
    monkeypatch.setattr("server.pipeline.verify_candidate", gates.deterministic)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=gates.browser,
        cache=cache,
    )

    record = manager.start("offline hybrid cancellation", "ar")
    await asyncio.wait_for(backend.physics_started.wait(), timeout=1)
    backend.release_physics.set()
    await asyncio.wait_for(
        asyncio.gather(
            *(event.wait() for event in backend.visuals_started.values())
        ),
        timeout=1,
    )

    await manager.cancel(record)

    assert record.status == "cancelled"
    assert backend.active_visuals == 0
    assert record.answer is not None
    assert record.artifact is None
    assert record.simulation is None
    assert cache.writes == []
    assert not any(event.type == "result" for event in record.events)
