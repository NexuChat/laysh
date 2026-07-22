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
        "initialOutcomeMatchesModel": True,
        "modelOutcomeChanged": True,
        "displayedOutcomeChanged": True,
        "canvasPixels": 288_000,
        "changedPixels": 2_400,
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
    assert result.check_count == 9
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
                "initialOutcomeMatchesModel": True,
                "modelOutcomeChanged": True,
                "displayedOutcomeChanged": True,
                "canvasPixels": 288_000,
                "changedPixels": 2_400,
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


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("initialOutcomeMatchesModel", False, "initial_outcome_mismatch"),
        ("modelOutcomeChanged", False, "primary_outcome_unchanged"),
        ("displayedOutcomeChanged", False, "displayed_outcome_unchanged"),
        ("changedPixels", 20, "causal_visual_change_too_small"),
    ],
)
def test_browser_gate_fails_closed_when_causal_evidence_is_missing(field, value, code):
    from server.browser_verify import _evaluate

    evidence = {
        "ready": True,
        "controlChanged": True,
        "frameChanged": True,
        "runtimeError": False,
        "externalRequests": 0,
        "initialOutcomeMatchesModel": True,
        "modelOutcomeChanged": True,
        "displayedOutcomeChanged": True,
        "canvasPixels": 288_000,
        "changedPixels": 2_400,
        field: value,
    }

    result = _evaluate(evidence)

    assert result.passed is False
    assert code in {failure["code"] for failure in result.failures}
