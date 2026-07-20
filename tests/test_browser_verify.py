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
        "mobileOverlayLayout": {"passed": True},
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
    assert result.check_count == 16
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
            "mobileOverlayLayout": {"passed": True},
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
            "mobileOverlayLayout": {"passed": True},
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
            "mobileOverlayLayout": {"passed": True},
            "runtimeError": False,
            "externalRequests": 0,
        }
    )

    assert result.passed is True, result.failures


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


def test_paused_actor_tracking_accepts_held_wave_with_advancing_phase():
    from server.browser_verify import BrowserVerificationResult, _evaluate

    paused = {
        "passed": True,
        "lesson": "How does frequency change pitch?",
        "action": "propagates",
        "heldParameter": {"id": "frequency_hz", "value": 440, "unit": "Hz"},
        "expected": {"phaseShiftRadians": 1.5708, "maximumErrorRadians": 0.6},
        "measured": {"phaseShiftRadians": 1.549, "phaseErrorRadians": 0.0218},
    }
    result = _evaluate(
        {**BrowserVerificationResult.passing().evidence, "pausedActorTracking": paused}
    )

    assert result.passed is True
    assert result.evidence["pausedActorTracking"]["heldParameter"]["value"] == 440


def test_paused_actor_tracking_rejects_frozen_wave_with_exact_lesson_diagnostic():
    from server.browser_verify import BrowserVerificationResult, _evaluate

    expected = {
        "lesson": "How does frequency change pitch?",
        "held_parameter": {"id": "frequency_hz", "value": 440, "unit": "Hz"},
        "action": "propagates",
        "phase_shift_radians": 1.5708,
        "maximum_error_radians": 0.6,
    }
    measured = {
        "lesson": "How does frequency change pitch?",
        "held_parameter": {"id": "frequency_hz", "value": 440, "unit": "Hz"},
        "phase_shift_radians": 0.0,
        "phase_error_radians": 1.5708,
    }
    paused = {
        "passed": False,
        "failure": {
            "code": "paused_propagation_phase_static",
            "expected": expected,
            "measured": measured,
        },
    }
    result = _evaluate(
        {**BrowserVerificationResult.passing().evidence, "pausedActorTracking": paused}
    )

    assert result.passed is False
    assert result.failures[-1] == {
        "gate": "actor_action_tracking",
        "code": "paused_propagation_phase_static",
        "expected": expected,
        "actual": measured,
    }


def _wave_understanding():
    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding.update(
        {
            "canonical_intent": "sound_frequency_pitch",
            "domain": "physics_acoustics",
            "title": "How does frequency change pitch?",
            "key_formula": "λ = v / f; T = 1 / f",
            "actor": {
                "id": "sound_wave",
                "label": "sound wave",
                "tracking_signature": {
                    "color_rgb": [103, 232, 249],
                    "tolerance": 12,
                    "reference_color_rgb": None,
                    "reference_tolerance": None,
                },
                "tracking_output": "period_ms",
            },
            "action": "propagates",
            "primary_parameter": {
                "id": "frequency_hz",
                "label": "Frequency",
                "unit": "Hz",
                "min": 110,
                "max": 880,
                "default": 440,
                "step": 10,
                "sweep_mode": "bounce",
            },
            "module_spec": {"outputs": ["wavelength_m", "period_ms"]},
            "checks": [
                {
                    "id": "wavelength_at_440",
                    "kind": "numeric",
                    "inputs": [{"name": "frequency_hz", "value": 440}],
                    "output": "wavelength_m",
                    "expected": 0.7795,
                    "tolerance": 0.01,
                    "unit": "m",
                },
                {
                    "id": "period_at_440",
                    "kind": "numeric",
                    "inputs": [{"name": "frequency_hz", "value": 440}],
                    "output": "period_ms",
                    "expected": 2.2727,
                    "tolerance": 0.01,
                    "unit": "ms",
                },
            ],
        }
    )
    return understanding


@pytest.mark.browser
@pytest.mark.parametrize("frozen", [False, True])
def test_paused_phenomenon_gate_accepts_travelling_wave_and_rejects_frozen_wave(frozen):
    from server.assemble import assemble_artifact
    from server.browser_verify import verify_artifact_in_browser

    source = (ROOT / "tests" / "fixtures" / "travelling_wave_module.js").read_text(
        encoding="utf-8"
    )
    if frozen:
        source = source.replace(
            "phenomenonTimeSeconds = Number.isFinite(Number(timeSeconds)) "
            "? Number(timeSeconds) : 0;",
            "phenomenonTimeSeconds = 0;",
        )
    artifact = assemble_artifact(
        _wave_understanding(),
        {
            **VALID_MODULE_OUTPUT,
            "module_js": source,
            "output_names": ["wavelength_m", "period_ms"],
        },
    )

    result = verify_artifact_in_browser(artifact)
    paused = result.evidence["pausedActorTracking"]

    assert paused["passed"] is (not frozen)
    if frozen:
        assert paused["failure"]["code"] == "paused_propagation_phase_static"
        assert paused["failure"]["expected"]["lesson"] == _wave_understanding()["title"]
        held = paused["failure"]["measured"]["held_parameter"]
        assert held == paused["failure"]["expected"]["held_parameter"]
        assert held["id"] == "frequency_hz" and held["unit"] == "Hz"
        assert 110 <= held["value"] <= 880


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


def test_mobile_overlay_band_accepts_one_edge_label_clear_of_subject():
    from server.browser_verify import BrowserVerificationResult, _evaluate

    mobile = {
        "passed": True,
        "canvas": {"width": 360, "height": 274},
        "subjectRegion": {"x": 72, "y": 55, "width": 216, "height": 164},
        "overlayRects": [
            {"x": 10, "y": 8, "width": 78, "height": 24, "role": "essential-state"}
        ],
        "overlayCount": 1,
        "overlayHeightRatio": 0.0876,
        "subjectOverlapPixels": 0,
    }
    result = _evaluate(
        {**BrowserVerificationResult.passing().evidence, "mobileOverlayLayout": mobile}
    )

    assert result.passed is True
    assert result.evidence["mobileOverlayLayout"] == mobile


def test_mobile_overlay_band_reports_exact_subject_intrusion_to_heal():
    from server.browser_verify import BrowserVerificationResult, _evaluate

    mobile = {
        "passed": False,
        "canvas": {"width": 360, "height": 274},
        "subjectRegion": {"x": 72, "y": 55, "width": 216, "height": 164},
        "overlayRects": [
            {"x": 80, "y": 70, "width": 130, "height": 40, "role": "numeric-readout"},
            {"x": 80, "y": 116, "width": 130, "height": 40, "role": "essential-state"},
        ],
        "failure": {
            "code": "mobile_overlay_subject_intrusion",
            "expected": {
                "canvas_width_max": 420,
                "overlay_count_max": 1,
                "overlay_height_ratio_max": 0.22,
                "subject_overlap_pixels": 0,
            },
            "measured": {
                "overlay_count": 2,
                "overlay_height_ratio": 0.292,
                "subject_overlap_pixels": 10400,
            },
        },
    }
    result = _evaluate(
        {**BrowserVerificationResult.passing().evidence, "mobileOverlayLayout": mobile}
    )

    assert result.passed is False
    assert result.failures == [{
        "gate": "mobile_overlay_safe_band",
        "code": "mobile_overlay_subject_intrusion",
        "expected": mobile["failure"]["expected"],
        "actual": mobile["failure"]["measured"],
    }]


@pytest.mark.browser
def test_static_response_action_tracks_parameter_without_inventing_held_motion():
    from server.assemble import assemble_artifact
    from server.browser_verify import verify_artifact_in_browser

    source = (ROOT / "tests" / "fixtures" / "static_response_module.js").read_text(
        encoding="utf-8"
    )
    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding.update(
        {
            "title": "How does a static response change?",
            "lang": "en",
            "action": "responds",
            "primary_parameter": {
                "id": "stimulus",
                "label": "Stimulus",
                "unit": "units",
                "min": 0,
                "max": 0.5,
                "default": 0.25,
                "step": 0.1,
                "sweep_mode": "bounce",
            },
            "module_spec": {"outputs": ["response_strength"]},
            "checks": [
                {
                    "id": "low",
                    "kind": "numeric",
                    "inputs": [{"name": "stimulus", "value": 0}],
                    "output": "response_strength",
                    "expected": 10,
                    "tolerance": 0.01,
                    "unit": "units",
                },
                {
                    "id": "high",
                    "kind": "numeric",
                    "inputs": [{"name": "stimulus", "value": 0.5}],
                    "output": "response_strength",
                    "expected": 20,
                    "tolerance": 0.01,
                    "unit": "units",
                },
            ],
        }
    )
    understanding["actor"] = {
        "id": "response_body",
        "label": "Response body",
        "tracking_signature": {
            "color_rgb": [31, 211, 174],
            "tolerance": 4,
            "reference_color_rgb": None,
            "reference_tolerance": None,
        },
        "tracking_output": "response_strength",
    }
    artifact = assemble_artifact(
        understanding,
        {
            **VALID_MODULE_OUTPUT,
            "module_js": source,
            "output_names": ["response_strength"],
        },
    )

    result = verify_artifact_in_browser(artifact)

    assert result.passed is True, result.failures
    assert result.evidence["actorTracking"]["action"] == "responds"
    assert result.evidence["pausedActorTracking"]["measured"]["held_state_stable"] is True


@pytest.mark.browser
def test_mobile_gate_accepts_one_raster_measured_safe_edge_label_without_registration():
    from server.assemble import assemble_artifact
    from server.browser_verify import verify_artifact_in_browser

    source = (ROOT / "tests" / "fixtures" / "moon_phase_module.js").read_text(
        encoding="utf-8"
    )
    labeled = source.replace(
        "    emitFrame();",
        '    context.font = "16px sans-serif";\n'
        '    context.fillStyle = "white";\n'
        '    context.fillText("phase", 12, 22);\n'
        "    emitFrame();",
        1,
    )
    artifact = assemble_artifact(
        VALID_UNDERSTANDING,
        {**VALID_MODULE_OUTPUT, "module_js": labeled},
    )

    result = verify_artifact_in_browser(artifact)

    assert result.evidence["mobileOverlayLayout"]["passed"] is True
    assert result.evidence["mobileOverlayLayout"]["drawnLabelRects"]


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
