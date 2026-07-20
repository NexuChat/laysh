from __future__ import annotations

import base64
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]

# The central 60% occupies 36% of the canvas. Requiring 1% change there is large
# enough to demand motion from a lesson-scale body or trajectory while rejecting
# a few twinkling background pixels. The 0.1% whole-canvas floor is intentionally
# lower: it is only a total-freeze tripwire and can never substitute for subject motion.
SUBJECT_MOTION_MIN_CHANGED_PIXEL_RATIO = 0.01
WHOLE_CANVAS_MOTION_MIN_CHANGED_PIXEL_RATIO = 0.001
MOTION_CAPTURE_INTERVAL_MS = 1000


@dataclass(frozen=True, slots=True)
class BrowserVerificationResult:
    passed: bool
    check_count: int
    failures: list[dict[str, Any]]
    evidence: dict[str, Any]
    vision_frames: tuple[bytes, ...] = ()

    @classmethod
    def passing(cls) -> BrowserVerificationResult:
        return cls(
            passed=True,
            check_count=18,
            failures=[],
            evidence={
                "ready": True,
                "controlChanged": True,
                "frameChanged": True,
                "idleMotionSubjectChangedPixelRatio": 0.011,
                "idleMotionWholeCanvasChangedPixelRatio": 0.004,
                "idleMotionCaptureIntervalMs": 1100,
                "autoAdvanceValueChanged": True,
                "sliderTrackedAnimation": True,
                "controlAlwaysEnabled": True,
                "pauseHeldValue": True,
                "pausedMotionSubjectChangedPixelRatio": 0.012,
                "pausedMotionWholeCanvasChangedPixelRatio": 0.004,
                "pausedMotionCaptureIntervalMs": 1100,
                "sliderInteractionYielded": True,
                "reducedMotionStartedPaused": True,
                "reducedMotionPlayOptInWorked": True,
                "renderOutputSweep": {
                    "passed": True,
                    "metric": "meanLuminance",
                    "rankCorrelation": 0.9,
                    "samples": [{"parameter": 0, "computedOutput": 0, "renderedMeasure": 0}],
                },
                "actorTracking": {
                    "passed": True,
                    "action": "phases",
                    "actorId": "moon",
                    "expected": {"angularDisplacementDegrees": 360},
                    "measured": {"angularDisplacementDegrees": 358.5},
                },
                "pausedActorTracking": {
                    "passed": True,
                    "lesson": "How does frequency change pitch?",
                    "action": "propagates",
                    "actorId": "sound_wave",
                    "heldParameter": {
                        "id": "frequency_hz",
                        "value": 440,
                        "unit": "Hz",
                    },
                    "expected": {"phase_shift_radians": 1.5708},
                    "measured": {"phase_shift_radians": 1.55},
                },
                "mobileOverlayLayout": {
                    "passed": True,
                    "canvas": {"width": 360, "height": 274},
                    "subjectRegion": {"x": 72, "y": 55, "width": 216, "height": 164},
                    "overlayRects": [],
                    "drawnLabelRects": [],
                    "overlayCount": 0,
                    "overlayHeightRatio": 0,
                    "subjectOverlapPixels": 0,
                    "failure": None,
                },
                "runtimeError": False,
                "externalRequests": 0,
            },
        )


def _failure(
    code: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    gate: str = "browser_readiness",
) -> dict[str, Any]:
    return {
        "gate": gate,
        "code": code,
        "expected": expected,
        "actual": actual,
    }


def _evaluate(evidence: dict[str, Any]) -> BrowserVerificationResult:
    failures = []
    capture_interval = evidence.get("idleMotionCaptureIntervalMs")
    subject_ratio = float(evidence.get("idleMotionSubjectChangedPixelRatio", 0))
    whole_canvas_ratio = float(evidence.get("idleMotionWholeCanvasChangedPixelRatio", 0))
    actor_tracking = evidence.get("actorTracking")
    # A thin refracted ray or field indicator can be causally strong while occupying less area than
    # an orbiting body. Keep the changed-subject principle, but use a justified 0.5% floor for the
    # static-response adapter; actor correlation independently rejects decorative pixel motion.
    subject_motion_minimum = (
        0.005
        if isinstance(actor_tracking, dict) and actor_tracking.get("action") == "responds"
        else SUBJECT_MOTION_MIN_CHANGED_PIXEL_RATIO
    )
    checks = (
        (
            bool(evidence.get("ready")),
            "first_frame_missing",
            {"first_frame_ready": True},
            {"first_frame_ready": bool(evidence.get("ready"))},
            "browser_readiness",
        ),
        (
            bool(evidence.get("controlChanged")),
            "primary_control_unchanged",
            {"control_changed": True},
            {"control_changed": bool(evidence.get("controlChanged"))},
            "browser_readiness",
        ),
        (
            bool(evidence.get("frameChanged")),
            "visible_frame_unchanged",
            {"frame_changed": True},
            {"frame_changed": bool(evidence.get("frameChanged"))},
            "browser_readiness",
        ),
        (
            subject_ratio >= subject_motion_minimum,
            "subject_idle_motion_insufficient",
            {
                "region": "central_60_percent",
                "minimum_changed_pixel_ratio": subject_motion_minimum,
                "capture_interval_ms": MOTION_CAPTURE_INTERVAL_MS,
            },
            {
                "region": "central_60_percent",
                "changed_pixel_ratio": subject_ratio,
                "shortfall": round(
                    max(0, subject_motion_minimum - subject_ratio), 6
                ),
                "capture_interval_ms": capture_interval,
            },
            "visual_richness",
        ),
        (
            whole_canvas_ratio >= WHOLE_CANVAS_MOTION_MIN_CHANGED_PIXEL_RATIO,
            "whole_canvas_idle_motion_insufficient",
            {
                "region": "whole_canvas",
                "minimum_changed_pixel_ratio": WHOLE_CANVAS_MOTION_MIN_CHANGED_PIXEL_RATIO,
                "capture_interval_ms": MOTION_CAPTURE_INTERVAL_MS,
            },
            {
                "region": "whole_canvas",
                "changed_pixel_ratio": whole_canvas_ratio,
                "shortfall": round(
                    max(0, WHOLE_CANVAS_MOTION_MIN_CHANGED_PIXEL_RATIO - whole_canvas_ratio), 6
                ),
                "capture_interval_ms": capture_interval,
            },
            "visual_richness",
        ),
        (
            bool(evidence.get("autoAdvanceValueChanged")),
            "parameter_did_not_auto_advance",
            {"fresh_lesson_parameter_advances": True},
            {"fresh_lesson_parameter_advances": bool(evidence.get("autoAdvanceValueChanged"))},
            "motion_control",
        ),
        (
            bool(evidence.get("sliderTrackedAnimation")),
            "slider_did_not_track_animation",
            {"slider_tracks_parameter": True},
            {"slider_tracks_parameter": bool(evidence.get("sliderTrackedAnimation"))},
            "motion_control",
        ),
        (
            bool(evidence.get("controlAlwaysEnabled")),
            "primary_control_disabled",
            {"primary_control_always_enabled": True},
            {"primary_control_always_enabled": bool(evidence.get("controlAlwaysEnabled"))},
            "motion_control",
        ),
        (
            bool(evidence.get("pauseHeldValue")),
            "pause_did_not_hold_parameter",
            {"paused_parameter_stable": True},
            {"paused_parameter_stable": bool(evidence.get("pauseHeldValue"))},
            "motion_control",
        ),
        (
            bool(evidence.get("sliderInteractionYielded")),
            "slider_interaction_did_not_yield_motion",
            {"auto_advance_yields_during_slider_interaction": True},
            {
                "auto_advance_yields_during_slider_interaction": bool(
                    evidence.get("sliderInteractionYielded")
                )
            },
            "motion_control",
        ),
        (
            bool(evidence.get("reducedMotionStartedPaused")),
            "reduced_motion_autoplayed",
            {"reduced_motion_starts_paused": True},
            {"reduced_motion_starts_paused": bool(evidence.get("reducedMotionStartedPaused"))},
            "reduced_motion",
        ),
        (
            bool(evidence.get("reducedMotionPlayOptInWorked")),
            "reduced_motion_play_opt_in_failed",
            {"reduced_motion_play_control_works": True},
            {
                "reduced_motion_play_control_works": bool(
                    evidence.get("reducedMotionPlayOptInWorked")
                )
            },
            "reduced_motion",
        ),
        (
            not bool(evidence.get("runtimeError")),
            "runtime_error_beacon",
            {"runtime_error": False},
            {"runtime_error": bool(evidence.get("runtimeError"))},
            "browser_readiness",
        ),
        (
            evidence.get("externalRequests") == 0,
            "external_request_observed",
            {"external_requests": 0},
            {"external_requests": evidence.get("externalRequests")},
            "browser_readiness",
        ),
    )
    for passed, code, expected, actual, gate in checks:
        if not passed:
            failures.append(_failure(code, expected, actual, gate=gate))
    render_sweep = evidence.get("renderOutputSweep")
    render_passed = isinstance(render_sweep, dict) and render_sweep.get("passed") is True
    if not render_passed:
        diagnostic = render_sweep.get("failure", {}) if isinstance(render_sweep, dict) else {}
        failures.append(
            _failure(
                str(diagnostic.get("code", "render_output_sweep_missing")),
                {
                    "full_parameter_sweep": True,
                    "render_tracks_computed_output": True,
                    "adjacent_discontinuities": 0,
                },
                diagnostic,
                gate="render_output_consistency",
            )
        )
    if isinstance(actor_tracking, dict) and actor_tracking.get("passed") is not True:
        diagnostic = actor_tracking.get("failure", {})
        failures.append(
            _failure(
                str(diagnostic.get("code", "actor_trajectory_mismatch")),
                diagnostic.get("expected", {"declared_action_performed": True}),
                diagnostic.get("measured", {}),
                gate="actor_action_tracking",
            )
        )
    paused_actor_tracking = evidence.get("pausedActorTracking")
    paused_actor_required = isinstance(actor_tracking, dict)
    paused_actor_passed = isinstance(paused_actor_tracking, dict) and (
        paused_actor_tracking.get("passed") is True
    )
    if paused_actor_required and not paused_actor_passed:
        diagnostic = (
            paused_actor_tracking.get("failure", {})
            if isinstance(paused_actor_tracking, dict)
            else {}
        )
        failures.append(
            _failure(
                str(diagnostic.get("code", "paused_actor_tracking_missing")),
                diagnostic.get(
                    "expected",
                    {
                        "sweep_state": "paused",
                        "held_parameter_stable": True,
                        "declared_action_continues": True,
                    },
                ),
                diagnostic.get("measured", {}),
                gate="actor_action_tracking",
            )
        )
    mobile_layout = evidence.get("mobileOverlayLayout")
    mobile_passed = isinstance(mobile_layout, dict) and mobile_layout.get("passed") is True
    if not mobile_passed:
        diagnostic = mobile_layout.get("failure", {}) if isinstance(mobile_layout, dict) else {}
        failures.append(
            _failure(
                str(diagnostic.get("code", "mobile_overlay_measurement_missing")),
                diagnostic.get(
                    "expected",
                    {
                        "canvas_width_max": 420,
                        "overlay_count_max": 1,
                        "overlay_height_ratio_max": 0.22,
                        "subject_overlap_pixels": 0,
                    },
                ),
                diagnostic.get("measured", {}),
                gate="mobile_overlay_safe_band",
            )
        )
    return BrowserVerificationResult(
        passed=not failures,
        check_count=(
            len(checks)
            + 2
            + int(isinstance(actor_tracking, dict))
            + int(isinstance(paused_actor_tracking, dict))
        ),
        failures=failures,
        evidence=evidence,
    )


def verify_artifact_in_browser(artifact: str) -> BrowserVerificationResult:
    node = shutil.which("node")
    if node is None:
        return BrowserVerificationResult(
            passed=False,
            check_count=1,
            failures=[
                _failure(
                    "browser_probe_unavailable",
                    {"node_available": True},
                    {"node_available": False},
                )
            ],
            evidence={},
        )
    with tempfile.TemporaryDirectory(prefix="laysh-browser-gate-") as temporary:
        artifact_path = Path(temporary) / "artifact.html"
        artifact_path.write_text(artifact, encoding="utf-8")
        try:
            completed = subprocess.run(  # noqa: S603 - fixed verifier and disposable artifact
                [node, str(ROOT / "scripts" / "check_artifact.mjs"), str(artifact_path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return BrowserVerificationResult(
                passed=False,
                check_count=1,
                failures=[
                    _failure(
                        "browser_probe_timeout",
                        {"maximum_seconds": 30},
                        {"timed_out": True},
                    )
                ],
                evidence={},
            )
    if completed.returncode != 0:
        return BrowserVerificationResult(
            passed=False,
            check_count=1,
            failures=[
                _failure(
                    "browser_probe_failed",
                    {"exit_code": 0},
                    {"exit_code": completed.returncode},
                )
            ],
            evidence={},
        )
    try:
        evidence = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return BrowserVerificationResult(
            passed=False,
            check_count=1,
            failures=[
                _failure(
                    "browser_probe_malformed",
                    {"valid_json": True},
                    {"valid_json": False},
                )
            ],
            evidence={},
        )
    encoded_frames = evidence.pop("visionFrames", [])
    try:
        vision_frames = tuple(base64.b64decode(value, validate=True) for value in encoded_frames)
    except (ValueError, TypeError):
        vision_frames = ()
    evaluated = _evaluate(evidence)
    return BrowserVerificationResult(
        passed=evaluated.passed,
        check_count=evaluated.check_count,
        failures=evaluated.failures,
        evidence=evaluated.evidence,
        vision_frames=vision_frames,
    )
