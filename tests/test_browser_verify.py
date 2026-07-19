import json
from types import SimpleNamespace

import pytest


def test_browser_gate_returns_actionable_structured_failures(monkeypatch):
    from server.browser_verify import verify_artifact_in_browser

    observed = {
        "ready": True,
        "controlChanged": False,
        "frameChanged": True,
        "runtimeError": False,
        "externalRequests": 0,
    }
    monkeypatch.setattr("server.browser_verify.shutil.which", lambda _: "/usr/bin/node")
    monkeypatch.setattr(
        "server.browser_verify.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(observed),
            stderr="",
        ),
    )

    result = verify_artifact_in_browser("<!doctype html><title>fixture</title>")

    assert result.passed is False
    assert result.check_count == 5
    assert result.evidence == observed
    assert result.failures == [
        {
            "gate": "browser_readiness",
            "code": "primary_control_unchanged",
            "expected": {"control_changed": True},
            "actual": {"control_changed": False},
        }
    ]


@pytest.mark.asyncio
async def test_browser_failure_enters_heal_with_exact_report_before_publish():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    reports = [
        BrowserVerificationResult(
            passed=False,
            check_count=5,
            failures=[
                {
                    "gate": "browser_readiness",
                    "code": "primary_control_unchanged",
                    "expected": {"control_changed": True},
                    "actual": {"control_changed": False},
                }
            ],
            evidence={
                "ready": True,
                "controlChanged": False,
                "frameChanged": True,
                "runtimeError": False,
                "externalRequests": 0,
            },
        ),
        BrowserVerificationResult.passing(),
    ]

    def browser_verifier(_artifact):
        return reports.pop(0)

    backend = MockCodexBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=browser_verifier,
    )
    record = manager.start("success", "ar")
    await record.task

    assert record.status == "complete"
    assert backend.heal_calls == 1
    assert backend.last_heal_failures[0] == [
        {
            "gate": "browser_readiness",
            "code": "primary_control_unchanged",
            "expected": {"control_changed": True},
            "actual": {"control_changed": False},
        }
    ]
    assert record.simulation is not None
    assert record.simulation.heal_count == 1
    assert reports == []
