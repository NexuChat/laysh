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
MOON_CORRECTION = (
    "تصحيح: أطوار القمر تنتج من زاوية الشمس والأرض والقمر، لا من ظل الأرض."
)
BUOYANCY_CORRECTION = "تصحيح: الطفو يعتمد على كثافة الجسم مقارنة بالسائل، لا على خفته المطلقة."
PENDULUM_CORRECTION = "تصحيح: زيادة طول البندول تزيد زمن دورته، لا تجعله أسرع."
CIRCUIT_CORRECTION = "تصحيح: زيادة المقاومة تخفّض التيار عند ثبات الجهد، لا تزيده."
SOUND_CORRECTION = "تصحيح: التردد يحدد الحدة، لا شدة الصوت بالضرورة."
DAY_NIGHT_CORRECTION = (
    "تصحيح: الليل يحدث لأن موقعك يدور بعيدًا عن ضوء الشمس، "
    "لا لأن الشمس تنطفئ أو يحجبها القمر."
)
MISCONCEPTION_CORRECTIONS = {
    "أطوار القمر سببها ظل الأرض": MOON_CORRECTION,
    (
        "ليست أطوار القمر ناتجة عن ظل الأرض؛ بل تنتج عن تغير الجزء المضاء "
        "الذي نراه مع تغير مواضع الشمس والأرض والقمر."
    ): MOON_CORRECTION,
    "الطفو يعتمد على خفة الجسم المطلقة لا على كثافته مقارنة بالسائل": BUOYANCY_CORRECTION,
    "زيادة طول البندول تجعله أسرع": PENDULUM_CORRECTION,
    "زيادة طول البندول تجعله أسرع.": PENDULUM_CORRECTION,
    "زيادة المقاومة تسمح بمرور تيار أكبر": CIRCUIT_CORRECTION,
    "زيادة المقاومة تسمح بمرور تيار أكبر.": CIRCUIT_CORRECTION,
    "الصوت الأعلى ترددًا هو بالضرورة أعلى شدة": SOUND_CORRECTION,
    "الصوت الأعلى ترددًا هو بالضرورة أعلى شدة.": SOUND_CORRECTION,
    "الليل يحدث لأن الشمس تنطفئ أو تختفي خلف القمر": DAY_NIGHT_CORRECTION,
}


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
    reference["module_spec"] = {
        **reference["module_spec"],
        "outputs": sorted(outputs),
    }
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
    from server.schemas import has_explicit_misconception_correction
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
    module_spec = understanding.get("module_spec") or {}
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
        "actor_action_matches_reference": (
            module_spec.get("actor") == contract.get("actor")
            and module_spec.get("action") == contract.get("action")
        ),
        "model_fixtures_match_reference": model_fixture_matches,
        "bilingual_metadata": all(
            metadata.get(locale, {}).get(field)
            for locale in ("ar", "en")
            for field in ("title", "domain", "summary")
        ),
        "reference_fixture_count": len(contract["reference_fixtures"]),
        "reference_fixtures_passed": bool(report.get("passed")),
        "misconception_present": bool(understanding.get("misconception")),
        "misconception_explicitly_corrected": bool(understanding.get("misconception"))
        and has_explicit_misconception_correction(
            understanding["lang"], understanding["misconception"]
        ),
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
    if not checks["actor_action_matches_reference"]:
        failure_codes.append("actor_action_reference_mismatch")
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
    if not checks["misconception_explicitly_corrected"]:
        failure_codes.append("misconception_not_corrected")
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


def _artifact_lesson_and_module(artifact: str) -> tuple[dict[str, Any], str]:
    scripts = re.findall(r"<script>(.*?)</script>", artifact, flags=re.DOTALL)
    if len(scripts) != 4:
        raise ValueError("pinned artifact does not have the trusted four-script shell")
    prefix = "window.__LAYSH_LESSON__ = "
    lesson_script = scripts[0]
    if not lesson_script.startswith(prefix) or not lesson_script.endswith(";"):
        raise ValueError("pinned artifact has an invalid lesson payload")
    try:
        lesson = json.loads(lesson_script.removeprefix(prefix)[:-1])
    except json.JSONDecodeError as error:
        raise ValueError("pinned artifact has malformed lesson JSON") from error
    return lesson, scripts[2]


def refresh_pinned_golden_teaching_shells(
    *,
    root: Path = GOLDEN_ROOT,
    browser_verifier: Any | None = None,
) -> list[dict[str, Any]]:
    """Reassemble the six pinned lessons after a trusted teaching-shell revision."""
    from server.browser_verify import verify_artifact_in_browser
    from server.schemas import has_explicit_misconception_correction
    from server.verify import verify_candidate

    verify_browser = browser_verifier or verify_artifact_in_browser
    fixtures = load_golden_fixtures()
    refreshed_documents: list[tuple[Path, dict[str, Any]]] = []
    reports: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        if path.name == "manifest.json":
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        lesson, module_js = _artifact_lesson_and_module(document["artifact"])
        misconception = lesson.get("misconception")
        if not isinstance(misconception, str):
            raise ValueError("pinned lesson has no approved misconception correction")
        if not has_explicit_misconception_correction(lesson["lang"], misconception):
            corrected = MISCONCEPTION_CORRECTIONS.get(misconception)
            if corrected is None:
                raise ValueError("pinned lesson has no approved misconception correction")
            lesson["misconception"] = corrected
        fixture_id = f'{document["golden_id"]}_ar'
        fixture = fixtures.get(fixture_id)
        if fixture is None:
            raise ValueError("pinned lesson is not in the curated fixture allowlist")
        lesson["module_spec"] = {
            **lesson["module_spec"],
            "actor": lesson["module_spec"].get("actor", fixture["review_contract"]["actor"]),
            "action": lesson["module_spec"].get("action", fixture["review_contract"]["action"]),
        }
        module_output = {
            "module_js": module_js,
            "output_names": lesson["module_spec"]["outputs"],
            "brief_summary": "offline trusted-shell refresh",
            "assumptions": fixture["review_contract"]["assumptions"],
        }
        candidate = verify_candidate(module_output, lesson)
        if not candidate.passed or candidate.artifact is None:
            raise ValueError("pinned lesson failed deterministic refresh verification")
        automated_review = review_golden_candidate(
            fixture=fixture,
            understanding=lesson,
            module_output=module_output,
        )
        if not automated_review["passed"]:
            raise ValueError("pinned lesson failed curated refresh review")
        browser = verify_browser(candidate.artifact)
        if not browser.passed:
            raise ValueError("pinned lesson failed browser refresh verification")
        document["artifact"] = candidate.artifact
        document["artifact_sha256"] = hashlib.sha256(candidate.artifact.encode()).hexdigest()
        document["receipt"]["check_count"] = candidate.check_count + browser.check_count
        document["review"] = {
            **document["review"],
            "automated": automated_review,
            "reference_contract": fixture["review_contract"],
        }
        document["evidence"] = {
            **document.get("evidence", {}),
            "teaching_shell_refresh": {
                "deterministic_check_count": candidate.check_count,
                "browser_check_count": browser.check_count,
            },
        }
        refreshed_documents.append((path, document))
        reports.append(
            {
                "golden_id": document["golden_id"],
                "artifact_sha256": document["artifact_sha256"],
                "shell_refreshed": True,
            }
        )
    manifest = {
        "schema_version": "1.0",
        "contract_version": "1.0",
        "lessons": [
            {
                "id": document["golden_id"],
                "aliases": document["aliases"],
                "instant": True,
                "tier": "A",
                "artifact_sha256": document["artifact_sha256"],
                "metadata": document["metadata"],
            }
            for _, document in refreshed_documents
        ],
    }
    pending_writes = [
        (path, json.dumps(document, ensure_ascii=False, separators=(",", ":")))
        for path, document in refreshed_documents
    ]
    pending_writes.append(
        (root / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    )
    temporary_paths: list[tuple[Path, Path]] = []
    for path, content in pending_writes:
        temporary = path.with_suffix(path.suffix + ".refresh.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary_paths.append((temporary, path))
    for temporary, path in temporary_paths:
        temporary.replace(path)
    return reports
