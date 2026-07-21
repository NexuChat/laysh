from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
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


def verify_golden_physics_motion(
    *,
    artifact: str,
    golden_id: str,
    actor_profile: Mapping[str, object],
    physics_profile: Mapping[str, object],
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

    probe_profile = {**actor_profile, "physics": dict(physics_profile)}
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
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "check_count": 1,
                "failures": [
                    _failure(
                        "physics_motion_browser_timeout",
                        {"maximum_seconds": 60},
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
    browser_failures = _browser_failures(evidence)
    return {
        "passed": actor_report["passed"] and physics_report["passed"] and not browser_failures,
        "check_count": (
            actor_report["check_count"] + physics_report["check_count"] + 4
        ),
        "failures": [
            *actor_report["failures"],
            *physics_report["failures"],
            *browser_failures,
        ],
        "evidence": evidence,
    }
