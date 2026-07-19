from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import create_app
from server.browser_verify import BrowserVerificationResult
from server.ratelimit import GenerationLimiter
from tests.conftest import wait_for_terminal


def test_generation_limiter_enforces_hourly_ip_and_daily_global_windows():
    now = [100_000.0]
    limiter = GenerationLimiter(
        secret=b"test-only-secret",
        per_ip_per_hour=2,
        global_per_day=3,
        clock=lambda: now[0],
    )

    assert limiter.acquire("192.0.2.1") is None
    assert limiter.acquire("192.0.2.1") is None
    assert limiter.acquire("192.0.2.1") == "ip_generation_limit"
    assert limiter.acquire("192.0.2.2") is None
    assert limiter.acquire("192.0.2.3") == "global_generation_limit"

    now[0] += 3601
    assert limiter.acquire("192.0.2.1") == "global_generation_limit"
    now[0] += 86_401
    assert limiter.acquire("192.0.2.1") is None


def test_api_degrades_rate_limit_to_localized_answer_only_without_model_spend(
    monkeypatch, backend
):
    monkeypatch.setenv("LAYSH_IP_GENERATIONS_PER_HOUR", "1")
    with TestClient(
        create_app(
            backend=backend,
            job_timeout_seconds=2,
            browser_verifier=lambda _: BrowserVerificationResult.passing(),
        )
    ) as client:
        accepted = client.post("/api/ask", json={"question": "success", "locale": "ar"})
        wait_for_terminal(client, accepted.json()["job_id"])
        limited = client.post("/api/ask", json={"question": "success again", "locale": "ar"})
        result = wait_for_terminal(client, limited.json()["job_id"])

    assert limited.status_code == 202
    assert result["status"] == "answer_only"
    assert result["fallback"]["reason_code"] == "ip_generation_limit"
    assert "الحد" in result["answer"]["tldr"]
    assert backend.understand_calls == backend.generate_calls == 1


def test_api_degrades_full_queue_without_spending_generation_quota(monkeypatch, backend):
    monkeypatch.setenv("LAYSH_MAX_CONCURRENT_JOBS", "1")
    monkeypatch.setenv("LAYSH_MAX_QUEUED_JOBS", "0")
    with TestClient(
        create_app(
            backend=backend,
            job_timeout_seconds=2,
            browser_verifier=lambda _: BrowserVerificationResult.passing(),
        )
    ) as client:
        first = client.post("/api/ask", json={"question": "timeout", "locale": "en"})
        second = client.post("/api/ask", json={"question": "success", "locale": "en"})
        result = wait_for_terminal(client, second.json()["job_id"])
        client.post(f"/api/jobs/{first.json()['job_id']}/cancel")

    assert result["status"] == "answer_only"
    assert result["fallback"]["reason_code"] == "queue_full"
    assert "busy" in result["answer"]["tldr"].lower()
