from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]


@dataclass(frozen=True, slots=True)
class BrowserVerificationResult:
    passed: bool
    check_count: int
    failures: list[dict[str, Any]]
    evidence: dict[str, Any]

    @classmethod
    def passing(cls) -> BrowserVerificationResult:
        return cls(
            passed=True,
            check_count=6,
            failures=[],
            evidence={
                "ready": True,
                "controlChanged": True,
                "frameChanged": True,
                "canvasHashBefore": 1234,
                "canvasHashAfter": 5678,
                "runtimeError": False,
                "externalRequests": 0,
            },
        )


def _failure(code: str, expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    return {
        "gate": "browser_readiness",
        "code": code,
        "expected": expected,
        "actual": actual,
    }


def _evaluate(evidence: dict[str, Any]) -> BrowserVerificationResult:
    failures = []
    checks = (
        (
            bool(evidence.get("ready")),
            "first_frame_missing",
            {"first_frame_ready": True},
            {"first_frame_ready": bool(evidence.get("ready"))},
        ),
        (
            bool(evidence.get("controlChanged")),
            "primary_control_unchanged",
            {"control_changed": True},
            {"control_changed": bool(evidence.get("controlChanged"))},
        ),
        (
            bool(evidence.get("frameChanged")),
            "visible_frame_unchanged",
            {"frame_changed": True},
            {"frame_changed": bool(evidence.get("frameChanged"))},
        ),
        (
            isinstance(evidence.get("canvasHashBefore"), int)
            and isinstance(evidence.get("canvasHashAfter"), int)
            and evidence.get("canvasHashBefore") != evidence.get("canvasHashAfter"),
            "canvas_pixels_unchanged",
            {"canvas_pixels_changed": True},
            {
                "canvas_hash_before": evidence.get("canvasHashBefore"),
                "canvas_hash_after": evidence.get("canvasHashAfter"),
            },
        ),
        (
            not bool(evidence.get("runtimeError")),
            "runtime_error_beacon",
            {"runtime_error": False},
            {"runtime_error": bool(evidence.get("runtimeError"))},
        ),
        (
            evidence.get("externalRequests") == 0,
            "external_request_observed",
            {"external_requests": 0},
            {"external_requests": evidence.get("externalRequests")},
        ),
    )
    for passed, code, expected, actual in checks:
        if not passed:
            failures.append(_failure(code, expected, actual))
    check_count = len(checks)
    causal = evidence.get("causalResponse")
    if isinstance(causal, dict) and causal.get("required") is True:
        report = causal.get("report")
        if not isinstance(report, dict):
            check_count += 1
            failures.append(
                {
                    "gate": "causal_response",
                    "code": "causal_report_missing",
                    "expected": {"trusted_causal_report": True},
                    "actual": {"trusted_causal_report": False},
                }
            )
        else:
            report_check_count = report.get("checkCount")
            if isinstance(report_check_count, int) and 0 < report_check_count <= 32:
                check_count += report_check_count
            else:
                check_count += 1
                failures.append(
                    {
                        "gate": "causal_response",
                        "code": "causal_report_malformed",
                        "expected": {"bounded_check_count": True},
                        "actual": {"bounded_check_count": False},
                    }
                )
            report_failures = report.get("failures")
            if isinstance(report_failures, list) and all(
                isinstance(item, dict)
                and item.get("gate") == "causal_response"
                and isinstance(item.get("code"), str)
                and item["code"].startswith("causal_")
                and isinstance(item.get("expected"), dict)
                and isinstance(item.get("actual"), dict)
                for item in report_failures
            ):
                failures.extend(report_failures)
            else:
                failures.append(
                    {
                        "gate": "causal_response",
                        "code": "causal_report_malformed",
                        "expected": {"structured_failures": True},
                        "actual": {"structured_failures": False},
                    }
                )
    return BrowserVerificationResult(
        passed=not failures,
        check_count=check_count,
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
    return _evaluate(evidence)
