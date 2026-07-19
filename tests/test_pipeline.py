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
    from server.jobs import JobManager

    manager = JobManager(backend, public_job_timeout_seconds=2, evidence_job_timeout_seconds=2)
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
