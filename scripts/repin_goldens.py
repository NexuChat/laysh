from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from server.browser_verify import verify_artifact_in_browser
from server.goldens import (
    GOLDEN_FIXTURE_IDS,
    GOLDEN_ROOT,
    golden_id_for_fixture,
    load_golden_fixtures,
    review_golden_candidate,
)
from server.verify import verify_candidate

ROOT = Path(__file__).parents[1]
CANDIDATE_ROOT = ROOT / "out" / "tmp" / "goldens"
EVIDENCE_ROOT = ROOT / "out" / "evidence" / "goldens"
REGENERATED = frozenset({"moon_phases_ar"})


def _migrated_understanding(
    understanding: dict[str, Any],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    migrated = deepcopy(understanding)
    migrated.pop("prediction", None)
    migrated["misconception"] = fixture["review_contract"]["misconception"]
    parameter = migrated.get("primary_parameter")
    if isinstance(parameter, dict):
        parameter["sweep_mode"] = fixture["review_contract"]["primary_parameter"][
            "sweep_mode"
        ]
    return migrated


def verify_lesson(fixture_id: str) -> dict[str, Any]:
    fixture = load_golden_fixtures()[fixture_id]
    golden_id = golden_id_for_fixture(fixture_id)
    candidate_path = CANDIDATE_ROOT / f"{golden_id}.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    outputs = candidate["builder_outputs"]
    module_output = outputs["module_output"]
    if fixture_id in REGENERATED:
        source_understanding = outputs["understanding"]
    else:
        pinned = json.loads(
            (GOLDEN_ROOT / f"{golden_id}.json").read_text(encoding="utf-8")
        )
        lesson_marker = "<script>window.__LAYSH_LESSON__ = "
        lesson_start = pinned["artifact"].index(lesson_marker) + len(lesson_marker)
        lesson_end = pinned["artifact"].index(";</script>", lesson_start)
        source_understanding = json.loads(pinned["artifact"][lesson_start:lesson_end])
        if module_output["module_js"] not in pinned["artifact"]:
            raise ValueError(f"embedded module mismatch: {golden_id}")
    understanding = _migrated_understanding(source_understanding, fixture)
    deterministic = verify_candidate(module_output, understanding)
    browser = (
        verify_artifact_in_browser(deterministic.artifact)
        if deterministic.passed and deterministic.artifact is not None
        else None
    )
    review = review_golden_candidate(
        fixture=fixture,
        understanding=understanding,
        module_output=module_output,
    )
    passed = bool(
        deterministic.passed
        and deterministic.artifact is not None
        and browser is not None
        and browser.passed
        and review["passed"]
    )
    return {
        "fixture_id": fixture_id,
        "golden_id": golden_id,
        "method": "regenerated" if fixture_id in REGENERATED else "reassembled",
        "passed": passed,
        "understanding": understanding,
        "module_output": module_output,
        "artifact": deterministic.artifact,
        "artifact_sha256": (
            hashlib.sha256(deterministic.artifact.encode()).hexdigest()
            if deterministic.artifact is not None
            else None
        ),
        "deterministic": {
            "passed": deterministic.passed,
            "check_count": deterministic.check_count,
            "failures": deterministic.failures,
            "node_report": deterministic.node_report,
        },
        "browser": (
            {
                "passed": browser.passed,
                "check_count": browser.check_count,
                "failures": browser.failures,
                "evidence": browser.evidence,
            }
            if browser is not None
            else None
        ),
        "review": review,
        "candidate": candidate,
    }


def public_result(result: dict[str, Any]) -> dict[str, Any]:
    browser = result["browser"] or {"evidence": {}, "failures": []}
    evidence = browser["evidence"]
    sweep = evidence.get("renderOutputSweep") or {}
    return {
        "id": result["golden_id"],
        "method": result["method"],
        "passed": result["passed"],
        "artifact_sha256": result["artifact_sha256"],
        "deterministic_check_count": result["deterministic"]["check_count"],
        "browser_check_count": browser.get("check_count", 0),
        "subject_motion_ratio": evidence.get("idleMotionSubjectChangedPixelRatio"),
        "whole_canvas_motion_ratio": evidence.get("idleMotionWholeCanvasChangedPixelRatio"),
        "render_output_gate": {
            "passed": sweep.get("passed"),
            "metric": sweep.get("metric"),
            "rank_correlation": sweep.get("rankCorrelation"),
            "sample_count": len(sweep.get("samples", [])),
            "failure": sweep.get("failure"),
        },
        "failures": [
            *result["deterministic"]["failures"],
            *browser.get("failures", []),
        ],
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def apply_results(results: list[dict[str, Any]]) -> None:
    if not all(result["passed"] for result in results):
        raise ValueError("cannot re-pin while any lesson has a failed gate")
    summary = {
        "schema_version": "1.0",
        "gate": "trusted_shell_autoplay_and_render_output_consistency",
        "lessons": [public_result(result) for result in results],
    }
    for result in results:
        golden_id = result["golden_id"]
        candidate = result["candidate"]
        outputs = candidate["builder_outputs"]
        outputs["understanding"] = result["understanding"]
        outputs["verification"] = {
            **outputs.get("verification", {}),
            "passed": True,
            "check_count": (
                result["deterministic"]["check_count"]
                + result["browser"]["check_count"]
            ),
            "node_report": result["deterministic"]["node_report"],
        }
        outputs["browser"] = result["browser"]["evidence"]
        candidate["artifact"] = result["artifact"]
        candidate["artifact_sha256"] = result["artifact_sha256"]
        candidate["shell_refreshed_offline"] = result["method"] == "reassembled"
        candidate["artifact_method"] = result["method"]
        candidate["automated_review"] = result["review"]
        _write_json(CANDIDATE_ROOT / f"{golden_id}.json", candidate)
        (CANDIDATE_ROOT / f"{golden_id}.html").write_text(
            result["artifact"], encoding="utf-8"
        )

        pinned_path = GOLDEN_ROOT / f"{golden_id}.json"
        pinned = json.loads(pinned_path.read_text(encoding="utf-8"))
        pinned["artifact"] = result["artifact"]
        pinned["artifact_sha256"] = result["artifact_sha256"]
        pinned["receipt"] = {
            "deterministic_passed": True,
            "browser_passed": True,
            "failed_gate_count": 0,
            "check_count": outputs["verification"]["check_count"],
        }
        pinned["review"]["automated"] = result["review"]
        pinned["review"]["builder"] = json.loads(
            (EVIDENCE_ROOT / f"{golden_id}-manual-review.json").read_text(
                encoding="utf-8"
            )
        )
        pinned["review"]["reference_contract"] = load_golden_fixtures()[
            result["fixture_id"]
        ]["review_contract"]
        pinned["evidence"] = {
            **pinned["evidence"],
            "heal_count": outputs["verification"].get("heal_count", 0),
            "browser": result["browser"]["evidence"],
            "artifact_method": result["method"],
            "revalidation_summary": str(
                (EVIDENCE_ROOT / "autoplay-render-revalidation.json").relative_to(ROOT)
            ),
            "screenshots": [
                f"out/evidence/screens/goldens/{golden_id}-mobile-390x844.png",
                f"out/evidence/screens/goldens/{golden_id}-desktop-1440x900.png",
            ],
        }
        if result["method"] == "regenerated":
            pinned["evidence"] = {
                **pinned["evidence"],
                "attempt": candidate["attempt"],
                "job_id": candidate["job_id"],
                "stages": candidate["stages"],
                "total_elapsed_ms": candidate["total_elapsed_ms"],
            }
        pinned["release_revision"] = "v1.2"
        _write_json(pinned_path, pinned)

    manifest = {
        "schema_version": "1.0",
        "contract_version": "1.0",
        "lessons": [
            {
                "id": result["golden_id"],
                "aliases": result["candidate"].get(
                    "aliases",
                    json.loads(
                        (GOLDEN_ROOT / f"{result['golden_id']}.json").read_text(
                            encoding="utf-8"
                        )
                    )["aliases"],
                ),
                "instant": True,
                "tier": "A",
                "artifact_sha256": result["artifact_sha256"],
                "metadata": json.loads(
                    (GOLDEN_ROOT / f"{result['golden_id']}.json").read_text(
                        encoding="utf-8"
                    )
                )["metadata"],
            }
            for result in sorted(results, key=lambda item: item["golden_id"])
        ],
    }
    _write_json(GOLDEN_ROOT / "manifest.json", manifest)
    _write_json(EVIDENCE_ROOT / "autoplay-render-revalidation.json", summary)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-verify and re-pin the six trusted-shell goldens"
    )
    parser.add_argument("--apply", action="store_true")
    options = parser.parse_args()
    results = [verify_lesson(fixture_id) for fixture_id in GOLDEN_FIXTURE_IDS]
    report = [public_result(result) for result in results]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if options.apply:
        apply_results(results)
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
