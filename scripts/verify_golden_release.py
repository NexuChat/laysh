from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from server.goldens import (
    GOLDEN_ROOT,
    _artifact_lesson_and_module,
    load_golden_fixtures,
    load_pinned_golden,
    localized_pinned_golden,
)
from server.schemas import has_explicit_misconception_correction

ROOT = Path(__file__).parents[1]
EVIDENCE_ROOT = ROOT / "out" / "evidence"
EXPECTED_LOCALES = {"ar": "rtl", "en": "ltr"}
REQUIRED_BROWSER_CHECKS = {
    "actor_visible",
    "primary_control_reachable",
    "pause_stops_motion",
    "resume_restarts_motion",
    "reset_restores_default",
    "reduced_motion_stops_automatic_motion",
    "state_alternative_present",
    "keyboard_controls_named",
    "no_duplicate_ids",
    "no_horizontal_clip",
}
REQUIRED_RESPONSIVE_CASES = {
    "mobile-320x844",
    "mobile-390x844",
    "desktop-1440x900",
    "zoom-200",
}
REQUIRED_BUILDER_CHECKS = {
    "answer_correct",
    "assumptions_honest",
    "formula_display_grade",
    "units_correct",
    "fixtures_correct",
    "misconception_addressed",
    "teaching_flow_clear",
    "visual_model_unambiguous",
    "min_default_max_tested",
    "arabic_metadata_reviewed",
    "english_metadata_reviewed",
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _read_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"expected an object in {path}")
    return document


def _by_golden(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    reports = report.get("goldens")
    if not isinstance(reports, list):
        return {}
    return {
        item["golden_id"]: item
        for item in reports
        if isinstance(item, dict) and isinstance(item.get("golden_id"), str)
    }


def _browser_by_identity(
    report: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    journeys = report.get("journeys")
    if not isinstance(journeys, list):
        return {}
    return {
        (item["golden_id"], item["locale"]): item
        for item in journeys
        if isinstance(item, dict)
        and isinstance(item.get("golden_id"), str)
        and isinstance(item.get("locale"), str)
    }


def _failure(code: str, *, expected: Any, actual: Any) -> dict[str, Any]:
    return {"code": code, "expected": expected, "actual": actual}


def _browser_journey_passes(journey: dict[str, Any]) -> bool:
    checks = journey.get("checks")
    responsive = journey.get("responsive")
    a11y = journey.get("a11y")
    if not isinstance(checks, dict) or not isinstance(responsive, list):
        return False
    responsive_by_name = {
        item.get("name"): item
        for item in responsive
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    screenshots = journey.get("screenshots")
    screenshot_hashes = journey.get("screenshot_sha256")
    screenshot_contract_passed = bool(
        isinstance(screenshots, list)
        and len(screenshots) == 2
        and all(isinstance(path, str) and path for path in screenshots)
        and len(set(screenshots)) == 2
        and isinstance(screenshot_hashes, dict)
        and set(screenshot_hashes) == set(screenshots)
        and all(
            isinstance(value, str) and SHA256_PATTERN.fullmatch(value)
            for value in screenshot_hashes.values()
        )
    )
    return bool(
        journey.get("passed") is True
        and all(checks.get(name) is True for name in REQUIRED_BROWSER_CHECKS)
        and set(responsive_by_name) == REQUIRED_RESPONSIVE_CASES
        and all(item.get("passed") is True for item in responsive_by_name.values())
        and isinstance(a11y, dict)
        and a11y.get("unnamed_interactive_nodes") == 0
        and a11y.get("duplicate_ids") == []
        and a11y.get("state_alternative_present") is True
        and journey.get("console_errors") == []
        and journey.get("external_requests") == 0
        and screenshot_contract_passed
    )


def _resolved_screenshot(path_text: str, *, root: Path) -> Path | None:
    root = root.resolve()
    source = Path(path_text)
    candidate = source.resolve() if source.is_absolute() else (root / source).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _screenshot_records(
    journey: dict[str, Any],
    *,
    root: Path,
    failures: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    screenshots = journey.get("screenshots")
    expected_hashes = journey.get("screenshot_sha256")
    if (
        not isinstance(screenshots, list)
        or len(screenshots) != 2
        or len({item for item in screenshots if isinstance(item, str)}) != 2
        or not all(isinstance(item, str) and item for item in screenshots)
        or not isinstance(expected_hashes, dict)
        or set(expected_hashes) != set(screenshots)
        or not all(
            isinstance(value, str) and SHA256_PATTERN.fullmatch(value)
            for value in expected_hashes.values()
        )
    ):
        failures.append(
            _failure(
                "screenshot_hash_binding_invalid",
                expected={"screenshots": 2, "unique": True, "sha256_bound": True},
                actual={
                    "screenshots": screenshots,
                    "screenshot_sha256": expected_hashes,
                },
            )
        )
        return [], False

    records: list[dict[str, Any]] = []
    passed = True
    for path_text in screenshots:
        path = _resolved_screenshot(path_text, root=root)
        expected_hash = expected_hashes[path_text]
        if path is None:
            passed = False
            failures.append(
                _failure(
                    "screenshot_path_outside_evidence_root",
                    expected={"inside_root": str(root.resolve())},
                    actual={"path": path_text},
                )
            )
            continue
        if not path.is_file():
            passed = False
            failures.append(
                _failure(
                    "screenshot_missing",
                    expected={"path": path_text, "exists": True},
                    actual={"exists": False},
                )
            )
            records.append(
                {
                    "path": path_text,
                    "sha256": None,
                    "expected_sha256": expected_hash,
                    "passed": False,
                }
            )
            continue
        actual_hash = _sha256_bytes(path.read_bytes())
        hash_matches = actual_hash == expected_hash
        if not hash_matches:
            passed = False
            failures.append(
                _failure(
                    "screenshot_hash_mismatch",
                    expected={"path": path_text, "sha256": expected_hash},
                    actual={"sha256": actual_hash},
                )
            )
        records.append(
            {
                "path": path_text,
                "sha256": actual_hash,
                "expected_sha256": expected_hash,
                "passed": hash_matches,
            }
        )
    return records, passed


def _bind_browser_screenshot_hashes(
    browser_evidence: dict[str, Any], *, root: Path
) -> dict[str, Any]:
    journeys = browser_evidence.get("journeys")
    if not isinstance(journeys, list):
        raise ValueError("browser evidence has no journeys to bind")
    bound_journeys: list[dict[str, Any]] = []
    for journey in journeys:
        if not isinstance(journey, dict) or not isinstance(journey.get("screenshots"), list):
            raise ValueError("browser journey has no screenshots to bind")
        screenshot_hashes: dict[str, str] = {}
        for path_text in journey["screenshots"]:
            if not isinstance(path_text, str):
                raise ValueError("browser screenshot path is invalid")
            path = _resolved_screenshot(path_text, root=root)
            if path is None or not path.is_file():
                raise ValueError("browser screenshot is unavailable for hash binding")
            screenshot_hashes[path_text] = _sha256_bytes(path.read_bytes())
        bound_journeys.append({**journey, "screenshot_sha256": screenshot_hashes})
    return {**browser_evidence, "journeys": bound_journeys}


def _motion_slice(
    report_by_id: dict[str, dict[str, Any]],
    golden_id: str,
    artifact_hash: str,
    *,
    bind_artifact: bool,
    source_hash: str | None = None,
) -> tuple[dict[str, Any], bool]:
    item = report_by_id.get(golden_id)
    if item is None:
        return {"passed": False, "failures": [{"code": "missing_motion_report"}]}, False
    hash_matches = True
    if bind_artifact:
        hash_matches = item.get("artifact_sha256") == artifact_hash
    elif source_hash is not None:
        hash_matches = item.get("source_sha256") == source_hash
    return {
        "passed": bool(item.get("passed") is True and hash_matches),
        "check_count": int(item.get("check_count", 0)),
        "artifact_or_source_hash_matches": hash_matches,
        "failures": item.get("failures", []),
    }, bool(item.get("passed") is True and hash_matches)


def _fresh_content_checks(
    lesson: dict[str, Any], fixture: dict[str, Any]
) -> dict[str, bool]:
    contract = fixture["review_contract"]
    parameter = lesson.get("primary_parameter") or {}
    module_spec = lesson.get("module_spec") or {}
    metadata = fixture.get("metadata") or {}
    teaching_fields = (
        "learning_objective",
        "prediction",
        "misconception",
        "explanation_prompt",
        "transfer_prompt",
    )
    formula = "".join(
        str(lesson.get("key_formula") or "").replace("؛", ";").replace("،", ";").split()
    )
    reference_formula = "".join(
        str(contract.get("formula") or "").replace("؛", ";").replace("،", ";").split()
    )
    reference_checks_match = True
    for reference_fixture in contract.get("reference_fixtures", []):
        expected_inputs = sorted(reference_fixture.get("inputs", {}).items())
        for output, expected in reference_fixture.get("expected", {}).items():
            matching = [
                check
                for check in lesson.get("checks", [])
                if check.get("kind") == "numeric"
                and check.get("output") == output
                and sorted(
                    (item.get("name"), item.get("value"))
                    for item in check.get("inputs", [])
                )
                == expected_inputs
                and abs(float(check.get("expected", float("inf"))) - float(expected))
                <= 1e-9
                and float(check.get("tolerance", float("inf")))
                <= float(reference_fixture["tolerance"][output])
            ]
            if not matching:
                reference_checks_match = False
    misconception = lesson.get("misconception")
    return {
        "formula_matches_reference": formula == reference_formula,
        "primary_parameter_matches_reference": all(
            parameter.get(field) == contract["primary_parameter"].get(field)
            for field in ("id", "min", "max", "default", "step", "unit")
        ),
        "actor_action_matches_reference": (
            module_spec.get("actor") == contract.get("actor")
            and module_spec.get("action") == contract.get("action")
        ),
        "reference_checks_match": reference_checks_match,
        "reference_fixture_count": len(contract.get("reference_fixtures", [])) >= 3,
        "bilingual_metadata": all(
            metadata.get(locale, {}).get(field)
            for locale in EXPECTED_LOCALES
            for field in ("title", "domain", "summary")
        ),
        "misconception_explicitly_corrected": bool(
            isinstance(misconception, str)
            and has_explicit_misconception_correction(lesson.get("lang"), misconception)
        ),
        "teaching_flow_complete": all(lesson.get(field) for field in teaching_fields),
        "units_present": bool(contract.get("units")),
        "assumptions_present": bool(contract.get("assumptions")),
    }


def _current_shell_artifact(
    document: dict[str, Any], _fixture: dict[str, Any], locale: str
) -> str:
    return localized_pinned_golden(document, locale)["artifact"]


def write_current_shell_review_artifacts(destination: Path) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    fixtures = load_golden_fixtures()
    artifacts: list[dict[str, str]] = []
    for fixture_id, fixture in sorted(fixtures.items()):
        golden_id = fixture_id.removesuffix("_ar")
        document = load_pinned_golden(golden_id)
        if document is None:
            raise ValueError(f"pinned golden unavailable: {golden_id}")
        for locale in EXPECTED_LOCALES:
            artifact = _current_shell_artifact(document, fixture, locale)
            filename = f"{golden_id}-{locale}.html"
            (destination / filename).write_text(artifact, encoding="utf-8")
            artifacts.append(
                {
                    "golden_id": golden_id,
                    "locale": locale,
                    "filename": filename,
                    "artifact_sha256": _sha256_text(artifact),
                    "source_artifact_sha256": _sha256_text(
                        localized_pinned_golden(document, locale)["artifact"]
                    ),
                }
            )
    manifest = {
        "schema_version": "1.0",
        "model_calls": 0,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def build_report(
    *,
    browser_evidence: dict[str, Any],
    actor_motion: dict[str, Any] | None = None,
    physics_motion: dict[str, Any] | None = None,
    shared_state: dict[str, Any] | None = None,
    manifest_hash_overrides: dict[str, str] | None = None,
    golden_root: Path = GOLDEN_ROOT,
    screenshot_root: Path = ROOT,
) -> dict[str, Any]:
    actor_motion = actor_motion or _read_json(EVIDENCE_ROOT / "motion-02.json")
    physics_motion = physics_motion or _read_json(EVIDENCE_ROOT / "motion-03.json")
    shared_state = shared_state or _read_json(EVIDENCE_ROOT / "motion-04.json")
    manifest_path = golden_root / "manifest.json"
    manifest = _read_json(manifest_path)
    fixtures = load_golden_fixtures()
    expected_ids = {fixture_id.removesuffix("_ar") for fixture_id in fixtures}
    manifest_lessons = manifest.get("lessons")
    if not isinstance(manifest_lessons, list):
        manifest_lessons = []
    manifest_by_id = {
        item["id"]: item
        for item in manifest_lessons
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    overrides = manifest_hash_overrides or {}
    for golden_id, value in overrides.items():
        if golden_id in manifest_by_id:
            manifest_by_id[golden_id] = {
                **manifest_by_id[golden_id],
                "artifact_sha256": value,
            }

    actor_by_id = _by_golden(actor_motion)
    physics_by_id = _by_golden(physics_motion)
    shared_by_id = _by_golden(shared_state)
    browser_by_identity = _browser_by_identity(browser_evidence)
    reports: list[dict[str, Any]] = []
    screenshot_paths: set[str] = set()

    for golden_id in sorted(expected_ids):
        fixture = fixtures[f"{golden_id}_ar"]
        path = golden_root / f"{golden_id}.json"
        document = load_pinned_golden(golden_id, root=golden_root)
        failures: list[dict[str, Any]] = []
        if document is None:
            reports.append(
                {
                    "golden_id": golden_id,
                    "passed": False,
                    "failures": [
                        _failure(
                            "pinned_golden_unavailable",
                            expected=True,
                            actual=False,
                        )
                    ],
                }
            )
            continue

        artifact = document["artifact"]
        artifact_hash = _sha256_text(artifact)
        document_hash = _sha256_bytes(path.read_bytes())
        manifest_item = manifest_by_id.get(golden_id, {})
        manifest_hash_matches = manifest_item.get("artifact_sha256") == artifact_hash
        if not manifest_hash_matches:
            failures.append(
                _failure(
                    "manifest_artifact_hash_mismatch",
                    expected=artifact_hash,
                    actual=manifest_item.get("artifact_sha256"),
                )
            )

        lesson, module_source = _artifact_lesson_and_module(artifact)
        automated_review = document.get("review", {}).get("automated", {})
        content_checks = _fresh_content_checks(lesson, fixture)
        builder_review = document.get("review", {}).get("builder", {})
        builder_passed = bool(
            isinstance(builder_review, dict)
            and builder_review.get("verdict") == "pass"
            and all(builder_review.get(name) is True for name in REQUIRED_BUILDER_CHECKS)
        )
        receipt = document.get("receipt", {})
        receipt_passed = bool(
            receipt.get("deterministic_passed") is True
            and receipt.get("browser_passed") is True
            and receipt.get("failed_gate_count") == 0
            and int(receipt.get("check_count", 0)) > 0
        )
        science_passed = bool(
            automated_review.get("passed") is True
            and all(content_checks.values())
            and builder_passed
            and receipt_passed
        )
        if not science_passed:
            failures.append(
                _failure(
                    "scientific_or_review_gate_failed",
                    expected={
                        "content_checks": True,
                        "recorded_automated_review": True,
                        "builder_review": True,
                        "receipt": True,
                    },
                    actual={
                        "content_checks": all(content_checks.values()),
                        "recorded_automated_review": automated_review.get("passed"),
                        "builder_review": builder_passed,
                        "receipt": receipt_passed,
                    },
                )
            )

        actor, actor_passed = _motion_slice(
            actor_by_id,
            golden_id,
            artifact_hash,
            bind_artifact=True,
        )
        physics, physics_passed = _motion_slice(
            physics_by_id,
            golden_id,
            artifact_hash,
            bind_artifact=True,
        )
        source_hash = _sha256_text(module_source)
        shared, shared_passed = _motion_slice(
            shared_by_id,
            golden_id,
            artifact_hash,
            bind_artifact=False,
            source_hash=source_hash,
        )
        for name, passed in (
            ("actor_motion_failed", actor_passed),
            ("physics_motion_failed", physics_passed),
            ("shared_state_failed", shared_passed),
        ):
            if not passed:
                failures.append(_failure(name, expected=True, actual=False))

        locales: dict[str, dict[str, Any]] = {}
        screenshots: list[dict[str, Any]] = []
        for locale, direction in EXPECTED_LOCALES.items():
            localized = localized_pinned_golden(document, locale)
            current_shell_artifact = _current_shell_artifact(document, fixture, locale)
            current_shell_hash = _sha256_text(current_shell_artifact)
            journey = browser_by_identity.get((golden_id, locale))
            if journey is None:
                failures.append(
                    _failure(
                        "missing_browser_locale",
                        expected={"golden_id": golden_id, "locale": locale},
                        actual=None,
                    )
                )
                locales[locale] = {"passed": False}
                continue
            screenshot_records, screenshots_passed = _screenshot_records(
                journey,
                root=screenshot_root,
                failures=failures,
            )
            browser_passed = bool(
                journey.get("lang") == locale
                and journey.get("dir") == direction
                and journey.get("artifact_sha256") == current_shell_hash
                and _browser_journey_passes(journey)
                and screenshots_passed
            )
            if not browser_passed:
                failures.append(
                    _failure(
                        "browser_locale_failed",
                        expected={"locale": locale, "dir": direction, "passed": True},
                        actual={
                            "locale": journey.get("lang"),
                            "dir": journey.get("dir"),
                            "passed": journey.get("passed"),
                            "artifact_sha256": journey.get("artifact_sha256"),
                        },
                    )
                )
            screenshots.extend(screenshot_records)
            screenshot_paths.update(
                record["path"] for record in screenshot_records if record.get("path")
            )
            locales[locale] = {
                "passed": browser_passed,
                "lang": journey.get("lang"),
                "dir": journey.get("dir"),
                "title": localized["title"],
                "source_artifact_sha256": _sha256_text(localized["artifact"]),
                "review_artifact_sha256": current_shell_hash,
                "checks": journey.get("checks", {}),
                "responsive": journey.get("responsive", []),
                "a11y": journey.get("a11y", {}),
                "screenshots": screenshot_records,
            }

        reports.append(
            {
                "golden_id": golden_id,
                "passed": not failures,
                "tier": document.get("tier"),
                "pinned": document.get("pinned"),
                "artifact_sha256": artifact_hash,
                "document_sha256": document_hash,
                "manifest_hash_matches": manifest_hash_matches,
                "science": {
                    "passed": science_passed,
                    "deterministic_check_count": len(content_checks),
                    "content_checks": content_checks,
                    "recorded_automated_review_passed": automated_review.get("passed"),
                    "builder_review_passed": builder_passed,
                    "receipt_passed": receipt_passed,
                },
                "actor_motion": actor,
                "physics_motion": physics,
                "shared_state": shared,
                "locales": locales,
                "screenshots": screenshots,
                "failures": failures,
            }
        )

    manifest_passed = bool(
        manifest.get("schema_version") == "1.0"
        and manifest.get("contract_version") == "1.0"
        and set(manifest_by_id) == expected_ids
        and len(manifest_lessons) == len(expected_ids) == 6
    )
    locale_journey_count = len(browser_by_identity)
    screenshot_set_passed = len(screenshot_paths) == 24
    sources_have_zero_model_calls = all(
        report.get("model_calls") == 0
        for report in (browser_evidence, actor_motion, physics_motion, shared_state)
    )
    passed = bool(
        manifest_passed
        and sources_have_zero_model_calls
        and browser_evidence.get("passed") is True
        and len(reports) == 6
        and locale_journey_count == 12
        and screenshot_set_passed
        and all(report.get("passed") is True for report in reports)
    )
    return {
        "schema_version": "1.0",
        "gate": "GOLD-01",
        "model_calls": 0,
        "passed": passed,
        "golden_count": len(reports),
        "locale_journey_count": locale_journey_count,
        "screenshot_count": len(screenshot_paths),
        "screenshots_passed": screenshot_set_passed,
        "check_count": sum(
            int(report.get("science", {}).get("deterministic_check_count", 0))
            + int(report.get("actor_motion", {}).get("check_count", 0))
            + int(report.get("physics_motion", {}).get("check_count", 0))
            + int(report.get("shared_state", {}).get("check_count", 0))
            for report in reports
        ),
        "manifest": {
            "path": str(manifest_path.relative_to(ROOT)),
            "sha256": _sha256_bytes(manifest_path.read_bytes()),
            "schema_version": manifest.get("schema_version"),
            "contract_version": manifest.get("contract_version"),
            "golden_count": len(manifest_lessons),
            "passed": manifest_passed,
        },
        "source_evidence": {
            "actor_motion": "out/evidence/motion-02.json",
            "physics_motion": "out/evidence/motion-03.json",
            "shared_state": "out/evidence/motion-04.json",
            "browser": "out/evidence/gold-01-browser.json",
        },
        "goldens": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the deterministic bilingual six-golden GOLD-01 report."
    )
    parser.add_argument(
        "--browser-evidence",
        type=Path,
        default=EVIDENCE_ROOT / "gold-01-browser.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=EVIDENCE_ROOT / "gold-01.json",
    )
    parser.add_argument(
        "--collect-browser",
        action="store_true",
        help="Reassemble temporary current-shell artifacts and collect browser evidence.",
    )
    parser.add_argument(
        "--screens",
        type=Path,
        default=EVIDENCE_ROOT / "screens" / "gold-01",
    )
    arguments = parser.parse_args()
    if arguments.collect_browser:
        with tempfile.TemporaryDirectory(prefix="laysh-gold-01-") as temporary:
            artifact_root = Path(temporary)
            write_current_shell_review_artifacts(artifact_root)
            node = shutil.which("node")
            if node is None:
                raise RuntimeError("node is required for GOLD-01 browser evidence")
            completed = subprocess.run(  # noqa: S603 - fixed repository harness
                [
                    node,
                    str(ROOT / "scripts" / "check_golden_release.mjs"),
                    str(artifact_root),
                    str(arguments.screens),
                    str(arguments.browser_evidence),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr or completed.stdout)
    browser_evidence = _read_json(arguments.browser_evidence)
    if arguments.collect_browser:
        browser_evidence = _bind_browser_screenshot_hashes(
            browser_evidence,
            root=ROOT,
        )
        arguments.browser_evidence.write_text(
            json.dumps(browser_evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    report = build_report(browser_evidence=browser_evidence)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "golden_count": report["golden_count"],
                "locale_journey_count": report["locale_journey_count"],
                "check_count": report["check_count"],
                "output": str(arguments.output),
            }
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
