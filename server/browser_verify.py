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


def _gate_failure(
    gate: str,
    code: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> dict[str, Any]:
    return {
        "gate": gate,
        "code": code,
        "expected": expected,
        "actual": actual,
    }


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _evaluate_representation_consistency(
    evidence: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    report = evidence.get("representationConsistency")
    if not isinstance(report, dict) or report.get("required") is not True:
        return [], 0

    failures: list[dict[str, Any]] = []
    check_count = 0
    graph = report.get("graph")
    if isinstance(graph, dict) and graph.get("required") is True:
        check_count += 1
        samples = graph.get("samples")
        usable_samples = (
            samples
            if isinstance(samples, list)
            else []
        )
        mismatches = [
            {
                "input": sample.get("input"),
                "expected_output": sample.get("expectedOutput"),
                "plotted_output": sample.get("plottedOutput"),
                "tolerance": sample.get("tolerance"),
            }
            for sample in usable_samples
            if not (
                isinstance(sample, dict)
                and _finite_number(sample.get("expectedOutput"))
                and _finite_number(sample.get("plottedOutput"))
                and _finite_number(sample.get("tolerance"))
                and sample["tolerance"] >= 0
                and abs(sample["expectedOutput"] - sample["plottedOutput"])
                <= sample["tolerance"]
            )
        ]
        if len(usable_samples) != 5 or mismatches:
            failures.append(
                _gate_failure(
                    "graph_consistency",
                    "graph_physics_mismatch",
                    {
                        "sample_count": 5,
                        "plotted_values_match_module_test": True,
                    },
                    {
                        "sample_count": len(usable_samples),
                        "mismatches": mismatches,
                    },
                )
            )

        check_count += 1
        markers = graph.get("markers")
        usable_markers = markers if isinstance(markers, list) else []
        marker_mismatches = [
            {
                "control_value": marker.get("controlValue"),
                "expected_x": marker.get("expectedX"),
                "observed_x": marker.get("observedX"),
                "tolerance": marker.get("tolerance"),
            }
            for marker in usable_markers
            if not (
                isinstance(marker, dict)
                and _finite_number(marker.get("controlValue"))
                and _finite_number(marker.get("expectedX"))
                and _finite_number(marker.get("observedX"))
                and _finite_number(marker.get("tolerance"))
                and marker["tolerance"] >= 0
                and abs(marker["expectedX"] - marker["observedX"])
                <= marker["tolerance"]
            )
        ]
        observed_positions = {
            round(float(marker["observedX"]), 6)
            for marker in usable_markers
            if isinstance(marker, dict) and _finite_number(marker.get("observedX"))
        }
        if (
            len(usable_markers) != 3
            or len(observed_positions) < 3
            or marker_mismatches
        ):
            failures.append(
                _gate_failure(
                    "graph_consistency",
                    "graph_marker_mismatch",
                    {
                        "control_samples": 3,
                        "distinct_marker_positions": 3,
                        "marker_tracks_control": True,
                    },
                    {
                        "control_samples": len(usable_markers),
                        "distinct_marker_positions": len(observed_positions),
                        "mismatches": marker_mismatches,
                    },
                )
            )

    archetype = report.get("archetype")
    if not isinstance(archetype, dict) or archetype.get("required") is not True:
        return failures, check_count
    check_count += 1
    declared = archetype.get("declared") if isinstance(archetype, dict) else None
    paired_archetypes = {"orbital_pair", "linked_bodies", "surface_and_body"}
    minimum_actor_count = 2 if declared in paired_archetypes else 1
    scientific_count = (
        archetype.get("scientificActorCount") if isinstance(archetype, dict) else None
    )
    visible_count = (
        archetype.get("visibleActorCount") if isinstance(archetype, dict) else None
    )
    matching_count = (
        archetype.get("matchingPrimitiveCount")
        if isinstance(archetype, dict)
        else None
    )
    archetype_matches = (
        isinstance(declared, str)
        and _finite_number(scientific_count)
        and _finite_number(visible_count)
        and _finite_number(matching_count)
        and scientific_count >= minimum_actor_count
        and visible_count >= minimum_actor_count
        and matching_count >= minimum_actor_count
    )
    if not archetype_matches:
        failures.append(
            _gate_failure(
                "representation_consistency",
                "archetype_render_mismatch",
                {
                    "declared_archetype_rendered": True,
                    "minimum_visible_scientific_actors": minimum_actor_count,
                },
                {
                    "declared": declared,
                    "scientific_actor_count": scientific_count,
                    "visible_actor_count": visible_count,
                    "matching_primitive_count": matching_count,
                },
            )
        )
    return failures, check_count


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
    representation_failures, representation_check_count = (
        _evaluate_representation_consistency(evidence)
    )
    failures.extend(representation_failures)
    check_count += representation_check_count
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
