from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from server.settings import ALLOWED_RUNTIME_MODELS


def build_g2_evidence(
    *,
    record: Any,
    artifact_sha256: str,
    browser_evidence: dict[str, Any],
    total_elapsed_ms: int,
) -> dict[str, Any]:
    stages = []
    for index, execution in enumerate(record.stage_executions):
        model = execution["model"]
        if model not in ALLOWED_RUNTIME_MODELS:
            raise ValueError("G2 evidence contains a non-GPT-5.6 runtime model")
        stages.append(
            {
                "stage": execution.get("stage", f"stage_{index + 1}"),
                "attempt": execution.get("attempt", 1),
                "model": model,
                "outcome": execution.get("outcome", "completed"),
                "elapsed_ms": execution["elapsed_ms"],
                "failure_code": execution.get("failure_code"),
                "thread_id": execution["thread_id"],
                "evidence_mode": True,
            }
        )
    simulation = record.simulation
    fallback = record.fallback
    browser_passed = bool(
        browser_evidence.get("ready")
        and browser_evidence.get("controlChanged", True)
        and browser_evidence.get("frameChanged", True)
        and not browser_evidence.get("runtimeError", False)
        and browser_evidence.get("externalRequests") == 0
    )
    return {
        "schema_version": "1.0",
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "fixture_id": "moon_phases_ar",
        "runtime_family": "GPT-5.6",
        "job_id": record.job_id,
        "status": record.status,
        "total_elapsed_ms": total_elapsed_ms,
        "stages": stages,
        "state_history": list(record.state_history),
        "public_event_types": [event.type for event in record.events],
        "simulation": (
            {
                "sim_id": simulation.sim_id,
                "effective_model": simulation.effective_model,
                "pipeline_elapsed_ms": simulation.elapsed_ms,
                "check_count": simulation.check_count,
                "heal_count": simulation.heal_count,
            }
            if simulation
            else None
        ),
        "fallback_reason_code": fallback.reason_code if fallback else None,
        "artifact_sha256": artifact_sha256 or None,
        "browser": browser_evidence,
        "gate_g2_passed": record.status == "complete" and browser_passed,
    }
