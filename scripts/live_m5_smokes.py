from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from server.codex_backend import CodexBackend
from server.codex_runtime import CodexExecutor
from server.goldens import GOLDEN_FIXTURE_IDS
from server.jobs import JobManager
from server.settings import Settings

ROOT = Path(__file__).parents[1]
REPORT_PATH = ROOT / "out" / "evidence" / "g5-unseen-smokes.json"
SMOKES = (
    {
        "id": "unseen_ar_force_mass",
        "locale": "ar",
        "question": "كيف تؤثر كتلة جسم في تسارعه إذا بقيت القوة المؤثرة ثابتة؟",
    },
    {
        "id": "unseen_en_spring_force",
        "locale": "en",
        "question": "Why does a spring stretch farther when the applied force increases?",
    },
)


def first_substantive_is_answer(event_types: list[str]) -> bool:
    substantive = [event_type for event_type in event_types if event_type != "heartbeat"]
    return bool(substantive) and substantive[0] == "answer"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


async def run() -> int:
    settings = Settings.from_env()
    executor = CodexExecutor(
        stage_timeout_seconds=settings.public_stage_timeout_seconds,
        evidence_stage_timeout_seconds=settings.evidence_stage_timeout_seconds,
        record_runtime=False,
        evidence_allowlist=frozenset(GOLDEN_FIXTURE_IDS),
    )
    manager = JobManager(
        CodexBackend(executor=executor, settings=settings),
        public_job_timeout_seconds=settings.public_job_timeout_seconds,
        evidence_job_timeout_seconds=settings.evidence_job_timeout_seconds,
    )
    results: list[dict[str, Any]] = []
    for smoke in SMOKES:
        started = time.monotonic()
        record = manager.start(smoke["question"], smoke["locale"])
        if record.task is None:
            raise RuntimeError("public smoke job did not start")
        await record.task
        events = [event.type for event in record.events]
        results.append(
            {
                "id": smoke["id"],
                "locale": smoke["locale"],
                "status": record.status,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "live_call_count": len(record.stage_executions),
                "stages": [
                    {
                        "stage": stage["stage"],
                        "model": stage["model"],
                        "elapsed_ms": stage["elapsed_ms"],
                        "ephemeral_thread_observed_transiently": bool(stage.get("thread_id")),
                    }
                    for stage in record.stage_executions
                ],
                "answer_first": first_substantive_is_answer(events),
                "verification_passed": any(
                    event.type == "verification" and event.payload.passed is True
                    for event in record.events
                ),
                "playable_artifact": bool(record.artifact),
                "fallback_reason": record.fallback.reason_code if record.fallback else None,
            }
        )
    passed = all(
        item["status"] == "complete"
        and item["answer_first"]
        and item["verification_passed"]
        and item["playable_artifact"]
        for item in results
    )
    report = {
        "schema_version": "1.0",
        "gate": "G5_unseen_smokes",
        "passed": passed,
        "public_profile": {
            "job_timeout_seconds": settings.public_job_timeout_seconds,
            "stage_timeout_seconds": settings.public_stage_timeout_seconds,
        },
        "results": results,
        "total_live_call_count": sum(item["live_call_count"] for item in results),
    }
    atomic_write(REPORT_PATH, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
