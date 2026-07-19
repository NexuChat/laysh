from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ModuleSecurityError(ValueError):
    """The generated source requests a capability outside the module contract."""


PERMITTED_ABI = ("destroy", "init", "resize", "setParameter", "test", "version")
MAX_SOURCE_BYTES = 96 * 1024
FORBIDDEN_CAPABILITIES = (
    ("html_document", r"<\s*!?doctype\b|<\s*html\b|<\s*/?\s*script\b"),
    ("network_fetch", r"\bfetch\b"),
    ("network_transport", r"\b(?:XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b"),
    ("browser_storage", r"\b(?:localStorage|sessionStorage|indexedDB)\b"),
    (
        "dom_or_navigation",
        r"\b(?:document|parent|top|opener|navigator)\s*\."
        r"|\blocation\s*\.\s*(?:href|assign|replace|reload)\b"
        r"|\b(?:window|globalThis|self)\s*\.\s*"
        r"(?:document|location|parent|top|opener|navigator)\b"
        r"|\b(?:window|globalThis|self)\s*\[\s*['\"]"
        r"(?:document|location|parent|top|opener|navigator)['\"]\s*\]",
    ),
    ("worker", r"\b(?:Worker|SharedWorker)\b"),
    (
        "dynamic_code",
        r"\beval\s*\(|\bnew\s+Function\s*\(|(?<![\w$.])Function\s*\(|\bimport\s*\(",
    ),
    ("sensitive_device", r"\b(?:cookie|clipboard|microphone|camera)\b"),
    ("external_url", r"(?:https?|wss?):\/\/"),
)
FORBIDDEN_PATTERNS = [pattern for _, pattern in FORBIDDEN_CAPABILITIES]
CODE_IDENTIFIER_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")


@dataclass(frozen=True, slots=True)
class VerificationResult:
    passed: bool
    check_count: int
    failures: list[dict[str, Any]]
    artifact: str | None
    node_report: dict[str, Any]


def _source_report(source: str) -> tuple[list[dict[str, Any]], int]:
    failures: list[dict[str, Any]] = []
    encoded_size = len(source.encode("utf-8"))
    if encoded_size > MAX_SOURCE_BYTES:
        failures.append(
            {
                "gate": "source_size",
                "code": "source_too_large",
                "expected": {"maximum_bytes": MAX_SOURCE_BYTES},
                "actual": {"source_size_bytes": encoded_size},
            }
        )
    assignment_count = source.count("window.LayshSimulation")
    if assignment_count != 1:
        failures.append(
            {
                "gate": "interface",
                "code": "simulation_assignment_count",
                "expected": {"window.LayshSimulation_assignments": 1},
                "actual": {"window.LayshSimulation_assignments": assignment_count},
            }
        )
    capabilities = [
        name
        for name, pattern in FORBIDDEN_CAPABILITIES
        if re.search(
            pattern,
            source,
            flags=0 if name == "dynamic_code" else re.IGNORECASE,
        )
    ]
    if capabilities:
        failures.append(
            {
                "gate": "security",
                "code": "forbidden_capability",
                "expected": {"forbidden_capabilities": []},
                "actual": {"capabilities": capabilities},
            }
        )
    return failures, 3


def formula_presentation_report(understanding: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    formula = understanding.get("key_formula")
    if not formula:
        return [], 1
    identifiers = sorted(set(CODE_IDENTIFIER_PATTERN.findall(formula)))
    uses_ascii_hyphen_minus = "-" in formula
    if not identifiers and not uses_ascii_hyphen_minus:
        return [], 1
    code = (
        "code_identifier_in_key_formula"
        if identifiers
        else "ascii_minus_in_key_formula"
    )
    return [
        {
            "gate": "formula_presentation",
            "code": code,
            "expected": {
                "display_math": True,
                "code_identifiers": [],
                "minus_sign": "−",
            },
            "actual": {
                "code_identifiers": identifiers,
                "uses_ascii_hyphen_minus": uses_ascii_hyphen_minus,
            },
        }
    ], 1


def verify_module_source(source: str) -> dict[str, Any]:
    failures, _ = _source_report(source)
    if failures:
        raise ModuleSecurityError(failures[0]["code"])
    return {
        "source_size_bytes": len(source.encode("utf-8")),
        "forbidden_capabilities": 0,
    }


def _run_node_report(source: str, understanding: dict[str, Any]) -> dict[str, Any]:
    verifier = Path(__file__).parents[1] / "scripts" / "verify_module.mjs"
    node = shutil.which("node")
    if node is None:
        return {
            "passed": False,
            "check_count": 0,
            "fixture_count": 0,
            "first_frame": False,
            "failures": [
                {
                    "gate": "syntax_runtime",
                    "code": "node_missing",
                    "expected": {"node_runtime_available": True},
                    "actual": {"node_runtime_available": False},
                }
            ],
        }
    with tempfile.TemporaryDirectory(prefix="laysh-verify-") as temporary:
        temporary_path = Path(temporary)
        source_path = temporary_path / "module.js"
        contract_path = temporary_path / "understanding.json"
        source_path.write_text(source, encoding="utf-8")
        contract_path.write_text(json.dumps(understanding, ensure_ascii=False), encoding="utf-8")
        try:
            completed = subprocess.run(  # noqa: S603 - fixed verifier and disposable inputs
                [node, str(verifier), str(source_path), str(contract_path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "check_count": 0,
                "fixture_count": 0,
                "first_frame": False,
                "failures": [
                    {
                        "gate": "syntax_runtime",
                        "code": "node_verifier_timeout",
                        "expected": {"maximum_seconds": 5},
                        "actual": {"timed_out": True},
                    }
                ],
            }
    if completed.returncode != 0:
        return {
            "passed": False,
            "check_count": 0,
            "fixture_count": 0,
            "first_frame": False,
            "failures": [
                {
                    "gate": "syntax_runtime",
                    "code": "node_verifier_failed",
                    "expected": {"exit_code": 0},
                    "actual": {"exit_code": completed.returncode},
                }
            ],
        }
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "passed": False,
            "check_count": 0,
            "fixture_count": 0,
            "first_frame": False,
            "failures": [
                {
                    "gate": "syntax_runtime",
                    "code": "malformed_verifier_report",
                    "expected": {"valid_json_report": True},
                    "actual": {"valid_json_report": False},
                }
            ],
        }


def verify_module_with_node(source: str, understanding: dict[str, Any]) -> dict[str, Any]:
    verify_module_source(source)
    report = _run_node_report(source, understanding)
    if not report["passed"]:
        raise ValueError("module failed the bounded Node contract check")
    return report


def verify_artifact_contract(
    artifact: str,
    understanding: dict[str, Any],
    module_source: str,
) -> tuple[list[dict[str, Any]], int]:
    from server.assemble import PORTABLE_CSP

    failures: list[dict[str, Any]] = []
    doctype_count = len(re.findall(r"<!doctype\s+html>", artifact, flags=re.IGNORECASE))
    script_count = len(re.findall(r"<script(?:\s|>)", artifact, flags=re.IGNORECASE))
    source_count = artifact.count(module_source)
    if (doctype_count, script_count, source_count) != (1, 4, 1):
        failures.append(
            {
                "gate": "assembly",
                "code": "single_shell_contract_mismatch",
                "expected": {"doctype_count": 1, "script_count": 4, "module_count": 1},
                "actual": {
                    "doctype_count": doctype_count,
                    "script_count": script_count,
                    "module_count": source_count,
                },
            }
        )

    external_urls = re.findall(r"(?:https?|wss?):\/\/[^\s'\"<>]+", artifact)
    csp_present = f'content="{PORTABLE_CSP}"' in artifact
    if not csp_present or external_urls:
        failures.append(
            {
                "gate": "security",
                "code": "portable_artifact_security_mismatch",
                "expected": {"portable_csp": PORTABLE_CSP, "external_urls": []},
                "actual": {
                    "portable_csp_present": csp_present,
                    "external_urls": external_urls,
                },
            }
        )

    pedagogy_ids = {
        "prediction",
        "prediction-choices",
        "primary-control",
        "state-description",
        "explain",
        "explanation-prompt",
        "misconception",
        "reset",
    }
    missing_pedagogy_ids = sorted(
        element_id
        for element_id in pedagogy_ids
        if f'id="{element_id}"' not in artifact
    )
    if missing_pedagogy_ids:
        failures.append(
            {
                "gate": "pedagogy",
                "code": "trusted_teaching_flow_incomplete",
                "expected": {"required_element_ids": sorted(pedagogy_ids)},
                "actual": {"missing_element_ids": missing_pedagogy_ids},
            }
        )

    expected_direction = "rtl" if understanding["lang"] == "ar" else "ltr"
    language_ok = (
        f'<html lang="{understanding["lang"]}" dir="{expected_direction}">' in artifact
    )
    accessible_control = 'label for="primary-control"' in artifact
    live_region = 'aria-live="polite"' in artifact
    reduced_motion = "prefers-reduced-motion" in artifact
    if not all((language_ok, accessible_control, live_region, reduced_motion)):
        failures.append(
            {
                "gate": "language_a11y",
                "code": "language_accessibility_contract_mismatch",
                "expected": {
                    "lang": understanding["lang"],
                    "direction": expected_direction,
                    "labeled_primary_control": True,
                    "polite_live_region": True,
                    "reduced_motion_honored": True,
                },
                "actual": {
                    "language_direction_match": language_ok,
                    "labeled_primary_control": accessible_control,
                    "polite_live_region": live_region,
                    "reduced_motion_honored": reduced_motion,
                },
            }
        )
    return failures, 10


def verify_candidate(
    module_output: dict[str, Any],
    understanding: dict[str, Any],
) -> VerificationResult:
    from server.assemble import assemble_artifact

    source = module_output["module_js"]
    failures, check_count = formula_presentation_report(understanding)
    source_failures, source_checks = _source_report(source)
    failures.extend(source_failures)
    check_count += source_checks
    node_report: dict[str, Any] = {
        "passed": False,
        "check_count": 0,
        "fixture_count": 0,
        "first_frame": False,
        "failures": [],
    }
    if len(source.encode("utf-8")) <= MAX_SOURCE_BYTES:
        node_report = _run_node_report(source, understanding)
        passing_numeric = node_report.get("passing_numeric_fixtures", [])
        passing_by_output: dict[str, list[str]] = {}
        for fixture in passing_numeric:
            passing_by_output.setdefault(fixture["output"], []).append(fixture["fixture_id"])
        for failure in node_report["failures"]:
            if (
                failure.get("code") == "relation_fixture_mismatch"
                and failure.get("expected", {}).get("output") in passing_by_output
            ):
                output = failure["expected"]["output"]
                failure = {
                    **failure,
                    "gate": "fixture_integrity",
                    "code": "suspect_relation_fixture",
                    "numeric_cross_check": {
                        "output": output,
                        "passing_fixture_ids": passing_by_output[output],
                    },
                }
            failures.append(failure)
        check_count += int(node_report["check_count"])

    artifact = None
    if not failures:
        try:
            artifact = assemble_artifact(understanding, module_output)
            check_count += 1
            artifact_failures, artifact_checks = verify_artifact_contract(
                artifact,
                understanding,
                source,
            )
            check_count += artifact_checks
            if artifact_failures:
                failures.extend(artifact_failures)
                artifact = None
        except (OSError, ValueError) as error:
            failures.append(
                {
                    "gate": "assembly",
                    "code": "artifact_assembly_failed",
                    "expected": {"trusted_shell_assembled": True},
                    "actual": {"error_type": type(error).__name__},
                }
            )
            check_count += 1

    return VerificationResult(
        passed=not failures,
        check_count=check_count,
        failures=failures,
        artifact=artifact,
        node_report=node_report,
    )
