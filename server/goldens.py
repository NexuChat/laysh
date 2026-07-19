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
            tolerance = fixture["tolerance"][output]
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


def _normalized_display_formula(value: str | None) -> str:
    if not value:
        return ""
    return "".join(value.replace("؛", ";").replace("،", ";").split())


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
    prediction = understanding.get("prediction") or {}
    learner_strings = [
        understanding.get("title", ""),
        understanding.get("tldr", ""),
        understanding.get("learning_objective", ""),
        (understanding.get("primary_parameter") or {}).get("label", ""),
        prediction.get("prompt", ""),
        *prediction.get("choices", []),
        understanding.get("misconception", ""),
        understanding.get("explanation_prompt", ""),
        understanding.get("transfer_prompt", ""),
    ]
    hash_placeholder = re.compile(r"^[0-9a-f]{24,}$", flags=re.IGNORECASE)
    copy_has_no_hashes = all(
        not hash_placeholder.fullmatch(value.strip())
        for value in learner_strings
        if isinstance(value, str) and value.strip()
    )
    essential_copy = [
        understanding.get("title", ""),
        understanding.get("tldr", ""),
        understanding.get("learning_objective", ""),
        (understanding.get("primary_parameter") or {}).get("label", ""),
        prediction.get("prompt", ""),
        understanding.get("misconception", ""),
        understanding.get("explanation_prompt", ""),
        understanding.get("transfer_prompt", ""),
    ]
    localized_pattern = re.compile(
        r"[\u0600-\u06ff]" if understanding.get("lang") == "ar" else r"[A-Za-z]"
    )
    copy_localized = all(
        isinstance(value, str) and localized_pattern.search(value)
        for value in essential_copy
    )
    parameter_contract = contract["primary_parameter"]
    parameter = understanding.get("primary_parameter") or {}
    parameter_matches = all(
        parameter.get(field) == parameter_contract[field]
        for field in ("id", "min", "max", "default", "step", "unit")
    )
    model_fixture_matches = True
    for reference_fixture in contract["reference_fixtures"]:
        reference_inputs = sorted(reference_fixture["inputs"].items())
        for output, expected in reference_fixture["expected"].items():
            matching = [
                check
                for check in understanding.get("checks", [])
                if check.get("kind") == "numeric"
                and check.get("output") == output
                and sorted(
                    (item["name"], item["value"])
                    for item in check.get("inputs", [])
                )
                == reference_inputs
                and abs(float(check.get("expected", float("inf"))) - float(expected))
                <= 1e-9
                and float(check.get("tolerance", float("inf")))
                <= float(reference_fixture["tolerance"][output])
            ]
            if not matching:
                model_fixture_matches = False
    checks: dict[str, Any] = {
        "formula_matches_reference": _normalized_display_formula(
            understanding.get("key_formula")
        )
        == _normalized_display_formula(contract["formula"]),
        "learner_copy_has_no_hash_placeholders": copy_has_no_hashes,
        "learner_copy_localized": copy_localized,
        "primary_parameter_matches_reference": parameter_matches,
        "model_fixtures_match_reference": model_fixture_matches,
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
    if not checks["learner_copy_has_no_hash_placeholders"]:
        failure_codes.append("learner_copy_placeholder")
    if not checks["learner_copy_localized"]:
        failure_codes.append("learner_copy_not_localized")
    if not checks["primary_parameter_matches_reference"]:
        failure_codes.append("primary_parameter_reference_mismatch")
    if not checks["model_fixtures_match_reference"]:
        failure_codes.append("model_fixture_contract_mismatch")
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
