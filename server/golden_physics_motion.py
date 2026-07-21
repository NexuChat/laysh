from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from itertools import combinations
from pathlib import Path
from typing import Any

from server.motion import evaluate_actor_trajectory
from server.physics_motion import evaluate_action_physics

ROOT = Path(__file__).parents[1]


def _failure(code: str, expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    return {
        "gate": "physics_motion_browser",
        "code": code,
        "expected": expected,
        "actual": actual,
    }


def _browser_failures(evidence: Mapping[str, object]) -> list[dict[str, Any]]:
    checks = (
        (bool(evidence.get("ready")), "physics_motion_not_ready", {"ready": True}),
        (
            not bool(evidence.get("runtimeError")),
            "physics_motion_runtime_error",
            {"runtime_error": False},
        ),
        (
            evidence.get("externalRequests") == 0,
            "physics_motion_external_request",
            {"external_requests": 0},
        ),
        (
            evidence.get("consoleErrors") == [],
            "physics_motion_console_error",
            {"console_errors": []},
        ),
    )
    return [
        _failure(code, expected, {key: evidence.get(key) for key in expected})
        for passed, code, expected in checks
        if not passed
    ]


def evaluate_body_geometry(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Reject undeclared intersections between rendered circular bodies."""

    failures: list[dict[str, Any]] = []
    check_count = 0
    minimum_clearance = math.inf
    for sample in samples:
        bodies = sample.get("bodies")
        if not isinstance(bodies, list) or len(bodies) < 2:
            failures.append(
                {
                    "gate": "body_geometry",
                    "code": "drawn_body_geometry_missing",
                    "expected": {"minimum_named_bodies": 2},
                    "actual": {"bodies": bodies},
                    "message": "Rendered body geometry is missing or incomplete.",
                }
            )
            check_count += 1
            continue
        for body_a, body_b in combinations(bodies, 2):
            check_count += 1
            contacts_a = body_a.get("contacts", [])
            contacts_b = body_b.get("contacts", [])
            if body_b.get("name") in contacts_a or body_a.get("name") in contacts_b:
                continue
            if body_a.get("shape") != "circle" or body_b.get("shape") != "circle":
                failures.append(
                    {
                        "gate": "body_geometry",
                        "code": "unsupported_body_shape",
                        "expected": {"shape": "circle"},
                        "actual": {
                            "body_a": body_a.get("name"),
                            "shape_a": body_a.get("shape"),
                            "body_b": body_b.get("name"),
                            "shape_b": body_b.get("shape"),
                        },
                        "message": "Rendered bodies must declare supported circle geometry.",
                    }
                )
                continue
            try:
                center_distance = math.hypot(
                    float(body_a["x"]) - float(body_b["x"]),
                    float(body_a["y"]) - float(body_b["y"]),
                )
                clearance = center_distance - float(body_a["radius"]) - float(
                    body_b["radius"]
                )
            except (KeyError, TypeError, ValueError):
                failures.append(
                    {
                        "gate": "body_geometry",
                        "code": "invalid_body_geometry",
                        "expected": {"finite_circle_geometry": True},
                        "actual": {"body_a": body_a, "body_b": body_b},
                        "message": "Rendered body geometry is not a finite circle.",
                    }
                )
                continue
            if not math.isfinite(clearance):
                failures.append(
                    {
                        "gate": "body_geometry",
                        "code": "invalid_body_geometry",
                        "expected": {"finite_circle_geometry": True},
                        "actual": {"body_a": body_a, "body_b": body_b},
                        "message": "Rendered body geometry is not a finite circle.",
                    }
                )
                continue
            minimum_clearance = min(minimum_clearance, clearance)
            if clearance >= 0:
                continue
            overlap = round(-clearance, 3)
            viewport = sample.get("viewport")
            canvas = sample.get("canvas")
            parameter = sample.get("parameter")
            viewport_text = f'{viewport.get("width")}x{viewport.get("height")}'
            canvas_text = f'{canvas.get("width")}x{canvas.get("height")}'
            parameter_text = f'{parameter.get("name")}={parameter.get("value")}'
            failures.append(
                {
                    "gate": "body_geometry",
                    "code": "drawn_bodies_overlap",
                    "expected": {"overlap_px": 0, "contact_declared": False},
                    "actual": {
                        "body_a": body_a["name"],
                        "body_b": body_b["name"],
                        "viewport": viewport,
                        "canvas": canvas,
                        "parameter": parameter,
                        "overlap_px": overlap,
                    },
                    "message": (
                        f'{body_a["name"]} and {body_b["name"]} overlap by '
                        f"{overlap:.2f}px at viewport {viewport_text} "
                        f"(canvas {canvas_text}, {parameter_text})."
                    ),
                }
            )
    return {
        "passed": not failures,
        "check_count": check_count,
        "minimum_clearance_px": (
            round(minimum_clearance, 3) if math.isfinite(minimum_clearance) else None
        ),
        "failures": failures,
    }


def verify_golden_physics_motion(
    *,
    artifact: str,
    golden_id: str,
    actor_profile: Mapping[str, object],
    physics_profile: Mapping[str, object],
    geometry_profile: Mapping[str, object] | None = None,
    screenshot_root: Path | None = None,
) -> dict[str, Any]:
    """Prove a pinned module's declared action with browser-observed physics.

    The Node harness observes only repository-owned artifacts.  Its whole-canvas
    hashes and frame counts remain diagnostic evidence; actor paths, structured
    ``test(inputs)`` outputs, and action-specific measurements decide the gate.
    """

    node = shutil.which("node")
    if node is None:
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                _failure(
                    "physics_motion_browser_unavailable",
                    {"node_available": True},
                    {"node_available": False},
                )
            ],
            "evidence": {},
        }

    probe_profile = {
        **actor_profile,
        "physics": dict(physics_profile),
        "geometry": dict(geometry_profile) if geometry_profile else None,
    }
    with tempfile.TemporaryDirectory(prefix="laysh-golden-physics-") as temporary:
        temporary_path = Path(temporary)
        artifact_path = temporary_path / "artifact.html"
        profile_path = temporary_path / "physics-motion.json"
        report_path = temporary_path / "browser-report.json"
        temporary_screens = temporary_path / "screens"
        artifact_path.write_text(artifact, encoding="utf-8")
        profile_path.write_text(json.dumps(probe_profile), encoding="utf-8")
        target_screens = screenshot_root or temporary_screens
        target_screens.mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run(  # noqa: S603 - fixed local probe and disposable files
                [
                    node,
                    str(ROOT / "scripts" / "check_golden.mjs"),
                    str(artifact_path),
                    str(target_screens),
                    golden_id,
                    str(report_path),
                    str(profile_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "check_count": 1,
                "failures": [
                    _failure(
                        "physics_motion_browser_timeout",
                        {"maximum_seconds": 120},
                        {"timed_out": True},
                    )
                ],
                "evidence": {},
            }

    if completed.returncode != 0:
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                _failure(
                    "physics_motion_browser_failed",
                    {"exit_code": 0},
                    {"exit_code": completed.returncode},
                )
            ],
            "evidence": {},
        }
    try:
        evidence = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                _failure(
                    "physics_motion_browser_malformed",
                    {"valid_json": True},
                    {"valid_json": False},
                )
            ],
            "evidence": {},
        }
    actor_samples = evidence.get("actorSamples")
    physics_samples = evidence.get("physicsSamples")
    temporal_runs = evidence.get("temporalRuns")
    if not isinstance(actor_samples, list) or not all(
        isinstance(sample, dict) for sample in actor_samples
    ):
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                _failure(
                    "physics_motion_actor_samples_missing",
                    {"actor_samples": "nonempty_list"},
                    {"actor_samples": actor_samples},
                )
            ],
            "evidence": evidence,
        }
    if not isinstance(physics_samples, list) or not all(
        isinstance(sample, dict) for sample in physics_samples
    ):
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                _failure(
                    "physics_motion_samples_missing",
                    {"physics_samples": "nonempty_list"},
                    {"physics_samples": physics_samples},
                )
            ],
            "evidence": evidence,
        }
    if not isinstance(temporal_runs, list) or not all(
        isinstance(run, dict) for run in temporal_runs
    ):
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                _failure(
                    "physics_motion_temporal_runs_missing",
                    {"temporal_runs": "list"},
                    {"temporal_runs": temporal_runs},
                )
            ],
            "evidence": evidence,
        }

    actor_report = evaluate_actor_trajectory(actor_profile, actor_samples)
    physics_report = evaluate_action_physics(physics_profile, physics_samples, temporal_runs)
    geometry_report = (
        evaluate_body_geometry(evidence.get("geometrySamples", []))
        if geometry_profile
        else {
            "passed": True,
            "check_count": 0,
            "minimum_clearance_px": None,
            "failures": [],
        }
    )
    browser_failures = _browser_failures(evidence)
    return {
        "passed": (
            actor_report["passed"]
            and physics_report["passed"]
            and geometry_report["passed"]
            and not browser_failures
        ),
        "check_count": (
            actor_report["check_count"]
            + physics_report["check_count"]
            + geometry_report["check_count"]
            + 4
        ),
        "minimum_clearance_px": geometry_report["minimum_clearance_px"],
        "failures": [
            *actor_report["failures"],
            *physics_report["failures"],
            *geometry_report["failures"],
            *browser_failures,
        ],
        "evidence": evidence,
    }
