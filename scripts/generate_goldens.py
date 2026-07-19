from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from server.cache import VerificationReceipt, VerifiedCache
from server.codex_backend import CodexBackend
from server.codex_runtime import CodexExecutor
from server.goldens import (
    GOLDEN_FIXTURE_IDS,
    GOLDEN_ROOT,
    golden_id_for_fixture,
    load_golden_fixtures,
    review_golden_candidate,
)
from server.jobs import JobManager
from server.settings import Settings

ROOT = Path(__file__).parents[1]
EVIDENCE_ROOT = ROOT / "out" / "evidence" / "goldens"
CANDIDATE_ROOT = ROOT / "out" / "tmp" / "goldens"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _safe_stage_report(record: Any) -> list[dict[str, Any]]:
    return [
        {
            "stage": stage["stage"],
            "model": stage["model"],
            "elapsed_ms": stage["elapsed_ms"],
            "thread_id_captured": bool(stage.get("thread_id")),
        }
        for stage in record.stage_executions
    ]


async def generate_candidate(fixture_id: str, attempt: int) -> int:
    settings = Settings.from_env()
    if not settings.record_runtime:
        raise RuntimeError("LAYSH_RECORD_RUNTIME=1 is required for golden evidence")
    fixtures = load_golden_fixtures()
    fixture = fixtures[fixture_id]
    executor = CodexExecutor(
        stage_timeout_seconds=settings.public_stage_timeout_seconds,
        evidence_stage_timeout_seconds=settings.evidence_stage_timeout_seconds,
        record_runtime=True,
        evidence_allowlist=frozenset(GOLDEN_FIXTURE_IDS),
    )
    backend = CodexBackend(executor=executor, settings=settings)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=settings.public_job_timeout_seconds,
        evidence_job_timeout_seconds=settings.evidence_job_timeout_seconds,
    )
    started = time.monotonic()
    record = manager.start_evidence(
        fixture["question"],
        fixture["locale"],
        fixture_id,
        promote_golden=True,
    )
    if record.task is None:
        raise RuntimeError("golden evidence job did not start")
    await record.task
    total_elapsed_ms = int((time.monotonic() - started) * 1000)
    review: dict[str, Any] = {
        "passed": False,
        "failure_codes": ["pipeline_incomplete"],
        "checks": {},
    }
    artifact_sha256 = None
    if record.status == "complete" and record.artifact and record.builder_outputs:
        review = review_golden_candidate(
            fixture=fixture,
            understanding=record.builder_outputs["understanding"],
            module_output=record.builder_outputs["module_output"],
        )
        artifact_sha256 = hashlib.sha256(record.artifact.encode()).hexdigest()
        candidate = {
            "schema_version": "1.0",
            "fixture_id": fixture_id,
            "attempt": attempt,
            "job_id": record.job_id,
            "total_elapsed_ms": total_elapsed_ms,
            "stages": _safe_stage_report(record),
            "artifact_sha256": artifact_sha256,
            "artifact": record.artifact,
            "builder_outputs": record.builder_outputs,
            "automated_review": review,
        }
        atomic_write(
            CANDIDATE_ROOT / f"{golden_id_for_fixture(fixture_id)}.json",
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        )
        atomic_write(
            CANDIDATE_ROOT / f"{golden_id_for_fixture(fixture_id)}.html",
            record.artifact,
        )
    report = {
        "schema_version": "1.0",
        "fixture_id": fixture_id,
        "attempt": attempt,
        "job_id": record.job_id,
        "status": record.status,
        "total_elapsed_ms": total_elapsed_ms,
        "live_call_count": len(record.stage_executions),
        "stages": _safe_stage_report(record),
        "heal_count": (
            record.builder_outputs.get("verification", {}).get("heal_count")
            if record.builder_outputs
            else None
        ),
        "qa": record.builder_outputs.get("qa") if record.builder_outputs else None,
        "artifact_sha256": artifact_sha256,
        "automated_review": review,
        "diagnostics": record.builder_diagnostics,
    }
    atomic_write(
        EVIDENCE_ROOT / f"{golden_id_for_fixture(fixture_id)}-attempt-{attempt}.json",
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if record.status == "complete" and review["passed"] else 1


def _manual_review_passed(review: dict[str, Any]) -> bool:
    required = (
        "answer_correct",
        "assumptions_honest",
        "formula_display_grade",
        "units_correct",
        "fixtures_correct",
        "misconception_addressed",
        "teaching_flow_clear",
        "visual_model_unambiguous",
        "light_occlusion_consistent",
        "labels_precise",
        "smooth_shading",
        "min_default_max_tested",
        "arabic_metadata_reviewed",
        "english_metadata_reviewed",
    )
    return review.get("verdict") == "pass" and all(review.get(key) is True for key in required)


def build_manifest() -> dict[str, Any]:
    lessons: list[dict[str, Any]] = []
    for path in sorted(GOLDEN_ROOT.glob("*.json")):
        if path.name == "manifest.json":
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        lessons.append(
            {
                "id": document["golden_id"],
                "aliases": document["aliases"],
                "instant": True,
                "tier": "A",
                "artifact_sha256": document["artifact_sha256"],
                "metadata": document["metadata"],
            }
        )
    return {"schema_version": "1.0", "contract_version": "1.0", "lessons": lessons}


def promote_candidate(fixture_id: str) -> int:
    settings = Settings.from_env()
    if not settings.cache_key_secret:
        raise RuntimeError("LAYSH_CACHE_KEY_SECRET is required to pin a golden")
    golden_id = golden_id_for_fixture(fixture_id)
    fixture = load_golden_fixtures()[fixture_id]
    candidate_path = CANDIDATE_ROOT / f"{golden_id}.json"
    review_path = EVIDENCE_ROOT / f"{golden_id}-manual-review.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    manual_review = json.loads(review_path.read_text(encoding="utf-8"))
    if candidate["fixture_id"] != fixture_id:
        raise ValueError("candidate fixture identity mismatch")
    outputs = candidate["builder_outputs"]
    current_review = review_golden_candidate(
        fixture=fixture,
        understanding=outputs["understanding"],
        module_output=outputs["module_output"],
    )
    if not current_review["passed"]:
        raise ValueError("candidate has not passed automated promotion review")
    if not _manual_review_passed(manual_review):
        raise ValueError("candidate has not passed the complete builder review checklist")
    screenshot_root = ROOT / "out" / "evidence" / "screens" / "goldens"
    browser_report_path = EVIDENCE_ROOT / f"{golden_id}-browser.json"
    screenshots = [
        screenshot_root / f"{golden_id}-mobile-390x844.png",
        screenshot_root / f"{golden_id}-desktop-1440x900.png",
    ]
    if any(not path.exists() or path.stat().st_size < 10_000 for path in screenshots):
        raise ValueError("accepted mobile and desktop screenshots are required")
    browser_report = json.loads(browser_report_path.read_text(encoding="utf-8"))
    if not (
        browser_report.get("ready") is True
        and browser_report.get("runtimeError") is False
        and browser_report.get("externalRequests") == 0
        and browser_report.get("consoleErrors") == []
        and len(browser_report.get("cases", [])) == 3
        and all(case.get("frameChanged") is True for case in browser_report["cases"])
    ):
        raise ValueError("golden browser evidence did not pass")
    understanding = outputs["understanding"]
    verification = outputs["verification"]
    cache = VerifiedCache(
        root=ROOT / "out" / "cache" / "live",
        golden_root=GOLDEN_ROOT,
        secret=settings.cache_key_secret.encode(),
        contract_version="1.0",
    )
    entry = cache.pin_golden(
        golden_id=golden_id,
        question=fixture["question"],
        locale=understanding["lang"],
        domain=understanding["domain"],
        canonical_intent=understanding["canonical_intent"],
        artifact=candidate["artifact"],
        title=understanding["title"],
        direction="rtl" if understanding["lang"] == "ar" else "ltr",
        receipt=VerificationReceipt(
            deterministic_passed=True,
            browser_passed=True,
            failed_gate_count=0,
            check_count=verification["check_count"],
        ),
        aliases=[golden_id, fixture_id, fixture["metadata"]["en"]["title"]],
        answer={"tldr": understanding["tldr"], "key_formula": understanding["key_formula"]},
        metadata=fixture["metadata"],
        review={
            "automated": current_review,
            "builder": manual_review,
            "reference_contract": fixture["review_contract"],
        },
        evidence={
            "attempt": candidate["attempt"],
            "job_id": candidate["job_id"],
            "stages": candidate["stages"],
            "total_elapsed_ms": candidate["total_elapsed_ms"],
            "heal_count": verification["heal_count"],
            "browser": browser_report,
            "screenshots": [str(path.relative_to(ROOT)) for path in screenshots],
        },
    )
    manifest = build_manifest()
    atomic_write(
        GOLDEN_ROOT / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps({"golden_id": golden_id, "cache_id": entry.cache_id}, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or promote curated Laysh goldens")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate")
    generate.add_argument("--fixture", required=True, choices=GOLDEN_FIXTURE_IDS)
    generate.add_argument("--attempt", type=int, choices=(1, 2, 3), required=True)
    promote = subparsers.add_parser("promote")
    promote.add_argument("--fixture", required=True, choices=GOLDEN_FIXTURE_IDS)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    if arguments.command == "generate":
        return asyncio.run(generate_candidate(arguments.fixture, arguments.attempt))
    return promote_candidate(arguments.fixture)


if __name__ == "__main__":
    sys.exit(main())
