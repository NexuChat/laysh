import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def backend():
    from server.codex_backend import MockCodexBackend

    return MockCodexBackend()


@pytest.fixture
def client(backend):
    from server.app import create_app
    from server.browser_verify import BrowserVerificationResult

    with TestClient(
        create_app(
            backend=backend,
            job_timeout_seconds=2.0,
            browser_verifier=lambda _: BrowserVerificationResult.passing(),
        )
    ) as test_client:
        yield test_client


def wait_for_terminal(client: TestClient, job_id: str, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        result = response.json()
        if result["status"] in {
            "complete",
            "answer_only",
            "rejected",
            "failed",
            "cancelled",
            "timed_out",
            "qa_inconclusive",
        }:
            return result
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach a terminal state")
