import asyncio
import json

import pytest

from tests.conftest import wait_for_terminal
from tests.test_pipeline import ask


def _sse_events(text: str) -> list[dict]:
    events = []
    current = {}
    for line in text.splitlines():
        if line.startswith("id: "):
            current["id"] = int(line[4:])
        elif line.startswith("event: "):
            current["type"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[6:])
        elif not line and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


def test_sse_replays_only_events_after_last_event_id(client):
    job_id = ask(client, "success")
    wait_for_terminal(client, job_id)

    all_response = client.get(f"/api/jobs/{job_id}/events")
    all_events = _sse_events(all_response.text)
    assert all_response.headers["content-type"].startswith("text/event-stream")
    assert len(all_events) >= 5

    last_seen = all_events[2]["id"]
    replay = client.get(
        f"/api/jobs/{job_id}/events",
        headers={"Last-Event-ID": str(last_seen)},
    )
    replayed = _sse_events(replay.text)
    assert replayed
    assert all(event["id"] > last_seen for event in replayed)
    assert [event["id"] for event in replayed] == sorted({event["id"] for event in replayed})


def test_cancel_affects_only_selected_job(client):
    slow_job = ask(client, "timeout")
    normal_job = ask(client, "success")

    response = client.post(f"/api/jobs/{slow_job}/cancel")
    assert response.status_code == 200
    assert wait_for_terminal(client, slow_job)["status"] == "cancelled"
    assert wait_for_terminal(client, normal_job)["status"] == "complete"


def test_job_transitions_are_monotonic_and_sequence_ids_are_contiguous(client):
    job_id = ask(client, "broken first draft")
    wait_for_terminal(client, job_id)
    record = client.app.state.jobs.get(job_id)

    assert [event.id for event in record.events] == list(range(1, len(record.events) + 1))
    assert record.state_history[0] == "queued"
    assert record.state_history[-1] == "complete"
    assert record.state_history.count("healing") == 1


def test_missing_job_returns_not_found(client):
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.post("/api/jobs/missing/cancel").status_code == 404


@pytest.mark.asyncio
async def test_evidence_job_has_build_time_budget_without_changing_public_deadline():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    class SlowMockCodexBackend(MockCodexBackend):
        async def understand(self, *args, **kwargs):
            await asyncio.sleep(0.01)
            return await super().understand(*args, **kwargs)

    manager = JobManager(
        SlowMockCodexBackend(),
        public_job_timeout_seconds=0.0001,
        evidence_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    public_record = manager.start("success", "ar")
    evidence_record = manager.start_evidence("success", "ar", "moon_phases_ar")

    await public_record.task
    await evidence_record.task

    assert public_record.status == "timed_out"
    assert evidence_record.status == "complete"


@pytest.mark.asyncio
async def test_long_running_job_emits_real_replayable_heartbeat():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    class SlowBackend(MockCodexBackend):
        async def understand(self, *args, **kwargs):
            await asyncio.sleep(0.04)
            return await super().understand(*args, **kwargs)

    manager = JobManager(
        SlowBackend(),
        public_job_timeout_seconds=2,
        heartbeat_interval_seconds=0.01,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    record = manager.start("success", "ar")
    await record.task

    heartbeats = [event for event in record.events if event.type == "heartbeat"]
    assert heartbeats
    assert [event.id for event in record.events] == list(range(1, len(record.events) + 1))
    assert all(event.payload.elapsed_ms >= 0 for event in heartbeats)
