from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = ROOT / "server" / "fixtures"
GOLDEN_ROOT = ROOT / "out" / "cache" / "golden"
GOLDEN_FIXTURE_IDS = (
    "moon_phases_ar",
    "buoyancy_ar",
    "pendulum_ar",
    "simple_circuit_ar",
    "sound_pitch_ar",
    "day_night_ar",
)


def load_golden_fixtures() -> dict[str, dict[str, Any]]:
    fixtures: dict[str, dict[str, Any]] = {}
    for fixture_id in GOLDEN_FIXTURE_IDS:
        path = FIXTURE_ROOT / f"{fixture_id}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("fixture_id") != fixture_id:
            raise ValueError(f"golden fixture identity mismatch: {fixture_id}")
        fixtures[fixture_id] = document
    return fixtures


def golden_id_for_fixture(fixture_id: str) -> str:
    if fixture_id not in GOLDEN_FIXTURE_IDS:
        raise ValueError("fixture is not in the curated golden allowlist")
    return fixture_id.removesuffix("_ar")


def _reference_understanding(
    understanding: dict[str, Any],
    review_contract: dict[str, Any],
) -> dict[str, Any]:
    reference = deepcopy(understanding)
    checks: list[dict[str, Any]] = []
    outputs: set[str] = set()
    for fixture_index, fixture in enumerate(review_contract["reference_fixtures"], start=1):
        inputs = [
            {"name": name, "value": value}
            for name, value in fixture["inputs"].items()
        ]
        for output, expected in fixture["expected"].items():
            outputs.add(output)
            tolerance = max(0.001, abs(float(expected)) * 0.01)
            checks.append(
                {
                    "id": f"builder_{fixture_index}_{output}",
                    "kind": "numeric",
                    "inputs": inputs,
                    "output": output,
                    "expected": expected,
                    "tolerance": tolerance,
                    "unit": "builder_reference",
                }
            )
    reference["checks"] = checks
    reference["module_spec"] = {"outputs": sorted(outputs)}
    return reference


def review_golden_candidate(
    *,
    fixture: dict[str, Any],
    understanding: dict[str, Any],
    module_output: dict[str, Any],
) -> dict[str, Any]:
    from server.verify import _run_node_report

    contract = fixture["review_contract"]
    reference_understanding = _reference_understanding(understanding, contract)
    report = _run_node_report(module_output["module_js"], reference_understanding)
    metadata = fixture["metadata"]
    teaching_fields = (
        "learning_objective",
        "prediction",
        "misconception",
        "explanation_prompt",
        "transfer_prompt",
    )
    checks: dict[str, Any] = {
        "formula_matches_reference": understanding.get("key_formula") == contract["formula"],
        "bilingual_metadata": all(
            metadata.get(locale, {}).get(field)
            for locale in ("ar", "en")
            for field in ("title", "domain", "summary")
        ),
        "reference_fixture_count": len(contract["reference_fixtures"]),
        "reference_fixtures_passed": bool(report.get("passed")),
        "misconception_present": bool(understanding.get("misconception")),
        "teaching_flow_complete": all(understanding.get(field) for field in teaching_fields),
        "assumptions_present": bool(module_output.get("assumptions")),
        "units_present": bool(contract.get("units")),
    }
    failure_codes: list[str] = []
    if not checks["formula_matches_reference"]:
        failure_codes.append("formula_reference_mismatch")
    if not checks["bilingual_metadata"]:
        failure_codes.append("bilingual_metadata_incomplete")
    if checks["reference_fixture_count"] < 3:
        failure_codes.append("insufficient_builder_reference_fixtures")
    if not checks["reference_fixtures_passed"]:
        failure_codes.append("builder_reference_fixture_failed")
    if not checks["misconception_present"]:
        failure_codes.append("misconception_missing")
    if not checks["teaching_flow_complete"]:
        failure_codes.append("teaching_flow_incomplete")
    if not checks["assumptions_present"]:
        failure_codes.append("assumptions_missing")
    if not checks["units_present"]:
        failure_codes.append("units_missing")
    return {
        "passed": not failure_codes,
        "checks": checks,
        "failure_codes": failure_codes,
        "reference_report": {
            "passed": bool(report.get("passed")),
            "check_count": int(report.get("check_count", 0)),
            "fixture_count": int(report.get("fixture_count", 0)),
            "failures": report.get("failures", []),
        },
    }


def load_pinned_golden(
    golden_id: str,
    *,
    root: Path = GOLDEN_ROOT,
) -> dict[str, Any] | None:
    if not re.fullmatch(r"[a-z0-9_]+", golden_id):
        return None
    path = root / f"{golden_id}.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        receipt = document["receipt"]
        artifact = document["artifact"]
        valid = (
            document["golden_id"] == golden_id
            and document["pinned"] is True
            and document["tier"] == "A"
            and receipt["deterministic_passed"] is True
            and receipt["browser_passed"] is True
            and receipt["failed_gate_count"] == 0
            and receipt["check_count"] > 0
            and hashlib.sha256(artifact.encode()).hexdigest()
            == document["artifact_sha256"]
        )
    except (KeyError, OSError, TypeError, json.JSONDecodeError):
        return None
    return document if valid else None


def list_pinned_goldens(*, root: Path = GOLDEN_ROOT) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        if path.name == "manifest.json":
            continue
        document = load_pinned_golden(path.stem, root=root)
        if document is not None:
            documents.append(document)
    return documents
