from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from server.codex_backend import CodexBackend
from server.codex_runtime import CodexExecutor
from server.evidence import build_g2_evidence
from server.jobs import JobManager
from server.settings import Settings

ROOT = Path(__file__).parents[1]
FIXTURE_PATH = ROOT / "server" / "fixtures" / "moon_phases_ar.json"
EVIDENCE_DIR = ROOT / "out" / "evidence"
ARTIFACT_PATH = EVIDENCE_DIR / "g2-moon-phases-ar.html"
REPORT_PATH = EVIDENCE_DIR / "g2-moon-phases-ar.json"
DIAGNOSTIC_PATH = EVIDENCE_DIR / "g2-moon-phases-ar-diagnostic.json"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def browser_check(artifact_path: Path) -> dict:
    node = shutil.which("node")
    if node is None:
        return {"ready": False, "externalRequests": None, "error_code": "node_missing"}
    completed = subprocess.run(  # noqa: S603 - fixed verifier and curated artifact paths
        [node, str(ROOT / "scripts" / "check_artifact.mjs"), str(artifact_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        return {
            "ready": False,
            "externalRequests": None,
            "error_code": "browser_check_failed",
        }
    return json.loads(completed.stdout)


async def run() -> int:
    settings = Settings.from_env()
    if not settings.record_runtime:
        raise RuntimeError("LAYSH_RECORD_RUNTIME=1 is required for curated G2 evidence")
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if fixture.get("fixture_id") != "moon_phases_ar":
        raise RuntimeError("curated fixture identity mismatch")

    executor = CodexExecutor(
        stage_timeout_seconds=settings.public_stage_timeout_seconds,
        evidence_stage_timeout_seconds=settings.evidence_stage_timeout_seconds,
        record_runtime=True,
        evidence_allowlist=frozenset({"moon_phases_ar"}),
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
        fixture["fixture_id"],
    )
    if record.task is None:
        raise RuntimeError("evidence job did not start")
    await record.task
    total_elapsed_ms = int((time.monotonic() - started) * 1000)

    artifact_hash = ""
    browser_evidence: dict = {
        "ready": False,
        "externalRequests": None,
        "error_code": "artifact_unavailable",
    }
    if record.status == "complete" and record.artifact:
        atomic_write(ARTIFACT_PATH, record.artifact)
        artifact_hash = hashlib.sha256(record.artifact.encode("utf-8")).hexdigest()
        browser_evidence = browser_check(ARTIFACT_PATH)

    evidence = build_g2_evidence(
        record=record,
        artifact_sha256=artifact_hash,
        browser_evidence=browser_evidence,
        total_elapsed_ms=total_elapsed_ms,
    )
    atomic_write(REPORT_PATH, json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    if record.builder_diagnostics:
        diagnostic = {
            "fixture_id": fixture["fixture_id"],
            "job_id": record.job_id,
            "public": False,
            "diagnostics": record.builder_diagnostics,
        }
        atomic_write(
            DIAGNOSTIC_PATH,
            json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n",
        )
    print(
        json.dumps(
            {
                "gate_g2_passed": evidence["gate_g2_passed"],
                "status": evidence["status"],
                "total_elapsed_ms": evidence["total_elapsed_ms"],
                "stages": [
                    {
                        "stage": stage["stage"],
                        "model": stage["model"],
                        "elapsed_ms": stage["elapsed_ms"],
                    }
                    for stage in evidence["stages"]
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0 if evidence["gate_g2_passed"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
