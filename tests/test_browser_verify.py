import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]


def test_browser_gate_returns_actionable_structured_failures(monkeypatch):
    from server.browser_verify import verify_artifact_in_browser

    observed = {
        "ready": True,
        "controlChanged": False,
        "frameChanged": True,
        "idleMotionSubjectChangedPixelRatio": 0.011,
        "idleMotionWholeCanvasChangedPixelRatio": 0.004,
        "idleMotionCaptureIntervalMs": 1100,
        "autoAdvanceValueChanged": True,
        "sliderTrackedAnimation": True,
        "controlAlwaysEnabled": True,
        "pauseHeldValue": True,
        "sliderInteractionYielded": True,
        "reducedMotionStartedPaused": True,
        "reducedMotionPlayOptInWorked": True,
        "renderOutputSweep": {"passed": True, "samples": [{"parameter": 0}]},
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
    assert result.check_count == 15
    assert result.evidence == observed
    assert result.failures == [
        {
            "gate": "browser_readiness",
            "code": "primary_control_unchanged",
            "expected": {"control_changed": True},
            "actual": {"control_changed": False},
        }
    ]


def test_browser_gate_rejects_backdrop_only_motion_with_a_subject_region_diagnostic():
    from server.browser_verify import _evaluate

    result = _evaluate(
        {
            "ready": True,
            "controlChanged": True,
            "frameChanged": True,
            "idleMotionSubjectChangedPixelRatio": 0.004,
            "idleMotionWholeCanvasChangedPixelRatio": 0.014,
            "idleMotionCaptureIntervalMs": 1100,
            "autoAdvanceValueChanged": True,
            "sliderTrackedAnimation": True,
            "controlAlwaysEnabled": True,
            "pauseHeldValue": True,
            "sliderInteractionYielded": True,
            "reducedMotionStartedPaused": True,
            "reducedMotionPlayOptInWorked": True,
            "renderOutputSweep": {"passed": True, "samples": [{"parameter": 0}]},
            "runtimeError": False,
            "externalRequests": 0,
        }
    )

    assert result.passed is False
    assert result.failures == [
        {
            "gate": "visual_richness",
            "code": "subject_idle_motion_insufficient",
            "expected": {
                "region": "central_60_percent",
                "minimum_changed_pixel_ratio": 0.01,
                "capture_interval_ms": 1000,
            },
            "actual": {
                "region": "central_60_percent",
                "changed_pixel_ratio": 0.004,
                "shortfall": 0.006,
                "capture_interval_ms": 1100,
            },
        }
    ]


def test_browser_gate_reports_a_whole_canvas_freeze_separately():
    from server.browser_verify import _evaluate

    result = _evaluate(
        {
            "ready": True,
            "controlChanged": True,
            "frameChanged": True,
            "idleMotionSubjectChangedPixelRatio": 0.012,
            "idleMotionWholeCanvasChangedPixelRatio": 0.0,
            "idleMotionCaptureIntervalMs": 1100,
            "autoAdvanceValueChanged": True,
            "sliderTrackedAnimation": True,
            "controlAlwaysEnabled": True,
            "pauseHeldValue": True,
            "sliderInteractionYielded": True,
            "reducedMotionStartedPaused": True,
            "reducedMotionPlayOptInWorked": True,
            "renderOutputSweep": {"passed": True, "samples": [{"parameter": 0}]},
            "runtimeError": False,
            "externalRequests": 0,
        }
    )

    assert result.passed is False
    assert result.failures == [
        {
            "gate": "visual_richness",
            "code": "whole_canvas_idle_motion_insufficient",
            "expected": {
                "region": "whole_canvas",
                "minimum_changed_pixel_ratio": 0.001,
                "capture_interval_ms": 1000,
            },
            "actual": {
                "region": "whole_canvas",
                "changed_pixel_ratio": 0.0,
                "shortfall": 0.001,
                "capture_interval_ms": 1100,
            },
        }
    ]


def test_browser_gate_accepts_motion_above_both_region_thresholds():
    from server.browser_verify import _evaluate

    result = _evaluate(
        {
            "ready": True,
            "controlChanged": True,
            "frameChanged": True,
            "idleMotionSubjectChangedPixelRatio": 0.0101,
            "idleMotionWholeCanvasChangedPixelRatio": 0.0011,
            "idleMotionCaptureIntervalMs": 1100,
            "autoAdvanceValueChanged": True,
            "sliderTrackedAnimation": True,
            "controlAlwaysEnabled": True,
            "pauseHeldValue": True,
            "sliderInteractionYielded": True,
            "reducedMotionStartedPaused": True,
            "reducedMotionPlayOptInWorked": True,
            "renderOutputSweep": {"passed": True, "samples": [{"parameter": 0}]},
            "runtimeError": False,
            "externalRequests": 0,
        }
    )

    assert result.passed is True


def test_actor_tracking_accepts_a_swinging_bob_with_measured_period():
    from server.browser_verify import BrowserVerificationResult, _evaluate

    tracking = {
        "passed": True,
        "action": "oscillates",
        "actorId": "pendulum_bob",
        "expected": {
            "signReversalsAtLeast": 3,
            "periodSeconds": 2.006,
            "periodToleranceRatio": 0.15,
        },
        "measured": {
            "signReversals": 4,
            "periodSeconds": 2.04,
            "periodErrorRatio": 0.0169,
            "horizontalSpanPixels": 27.4,
        },
    }
    result = _evaluate(
        {**BrowserVerificationResult.passing().evidence, "actorTracking": tracking}
    )

    assert result.passed is True
    assert result.evidence["actorTracking"]["measured"]["periodSeconds"] == 2.04


def test_actor_tracking_rejects_static_actor_with_moving_shadows():
    from server.browser_verify import BrowserVerificationResult, _evaluate

    tracking = {
        "passed": False,
        "action": "rotates",
        "actorId": "earth_surface_feature",
        "failure": {
            "code": "actor_trajectory_static",
            "expected": {"angularDisplacementDegrees": 90, "minimumSpanPixels": 6},
            "measured": {
                "angularDisplacementDegrees": 0,
                "horizontalSpanPixels": 0.3,
                "shadowChangedPixelRatio": 0.18,
            },
        },
    }
    result = _evaluate(
        {**BrowserVerificationResult.passing().evidence, "actorTracking": tracking}
    )

    assert result.passed is False
    assert result.failures[-1] == {
        "gate": "actor_action_tracking",
        "code": "actor_trajectory_static",
        "expected": tracking["failure"]["expected"],
        "actual": tracking["failure"]["measured"],
    }


def test_render_output_consistency_failure_reports_exact_adjacent_samples():
    from server.browser_verify import BrowserVerificationResult, _evaluate

    evidence = {
        **BrowserVerificationResult.passing().evidence,
        "renderOutputSweep": {
            "passed": False,
            "samples": [],
            "failure": {
                "code": "rendered_output_discontinuity",
                "metric": "brightPixelRatio",
                "left": {"parameter": 180, "computedOutput": 1.0, "renderedMeasure": 0.237},
                "right": {"parameter": 195, "computedOutput": 0.983, "renderedMeasure": 0.011},
            },
        },
    }

    result = _evaluate(evidence)

    assert result.passed is False
    assert result.failures == [{
        "gate": "render_output_consistency",
        "code": "rendered_output_discontinuity",
        "expected": {
            "full_parameter_sweep": True,
            "render_tracks_computed_output": True,
            "adjacent_discontinuities": 0,
        },
        "actual": evidence["renderOutputSweep"]["failure"],
    }]


@pytest.mark.browser
def test_real_render_sweep_rejects_correct_numbers_with_a_post_180_visual_cliff():
    from server.assemble import assemble_artifact
    from server.browser_verify import verify_artifact_in_browser

    source = (ROOT / "tests" / "fixtures" / "moon_phase_module.js").read_text(
        encoding="utf-8"
    )
    broken_painter = source.replace(
        "const fraction = litFraction(angleDeg);",
        "const fraction = angleDeg > 180 ? 0 : litFraction(angleDeg);",
        1,
    )
    understanding = deepcopy(VALID_UNDERSTANDING)
    artifact = assemble_artifact(
        understanding,
        {**VALID_MODULE_OUTPUT, "module_js": broken_painter},
    )

    result = verify_artifact_in_browser(artifact)

    failures = [
        failure
        for failure in result.failures
        if failure["gate"] == "render_output_consistency"
    ]
    assert len(failures) == 1
    failure = failures[0]
    assert failure["code"] in {
        "rendered_output_discontinuity",
        "rendered_output_not_monotonic_consistent",
    }
    assert failure["actual"]["left"]["parameter"] == 180
    assert failure["actual"]["right"]["parameter"] == 202.5
    for side in ("left", "right"):
        assert set(failure["actual"][side]) == {
            "parameter",
            "computedOutput",
            "renderedMeasure",
        }


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


@pytest.mark.asyncio
async def test_idle_motion_failure_enters_the_existing_bounded_heal_loop():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    motion_failure = {
        "gate": "visual_richness",
        "code": "subject_idle_motion_insufficient",
        "expected": {
            "region": "central_60_percent",
            "minimum_changed_pixel_ratio": 0.01,
            "capture_interval_ms": 1000,
        },
        "actual": {
            "region": "central_60_percent",
            "changed_pixel_ratio": 0.0,
            "shortfall": 0.01,
            "capture_interval_ms": 1100,
        },
    }
    reports = [
        BrowserVerificationResult(False, 15, [motion_failure], {}),
        BrowserVerificationResult.passing(),
    ]
    backend = MockCodexBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: reports.pop(0),
    )
    record = manager.start("success", "ar")
    await record.task

    assert record.status == "complete"
    assert backend.heal_calls == 1
    assert backend.last_heal_failures[0] == [motion_failure]
