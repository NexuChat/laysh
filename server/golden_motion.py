from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from server.motion import evaluate_actor_trajectory

ROOT = Path(__file__).parents[1]


def _failure(code: str, expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    return {
        "gate": "actor_motion_browser",
        "code": code,
        "expected": expected,
        "actual": actual,
    }


def verify_golden_actor_motion(
    *,
    artifact: str,
    golden_id: str,
    profile: Mapping[str, object],
    screenshot_root: Path | None = None,
) -> dict[str, Any]:
    """Run the actor-only browser probe for a trusted pinned artifact.

    The browser probe produces actor-region observations; this function decides
    the gate locally without treating canvas-wide changes or frame counts as
    proof of the scientific action.
    """

    node = shutil.which("node")
    if node is None:
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                _failure(
                    "actor_motion_browser_unavailable",
                    {"node_available": True},
                    {"node_available": False},
                )
            ],
            "evidence": {},
        }
    with tempfile.TemporaryDirectory(prefix="laysh-golden-motion-") as temporary:
        temporary_path = Path(temporary)
        artifact_path = temporary_path / "artifact.html"
        profile_path = temporary_path / "actor-tracking.json"
        report_path = temporary_path / "browser-report.json"
        temporary_screens = temporary_path / "screens"
        artifact_path.write_text(artifact, encoding="utf-8")
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
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
                timeout=45,
            )
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "check_count": 1,
                "failures": [
                    _failure(
                        "actor_motion_browser_timeout",
                        {"maximum_seconds": 45},
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
                    "actor_motion_browser_failed",
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
                    "actor_motion_browser_malformed",
                    {"valid_json": True},
                    {"valid_json": False},
                )
            ],
            "evidence": {},
        }
    samples = evidence.get("actorSamples")
    if not isinstance(samples, list) or not all(isinstance(sample, dict) for sample in samples):
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                _failure(
                    "actor_motion_samples_missing",
                    {"actor_samples": "nonempty_list"},
                    {"actor_samples": samples},
                )
            ],
            "evidence": evidence,
        }
    tracking = evaluate_actor_trajectory(profile, samples)
    browser_checks = (
        (bool(evidence.get("ready")), "actor_motion_not_ready", {"ready": True}),
        (
            not bool(evidence.get("runtimeError")),
            "actor_motion_runtime_error",
            {"runtime_error": False},
        ),
        (
            evidence.get("externalRequests") == 0,
            "actor_motion_external_request",
            {"external_requests": 0},
        ),
        (
            evidence.get("consoleErrors") == [],
            "actor_motion_console_error",
            {"console_errors": []},
        ),
    )
    browser_failures = [
        _failure(code, expected, {key: evidence.get(key) for key in expected})
        for passed, code, expected in browser_checks
        if not passed
    ]
    return {
        "passed": tracking["passed"] and not browser_failures,
        "check_count": tracking["check_count"] + len(browser_checks),
        "failures": [*tracking["failures"], *browser_failures],
        "evidence": evidence,
    }
