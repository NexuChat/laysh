import asyncio
import json

import pytest

from tests.conftest import wait_for_terminal


def ask(client, question: str, locale: str = "ar") -> str:
    response = client.post("/api/ask", json={"question": question, "locale": locale})
    assert response.status_code == 202
    body = response.json()
    assert body["contract_version"] == "1.0"
    return body["job_id"]


def test_success_pipeline_answers_first_and_returns_playable_artifact(client, backend):
    job_id = ask(client, "success")
    result = wait_for_terminal(client, job_id)

    assert result["status"] == "complete"
    assert result["answer"]["tldr"]
    assert result["simulation"]["tier"] == "B"
    assert result["simulation"]["check_count"] >= 2
    assert result["simulation"]["heal_count"] == 0
    assert result["simulation"]["effective_model"] == "mock/offline"
    assert backend.understand_calls == backend.generate_calls == 1
    assert backend.qa_calls == 0

    events = client.app.state.jobs.get(job_id).events
    event_types = [event.type for event in events]
    assert event_types[0] == "answer"
    assert event_types.index("answer") < event_types.index("verification")
    assert event_types.index("answer") < event_types.index("result")

    download = client.get(result["simulation"]["artifact_url"])
    assert download.status_code == 200
    assert "connect-src 'none'" in download.text
    assert "https://" not in download.text


def test_non_simulatable_is_successful_answer_only_without_generation(client, backend):
    job_id = ask(client, "not simulatable", "en")
    result = wait_for_terminal(client, job_id)

    assert result["status"] == "answer_only"
    assert result["answer"]["tldr"]
    assert result["simulation"] is None
    assert result["fallback"]["reason_code"] == "not_simulatable"
    assert len(result["fallback"]["suggestions"]) == 3
    assert backend.generate_calls == 0


def test_malformed_simulation_slice_preserves_a_safe_answer_without_generation():
    from copy import deepcopy

    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.codex_backend import MockCodexBackend

    class MalformedSimulationSliceBackend(MockCodexBackend):
        async def understand(self, *args, **kwargs):
            understanding = deepcopy(await super().understand(*args, **kwargs))
            understanding["module_spec"] = {
                "outputs": ["lit_fraction"],
                "actor": "not-a-closed-actor",
                "action": "orbits",
            }
            return understanding

    backend = MalformedSimulationSliceBackend()
    with TestClient(create_app(backend=backend, job_timeout_seconds=2)) as test_client:
        job_id = ask(test_client, "success")
        result = wait_for_terminal(test_client, job_id)
        record = test_client.app.state.jobs.get(job_id)

    assert result["status"] == "answer_only"
    assert result["answer"]["tldr"]
    assert result["simulation"] is None
    assert result["fallback"]["reason_code"] == "generation_failed"
    assert backend.generate_calls == 0
    assert record.artifact is None
    assert record.question is None


def test_malformed_unsafe_slice_never_salvages_an_answer():
    from copy import deepcopy

    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.codex_backend import MockCodexBackend

    class MalformedUnsafeSliceBackend(MockCodexBackend):
        async def understand(self, *args, **kwargs):
            understanding = deepcopy(await super().understand(*args, **kwargs))
            understanding["safe"] = False
            understanding["module_spec"] = {
                "outputs": ["lit_fraction"],
                "actor": "not-a-closed-actor",
                "action": "orbits",
            }
            return understanding

    with TestClient(
        create_app(backend=MalformedUnsafeSliceBackend(), job_timeout_seconds=2)
    ) as test_client:
        job_id = ask(test_client, "success")
        result = wait_for_terminal(test_client, job_id)

    assert result["status"] == "failed"
    assert result["answer"] is None
    assert result["simulation"] is None


def test_partial_module_slice_falls_back_without_a_verified_label_or_cache_write():
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.codex_backend import MockCodexBackend

    class PartialModuleBackend(MockCodexBackend):
        async def generate(self, *args, **kwargs):
            self.generate_calls += 1
            return {"module_js": "window.LayshSimulation = {};"}

    backend = PartialModuleBackend()
    with TestClient(create_app(backend=backend, job_timeout_seconds=2)) as test_client:
        job_id = ask(test_client, "success")
        result = wait_for_terminal(test_client, job_id)
        record = test_client.app.state.jobs.get(job_id)

    assert result["status"] == "answer_only"
    assert result["answer"]["tldr"]
    assert result["simulation"] is None
    assert result["fallback"]["reason_code"] == "generation_failed"
    assert backend.generate_calls == 1
    assert record.artifact is None
    assert test_client.app.state.jobs.artifacts == {}


@pytest.mark.asyncio
async def test_contradictory_simulation_contract_never_enters_verified_cache():
    from copy import deepcopy

    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    class ContradictoryFixtureBackend(MockCodexBackend):
        async def understand(self, *args, **kwargs):
            understanding = deepcopy(await super().understand(*args, **kwargs))
            understanding["checks"][0]["expected"] = 0.99
            return understanding

    class RejectingCache:
        def lookup(self, **kwargs):
            del kwargs
            return None

        def write_verified(self, **kwargs):
            raise AssertionError("contradictory simulation must never be cached")

    manager = JobManager(
        ContradictoryFixtureBackend(),
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=RejectingCache(),
    )
    record = manager.start("success", "ar")
    await record.task

    assert record.status == "answer_only"
    assert record.answer is not None and record.answer.tldr
    assert record.simulation is None
    assert record.artifact is None
    assert record.fallback is not None
    assert record.fallback.reason_code == "verification_exhausted"
    assert manager.artifacts == {}


def test_generate_failure_after_answer_preserves_the_safe_answer_as_answer_only():
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.codex_backend import MockCodexBackend
    from server.codex_runtime import CodexRuntimeError

    class FailingGenerateBackend(MockCodexBackend):
        async def generate(self, *args, **kwargs):
            self.generate_calls += 1
            raise CodexRuntimeError(
                "nonzero_exit",
                safe_detail={"kind": "runtime_error", "model": "gpt-5.6-sol"},
            )

    with TestClient(
        create_app(backend=FailingGenerateBackend(), job_timeout_seconds=2)
    ) as test_client:
        job_id = ask(test_client, "success")
        result = wait_for_terminal(test_client, job_id)
        record = test_client.app.state.jobs.get(job_id)

    assert result["status"] == "answer_only"
    assert result["answer"]["tldr"]
    assert result["simulation"] is None
    assert result["fallback"]["reason_code"] == "generation_failed"
    assert [event.type for event in record.events][:2] == ["answer", "stage"]
    assert record.events[-1].type == "fallback"
    assert [
        (receipt.stage, receipt.model, receipt.outcome, receipt.failure_code)
        for receipt in record.runtime_receipts
    ] == [("generate", "gpt-5.6-sol", "failed", "nonzero_exit")]
    assert record.question is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_stage", "expected_reason"),
    [
        ("generate", "generation_failed"),
        ("heal", "generation_failed"),
        ("qa", "simulation_runtime_error"),
        ("cache_lookup", "generation_failed"),
        ("browser", "simulation_runtime_error"),
        ("timeout", "timed_out"),
    ],
)
async def test_every_downstream_failure_after_answer_falls_back_without_artifact(
    failure_stage,
    expected_reason,
):
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.codex_runtime import CodexRuntimeError
    from server.jobs import JobManager

    class DownstreamFailureBackend(MockCodexBackend):
        async def generate(self, *args, **kwargs):
            if failure_stage == "timeout":
                await asyncio.sleep(60)
            if failure_stage == "generate":
                raise CodexRuntimeError(
                    "nonzero_exit",
                    safe_detail={"kind": "runtime_error", "model": "gpt-5.6-sol"},
                )
            return await super().generate(*args, **kwargs)

        async def heal(self, *args, **kwargs):
            if failure_stage == "heal":
                raise CodexRuntimeError(
                    "nonzero_exit",
                    safe_detail={"kind": "runtime_error", "model": "gpt-5.6-sol"},
                )
            return await super().heal(*args, **kwargs)

        async def qa(self, *args, **kwargs):
            if failure_stage == "qa":
                raise CodexRuntimeError(
                    "nonzero_exit",
                    safe_detail={"kind": "runtime_error", "model": "gpt-5.6-sol"},
                )
            return await super().qa(*args, **kwargs)

    class FailingCache:
        def lookup(self, **kwargs):
            del kwargs
            raise OSError("cache unavailable")

        def write_verified(self, **kwargs):
            raise AssertionError("a downstream failure must not write cache")

    def browser_verifier(_artifact):
        if failure_stage == "browser":
            raise RuntimeError("browser unavailable")
        return BrowserVerificationResult.passing()

    manager = JobManager(
        DownstreamFailureBackend(),
        public_job_timeout_seconds=0.02 if failure_stage == "timeout" else 2,
        browser_verifier=browser_verifier,
        cache=FailingCache() if failure_stage == "cache_lookup" else None,
    )
    question = "broken first draft" if failure_stage in {"heal", "qa"} else "success"
    record = manager.start(question, "ar")
    await record.task

    assert record.status == "answer_only"
    assert record.answer is not None and record.answer.tldr
    assert record.simulation is None
    assert record.artifact is None
    assert record.fallback is not None and record.fallback.reason_code == expected_reason
    assert manager.artifacts == {}
    assert [event.type for event in record.events][:2] == ["answer", "stage"]
    assert record.events[-1].type == "fallback"
    assert record.question is None


@pytest.mark.asyncio
async def test_assembly_failure_after_answer_exhausts_repairs_without_losing_the_answer(
    monkeypatch,
):
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    def fail_assembly(*_args, **_kwargs):
        raise ValueError("trusted shell unavailable")

    monkeypatch.setattr("server.assemble.assemble_artifact", fail_assembly)
    manager = JobManager(
        MockCodexBackend(),
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    record = manager.start("success", "ar")
    await record.task

    assert record.status == "answer_only"
    assert record.answer is not None and record.answer.tldr
    assert record.simulation is None
    assert record.artifact is None
    assert record.fallback is not None
    assert record.fallback.reason_code == "verification_exhausted"
    assert manager.artifacts == {}


@pytest.mark.asyncio
async def test_cache_write_failure_keeps_a_verified_playable_result_after_answer():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    class WriteFailingCache:
        def lookup(self, **kwargs):
            del kwargs
            return None

        def write_verified(self, **kwargs):
            del kwargs
            raise OSError("cache unavailable")

    manager = JobManager(
        MockCodexBackend(),
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=WriteFailingCache(),
    )
    record = manager.start("success", "ar")
    await record.task

    assert record.status == "complete"
    assert record.answer is not None and record.answer.tldr
    assert record.simulation is not None
    assert record.artifact is not None
    assert record.fallback is None
    assert record.simulation.sim_id in manager.artifacts


@pytest.mark.asyncio
async def test_fresh_pipeline_without_an_incumbent_serves_and_caches_its_candidate(tmp_path):
    from server.browser_verify import BrowserVerificationResult
    from server.cache import VERIFIED_CACHE_CONTRACT_VERSION, VerifiedCache
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=tmp_path / "golden",
        secret=b"fresh-without-incumbent-secret",
        contract_version=VERIFIED_CACHE_CONTRACT_VERSION,
    )
    manager = JobManager(
        MockCodexBackend(),
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=cache,
    )

    record = manager.start("success", "ar", fresh_generation=True)
    await record.task
    cached = cache.lookup(
        question="success",
        locale="ar",
        domain="astronomy",
        canonical_intent="moon_phase_lit_fraction",
    )

    assert record.status == "complete"
    assert record.fresh_outcome is None
    assert record.artifact is not None
    assert cached is not None and cached.artifact == record.artifact
    assert set(cached.receipt.passed_gates) == {
        "closed_schema",
        "fixtures",
        "node_runtime",
        "restricted_source",
    }
    assert "success" not in (tmp_path / "live" / f"{cached.cache_id}.json").read_text(
        encoding="utf-8"
    )


def test_unsafe_fixture_is_zero_echo_and_spends_no_generation(client, backend):
    canary = "unsafe PRIVATE-CANARY-9182"
    job_id = ask(client, canary)
    result = wait_for_terminal(client, job_id)
    record = client.app.state.jobs.get(job_id)
    public_surface = json.dumps(
        {
            "result": result,
            "events": [event.model_dump(mode="json") for event in record.events],
        },
        ensure_ascii=False,
    )

    assert result["status"] == "rejected"
    assert canary not in public_surface
    assert record.question is None
    assert backend.generate_calls == 0


def test_broken_first_draft_is_healed_once_and_reverified(client, backend):
    job_id = ask(client, "broken first draft")
    result = wait_for_terminal(client, job_id)
    stages = [
        event.payload.stage
        for event in client.app.state.jobs.get(job_id).events
        if event.type == "stage"
    ]

    assert result["status"] == "complete"
    assert result["simulation"]["heal_count"] == 1
    assert stages.count("verifying") == 2
    assert "healing" in stages
    assert backend.heal_calls == 1
    assert backend.qa_calls == 1
    assert backend.last_heal_failures
    assert {failure["gate"] for failure in backend.last_heal_failures[0]} >= {
        "interface",
        "security",
    }

    failed_verification = next(
        event for event in client.app.state.jobs.get(job_id).events
        if event.type == "verification" and event.payload.passed is False
    )
    public_payload = failed_verification.payload.model_dump(mode="json")
    assert set(public_payload) == {"passed", "check_count", "heal_count", "evidence"}
    assert set(public_payload["evidence"]) >= {"interface", "security"}
    assert "expected" not in str(public_payload)
    assert "actual" not in str(public_payload)


@pytest.mark.asyncio
async def test_curated_builder_evidence_retains_the_exact_report_sent_to_heal(backend):
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager

    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        evidence_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    record = manager.start_evidence("broken first draft", "ar", "moon_phases_ar")
    await record.task

    diagnostic = next(
        item for item in record.builder_diagnostics
        if item.get("type") == "verification_failure"
    )
    assert diagnostic["failures"] == backend.last_heal_failures[0]
    assert any(
        failure["gate"] == "interface"
        and failure["expected"]["permitted_abi"]
        and failure["actual"]["missing_keys"]
        for failure in diagnostic["failures"]
    )


@pytest.mark.asyncio
async def test_qa_timeout_retries_once_with_same_slim_input_then_completes():
    from copy import deepcopy

    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.codex_runtime import CodexRuntimeError, StageExecution
    from server.jobs import JobManager

    class TransientQaBackend(MockCodexBackend):
        def __init__(self):
            super().__init__()
            self.qa_inputs = []

        async def qa(self, module_output, understanding, gate_outcome, **kwargs):
            self.qa_calls += 1
            self.qa_inputs.append(
                (deepcopy(module_output), deepcopy(understanding), deepcopy(gate_outcome))
            )
            if self.qa_calls == 1:
                raise CodexRuntimeError(
                    "stage_timeout",
                    safe_detail={"kind": "runtime_error", "model": "gpt-5.6-sol"},
                )
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
                elapsed_ms=20,
            )

    backend = TransientQaBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        evidence_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    record = manager.start_evidence("broken first draft", "ar", "moon_phases_ar")
    await record.task

    assert record.status == "complete"
    assert backend.qa_calls == 2
    assert backend.qa_inputs[0] == backend.qa_inputs[1]
    assert backend.qa_inputs[0][2]["passed"] is True
    assert backend.qa_inputs[0][2]["check_count"] > 0
    assert backend.qa_inputs[0][2]["gate_names"]
    assert any(item.get("type") == "qa_timeout" for item in record.builder_diagnostics)
    assert [
        (receipt.stage, receipt.attempt, receipt.model, receipt.outcome, receipt.failure_code)
        for receipt in record.runtime_receipts
    ] == [
        ("qa", 1, "gpt-5.6-sol", "failed", "stage_timeout"),
        ("qa", 2, "gpt-5.6-sol", "completed", None),
    ]


@pytest.mark.asyncio
async def test_double_qa_timeout_withholds_curated_artifact_as_inconclusive():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.codex_runtime import CodexRuntimeError
    from server.jobs import JobManager

    class TimedOutQaBackend(MockCodexBackend):
        async def qa(self, *args, **kwargs):
            self.qa_calls += 1
            raise CodexRuntimeError("stage_timeout")

    backend = TimedOutQaBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        evidence_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    record = manager.start_evidence("broken first draft", "ar", "moon_phases_ar")
    await record.task

    assert record.status == "qa_inconclusive"
    assert backend.qa_calls == 2
    assert record.artifact is None
    assert record.simulation is None
    assert manager.artifacts == {}
    diagnostics = [
        item for item in record.builder_diagnostics if item.get("type") == "qa_timeout"
    ]
    assert [item["attempt"] for item in diagnostics] == [1, 2]
    assert all(item["structured_output_observed"] is False for item in diagnostics)
    assert all(item["gate_outcome"]["passed"] is True for item in diagnostics)


@pytest.mark.asyncio
async def test_double_qa_timeout_public_job_falls_back_to_answer_only():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.codex_runtime import CodexRuntimeError
    from server.jobs import JobManager

    class TimedOutQaBackend(MockCodexBackend):
        async def qa(self, *args, **kwargs):
            self.qa_calls += 1
            raise CodexRuntimeError("stage_timeout")

    backend = TimedOutQaBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    record = manager.start("broken first draft", "ar")
    await record.task

    assert record.status == "answer_only"
    assert backend.qa_calls == 2
    assert record.fallback is not None
    assert record.fallback.reason_code == "qa_inconclusive"
    assert record.artifact is None
    assert record.builder_diagnostics == []


@pytest.mark.asyncio
async def test_curated_qa_rejection_retains_candidate_and_actionable_visual_review():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    class RejectingVisualQaBackend(MockCodexBackend):
        async def qa(self, *args, **kwargs):
            self.qa_calls += 1
            return {
                "approved": False,
                "issues": ["المشهد مسطح ولا يحتوي حركة هادئة."],
                "replacement_module_js": None,
                "visual_richness": {
                    "scene_depth": False,
                    "physical_light": True,
                    "idle_motion": False,
                    "reactive_feedback": True,
                    "readable_overlays": True,
                },
            }

    backend = RejectingVisualQaBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        evidence_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    record = manager.start_evidence(
        "success",
        "ar",
        "moon_phases_ar",
        promote_golden=True,
    )
    await record.task

    assert record.status == "answer_only"
    assert record.artifact is not None
    assert record.builder_outputs["qa"]["visual_richness"]["scene_depth"] is False
    diagnostic = next(
        item for item in record.builder_diagnostics if item["type"] == "qa_rejected"
    )
    assert diagnostic["issues"] == ["المشهد مسطح ولا يحتوي حركة هادئة."]
    assert diagnostic["visual_richness"]["idle_motion"] is False


@pytest.mark.asyncio
async def test_public_qa_rejection_uses_remaining_heal_with_private_actionable_report():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    rejected_issue = "المشهد مسطح ولا يوضح أثر تغيّر المدخل بصريًا."
    rejected_richness = {
        "scene_depth": False,
        "physical_light": True,
        "idle_motion": False,
        "reactive_feedback": False,
        "readable_overlays": True,
    }
    approved_richness = {name: True for name in rejected_richness}

    class QaRehealBackend(MockCodexBackend):
        async def qa(self, *args, **kwargs):
            del args, kwargs
            self.qa_calls += 1
            if self.qa_calls == 1:
                return {
                    "approved": False,
                    "issues": [rejected_issue],
                    "replacement_module_js": None,
                    "visual_richness": rejected_richness,
                }
            return {
                "approved": True,
                "issues": [],
                "replacement_module_js": None,
                "visual_richness": approved_richness,
            }

    class CountingBrowserGate:
        def __init__(self):
            self.calls = 0

        def __call__(self, _artifact):
            self.calls += 1
            return BrowserVerificationResult.passing()

    backend = QaRehealBackend()
    browser_gate = CountingBrowserGate()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=browser_gate,
    )

    record = manager.start("broken first draft", "ar")
    await record.task

    assert backend.heal_calls == 2
    assert backend.qa_calls == 2
    assert browser_gate.calls == 2
    assert record.status == "complete"
    assert record.simulation is not None
    assert record.simulation.heal_count == 2

    initial_failures, qa_failures = backend.last_heal_failures
    assert {failure["gate"] for failure in initial_failures} >= {
        "interface",
        "security",
    }
    assert len(qa_failures) == 1
    qa_failure = qa_failures[0]
    assert qa_failure["gate"] == "qa_review"
    assert qa_failure["expected"]["approved"] is True
    assert qa_failure["expected"]["visual_richness"] == approved_richness
    assert qa_failure["actual"]["approved"] is False
    assert qa_failure["actual"]["issues"] == [rejected_issue]
    assert qa_failure["actual"]["visual_richness"] == rejected_richness

    public_qa_failure = next(
        event
        for event in record.events
        if event.type == "verification"
        and event.payload.passed is False
        and "qa_review" in event.payload.evidence
    )
    public_payload = public_qa_failure.payload.model_dump(mode="json")
    assert public_payload["evidence"] == ["qa_review"]
    assert set(public_payload) == {"passed", "check_count", "heal_count", "evidence"}
    public_surface = json.dumps(
        [event.model_dump(mode="json") for event in record.events],
        ensure_ascii=False,
    )
    assert rejected_issue not in public_surface
    assert "scene_depth" not in public_surface
    assert '"issues"' not in public_surface
    assert '"expected"' not in public_surface
    assert '"actual"' not in public_surface
    assert record.builder_diagnostics == []


@pytest.mark.asyncio
async def test_curated_suspect_fixture_refreshes_understand_once_without_heal():
    from copy import deepcopy

    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager
    from server.schemas import validate_understanding

    class RefreshingFixtureBackend(MockCodexBackend):
        async def understand(self, *args, **kwargs):
            understanding = await super().understand(*args, **kwargs)
            if self.understand_calls == 1:
                understanding = deepcopy(understanding)
                understanding["checks"].append(
                    {
                        "id": "contradictory_relation",
                        "kind": "relation",
                        "left_inputs": [{"name": "angle_deg", "value": 90}],
                        "right_inputs": [{"name": "angle_deg", "value": 45}],
                        "output": "lit_fraction",
                        "relation": "right_gt_left",
                        "minimum_ratio": 1.5,
                    }
                )
                return validate_understanding(understanding)
            return understanding

    backend = RefreshingFixtureBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        evidence_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    record = manager.start_evidence("success", "ar", "moon_phases_ar")
    await record.task

    assert record.status == "complete"
    assert backend.understand_calls == 2
    assert backend.generate_calls == 1
    assert backend.heal_calls == 0
    assert any(item.get("type") == "fixture_refresh" for item in record.builder_diagnostics)


@pytest.mark.asyncio
async def test_curated_code_style_formula_refreshes_understand_before_answer_or_generate():
    from copy import deepcopy

    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    class RefreshingFormulaBackend(MockCodexBackend):
        async def understand(self, *args, **kwargs):
            understanding = await super().understand(*args, **kwargs)
            if self.understand_calls == 1:
                understanding = deepcopy(understanding)
                understanding["key_formula"] = "illuminated_fraction = 1 - lunar_day"
            return understanding

    backend = RefreshingFormulaBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        evidence_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    record = manager.start_evidence("success", "ar", "moon_phases_ar")
    await record.task

    assert record.status == "complete"
    assert backend.understand_calls == 2
    assert backend.generate_calls == 1
    assert backend.heal_calls == 0
    assert record.answer is not None
    assert record.answer.key_formula == "f = (1 − cos θ) / 2"
    assert any(
        item.get("type") == "understanding_refresh"
        and item["trigger_failures"][0]["actual"]["code_identifiers"]
        == ["illuminated_fraction", "lunar_day"]
        for item in record.builder_diagnostics
    )


@pytest.mark.asyncio
async def test_public_code_style_formula_is_not_exposed_and_does_not_enter_heal_loop():
    from copy import deepcopy

    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    class CodeFormulaBackend(MockCodexBackend):
        async def understand(self, *args, **kwargs):
            understanding = deepcopy(await super().understand(*args, **kwargs))
            understanding["key_formula"] = "illuminated_fraction = 1 - lunar_day"
            return understanding

    backend = CodeFormulaBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    record = manager.start("success", "ar")
    await record.task

    assert record.status == "complete"
    assert record.answer is not None and record.answer.key_formula is None
    assert backend.understand_calls == 1
    assert backend.heal_calls == 0
    assert "illuminated_fraction" not in str(record.public_result())


def test_exhausted_heal_preserves_answer_and_never_exposes_artifact(client, backend):
    job_id = ask(client, "exhausted heal")
    result = wait_for_terminal(client, job_id)

    assert result["status"] == "answer_only"
    assert result["answer"]["tldr"]
    assert result["simulation"] is None
    assert result["fallback"]["reason_code"] == "verification_exhausted"
    assert backend.heal_calls == 2
    assert backend.qa_calls == 0


def test_timeout_reaches_truthful_terminal_state_and_discards_question(backend):
    from fastapi.testclient import TestClient

    from server.app import create_app

    with TestClient(create_app(backend=backend, job_timeout_seconds=0.03)) as test_client:
        job_id = ask(test_client, "timeout")
        result = wait_for_terminal(test_client, job_id)
        assert result["status"] == "timed_out"
        assert test_client.app.state.jobs.get(job_id).question is None


def test_public_runtime_receipts_preserve_every_stage_without_mislabeling_generation():
    """A later heal or QA model must never masquerade as the generation model."""
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.codex_runtime import StageExecution

    class ReceiptBackend(MockCodexBackend):
        async def understand(self, *args, **kwargs):
            return StageExecution(
                data=await super().understand(*args, **kwargs),
                thread_id="private-understand-thread",
                model="gpt-5.6-luna",
                elapsed_ms=11,
            )

        async def generate(self, *args, **kwargs):
            return StageExecution(
                data=await super().generate(*args, **kwargs),
                thread_id="private-generate-thread",
                model="gpt-5.6-terra",
                elapsed_ms=22,
            )

        async def heal(self, *args, **kwargs):
            return StageExecution(
                data=await super().heal(*args, **kwargs),
                thread_id="private-heal-thread",
                model="gpt-5.6-sol",
                elapsed_ms=33,
            )

        async def qa(self, *args, **kwargs):
            return StageExecution(
                data=await super().qa(*args, **kwargs),
                thread_id="private-qa-thread",
                model="gpt-5.6-luna",
                elapsed_ms=44,
            )

    with TestClient(
        create_app(
            backend=ReceiptBackend(),
            job_timeout_seconds=2,
            browser_verifier=lambda _: BrowserVerificationResult.passing(),
        )
    ) as test_client:
        job_id = ask(test_client, "broken first draft")
        result = wait_for_terminal(test_client, job_id)

    assert result["status"] == "complete"
    assert result["simulation"]["effective_model"] == "gpt-5.6-terra"
    assert [
        (receipt["stage"], receipt["attempt"], receipt["model"], receipt["outcome"])
        for receipt in result["runtime_receipts"]
    ] == [
        ("understand", 1, "gpt-5.6-luna", "completed"),
        ("generate", 1, "gpt-5.6-terra", "completed"),
        ("heal", 1, "gpt-5.6-sol", "completed"),
        ("qa", 1, "gpt-5.6-luna", "completed"),
    ]
    public_surface = json.dumps(result, ensure_ascii=False)
    assert "private-" not in public_surface
    assert "broken first draft" not in public_surface


def test_public_runtime_receipts_retain_a_sanitized_understand_fallback_attempt():
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.codex_runtime import StageExecution

    class FallbackReceiptBackend(MockCodexBackend):
        async def understand(self, *args, **kwargs):
            return StageExecution(
                data=await super().understand(*args, **kwargs),
                thread_id="private-fallback-thread",
                model="gpt-5.6-sol",
                elapsed_ms=27,
                attempted_models=("gpt-5.6-luna", "gpt-5.6-sol"),
                prior_failure_codes=("nonzero_exit",),
            )

        async def generate(self, *args, **kwargs):
            return StageExecution(
                data=await super().generate(*args, **kwargs),
                thread_id="private-generate-thread",
                model="gpt-5.6-sol",
                elapsed_ms=31,
            )

    with TestClient(
        create_app(
            backend=FallbackReceiptBackend(),
            job_timeout_seconds=2,
            browser_verifier=lambda _: BrowserVerificationResult.passing(),
        )
    ) as test_client:
        job_id = ask(test_client, "success")
        result = wait_for_terminal(test_client, job_id)

    assert [
        (receipt["stage"], receipt["attempt"], receipt["model"], receipt["outcome"])
        for receipt in result["runtime_receipts"]
    ] == [
        ("understand", 1, "gpt-5.6-luna", "failed"),
        ("understand", 2, "gpt-5.6-sol", "completed"),
        ("generate", 1, "gpt-5.6-sol", "completed"),
    ]
    assert result["runtime_receipts"][0]["failure_code"] == "nonzero_exit"
    assert "thread_id" not in str(result["runtime_receipts"])


@pytest.mark.asyncio
async def test_pipeline_cancellation_propagates():
    from server.pipeline import PipelineCancelled, cancellable_sleep

    task = asyncio.create_task(cancellable_sleep(5))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(PipelineCancelled):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failures", "expected_regeneration_calls", "expected_status"),
    [
        pytest.param(
            [
                {
                    "gate": "fixture_integrity",
                    "code": "numeric_fixture_mismatch",
                    "expected": {"fixture_match": True},
                    "actual": {"fixture_match": False},
                },
                {
                    "gate": "scene_geometry",
                    "code": "scientific_actor_clipped",
                    "expected": {"within_viewport": True},
                    "actual": {"within_viewport": False},
                },
            ],
            [
                ("physics", "physics_fixture_mismatch", 1),
                ("visual", "visual_geometry_mismatch", 1),
            ],
            "complete",
            id="physics_and_visual",
        ),
        pytest.param(
            [
                {
                    "gate": "causal_response",
                    "code": "causal_relation_mismatch",
                    "expected": {"monotonic_actor_response": True},
                    "actual": {"monotonic_actor_response": False},
                },
                {
                    "gate": "temporal_causal_matrix",
                    "code": "causal_direction_mismatch",
                    "expected": {"matching_direction": True},
                    "actual": {"matching_direction": False},
                },
            ],
            [("visual", "visual_causality_mismatch", 1)],
            "complete",
            id="causal_and_temporal_visual",
        ),
        pytest.param(
            [
                {
                    "gate": "representation_consistency",
                    "code": "archetype_render_mismatch",
                    "expected": {
                        "declared_archetype_rendered": True,
                        "minimum_visible_scientific_actors": 1,
                    },
                    "actual": {
                        "declared": "single_body",
                        "scientific_actor_count": 1,
                        "visible_actor_count": 0,
                        "matching_primitive_count": 0,
                    },
                }
            ],
            [("visual", "visual_geometry_mismatch", 1)],
            "complete",
            id="representation_consistency_visual",
        ),
        pytest.param(
            [
                {
                    "gate": "unknown_gate",
                    "code": "unknown_failure",
                    "expected": {"known": True},
                    "actual": {"known": False},
                }
            ],
            [],
            "answer_only",
            id="unknown",
        ),
        pytest.param(
            [
                {
                    "gate": "invariant",
                    "code": "numeric_fixture_mismatch",
                    "expected": {"fixture_match": True},
                    "actual": {"fixture_match": False},
                },
                {
                    "gate": "unknown_gate",
                    "code": "unknown_failure",
                    "expected": {"known": True},
                    "actual": {"known": False},
                },
            ],
            [],
            "answer_only",
            id="mapped_and_unknown",
        ),
    ],
)
async def test_fragment_preflight_repairs_all_mapped_roles_or_falls_back_for_unknown(
    monkeypatch: pytest.MonkeyPatch,
    failures: list[dict[str, object]],
    expected_regeneration_calls: list[tuple[str, str, int]],
    expected_status: str,
) -> None:
    """Known preflight failures repair every role; unknowns remain terminal."""

    from copy import deepcopy

    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend, RuntimeContext
    from server.codex_runtime import StageExecution
    from server.jobs import JobManager
    from server.verify import VerificationResult
    from tests.golden_cases import VALID_UNDERSTANDING
    from tests.test_parallel_fragment_generation import PHYSICS_FRAGMENT, VISUAL_FRAGMENT

    class FragmentBackend(MockCodexBackend):
        def __init__(self) -> None:
            super().__init__()
            self.regeneration_calls: list[tuple[str, str, int]] = []

        async def understand(self, _question, _locale, *, runtime_context=None):
            assert runtime_context == RuntimeContext(public=True)
            self.understand_calls += 1
            return deepcopy(VALID_UNDERSTANDING)

        async def generate_fragments(self, _understanding, *, runtime_context=None):
            assert runtime_context == RuntimeContext(public=True)
            return (
                StageExecution(
                    data=deepcopy(PHYSICS_FRAGMENT),
                    thread_id="private-physics",
                    model="gpt-5.6-sol",
                    elapsed_ms=1,
                ),
                StageExecution(
                    data=deepcopy(VISUAL_FRAGMENT),
                    thread_id="private-visual",
                    model="gpt-5.6-terra",
                    elapsed_ms=1,
                ),
            )

        async def regenerate_fragment(
            self,
            role,
            _understanding,
            failure_code,
            *,
            repair_attempt=1,
            runtime_context=None,
        ):
            assert runtime_context == RuntimeContext(public=True)
            self.regeneration_calls.append((role, failure_code, repair_attempt))
            fragment = PHYSICS_FRAGMENT if role == "physics" else VISUAL_FRAGMENT
            return StageExecution(
                data=deepcopy(fragment),
                thread_id="private-repair",
                model="gpt-5.6-sol" if role == "physics" else "gpt-5.6-terra",
                elapsed_ms=1,
            )

    verification_calls = 0

    def deterministic_verifier(_module_output, _understanding):
        nonlocal verification_calls
        verification_calls += 1
        if expected_status == "complete" and verification_calls > 1:
            return VerificationResult(
                passed=True,
                check_count=1,
                failures=[],
                artifact="<!doctype html><title>verified</title>",
                node_report={"passed": True},
            )
        return VerificationResult(
            passed=False,
            check_count=1,
            failures=deepcopy(failures),
            artifact=None,
            node_report={"passed": False},
        )

    monkeypatch.setattr("server.pipeline.verify_candidate", deterministic_verifier)
    backend = FragmentBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _artifact: BrowserVerificationResult.passing(),
    )
    record = manager.start("success", "ar")
    assert record.task is not None
    await record.task

    assert record.status == expected_status
    if expected_status == "answer_only":
        assert record.fallback is not None
        assert record.fallback.reason_code == "verification_exhausted"
    assert backend.regeneration_calls == expected_regeneration_calls
    assert backend.heal_calls == 0


@pytest.mark.asyncio
async def test_fragment_post_verification_repairs_mixed_roles_then_reverifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from copy import deepcopy

    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend, RuntimeContext
    from server.codex_runtime import StageExecution
    from server.jobs import JobManager
    from server.verify import VerificationResult
    from tests.golden_cases import VALID_UNDERSTANDING
    from tests.test_parallel_fragment_generation import PHYSICS_FRAGMENT, VISUAL_FRAGMENT

    class FragmentBackend(MockCodexBackend):
        def __init__(self) -> None:
            super().__init__()
            self.regeneration_calls: list[tuple[str, str, int]] = []

        async def understand(self, _question, _locale, *, runtime_context=None):
            assert runtime_context == RuntimeContext(public=True)
            return deepcopy(VALID_UNDERSTANDING)

        async def generate_fragments(self, _understanding, *, runtime_context=None):
            assert runtime_context == RuntimeContext(public=True)
            return (
                StageExecution(
                    deepcopy(PHYSICS_FRAGMENT), "private-physics", "gpt-5.6-sol", 1
                ),
                StageExecution(
                    deepcopy(VISUAL_FRAGMENT), "private-visual", "gpt-5.6-terra", 1
                ),
            )

        async def regenerate_fragment(
            self,
            role,
            _understanding,
            failure_code,
            *,
            repair_attempt=1,
            runtime_context=None,
        ):
            assert runtime_context == RuntimeContext(public=True)
            self.regeneration_calls.append((role, failure_code, repair_attempt))
            fragment = PHYSICS_FRAGMENT if role == "physics" else VISUAL_FRAGMENT
            return StageExecution(
                deepcopy(fragment),
                "private-repair",
                "gpt-5.6-sol" if role == "physics" else "gpt-5.6-terra",
                1,
            )

    verification_calls = 0

    def deterministic_verifier(_module_output, _understanding):
        nonlocal verification_calls
        verification_calls += 1
        if verification_calls == 2:
            return VerificationResult(
                passed=False,
                check_count=1,
                failures=[
                    {
                        "gate": "fixture_integrity",
                        "code": "numeric_fixture_mismatch",
                        "expected": {"fixture_match": True},
                        "actual": {"fixture_match": False},
                    },
                    {
                        "gate": "causal_response",
                        "code": "causal_relation_mismatch",
                        "expected": {"response": True},
                        "actual": {"response": False},
                    },
                ],
                artifact=None,
                node_report={"passed": False},
            )
        return VerificationResult(
            passed=True,
            check_count=1,
            failures=[],
            artifact="<!doctype html><title>verified</title>",
            node_report={"passed": True},
        )

    monkeypatch.setattr("server.pipeline.verify_candidate", deterministic_verifier)
    backend = FragmentBackend()
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
        ("physics", "physics_fixture_mismatch", 1),
        ("visual", "visual_causality_mismatch", 1),
    ]
    assert backend.heal_calls == 0
    assert verification_calls == 3
