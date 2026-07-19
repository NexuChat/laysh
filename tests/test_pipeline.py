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
    from server.codex_runtime import CodexRuntimeError
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
                raise CodexRuntimeError("stage_timeout")
            return {"approved": True, "issues": [], "replacement_module_js": None}

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


@pytest.mark.asyncio
async def test_pipeline_cancellation_propagates():
    from server.pipeline import PipelineCancelled, cancellable_sleep

    task = asyncio.create_task(cancellable_sleep(5))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(PipelineCancelled):
        await task
