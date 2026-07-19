from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from server.schemas import (
    AnswerPayload,
    FallbackResult,
    PublicEvent,
    PublicResult,
    SimulationMetadata,
)

TERMINAL_STATES = frozenset(
    {"complete", "answer_only", "rejected", "failed", "cancelled", "timed_out"}
)

ALLOWED_TRANSITIONS = {
    "queued": {"filtering", "cancelled", "timed_out", "failed"},
    "filtering": {"understanding", "cancelled", "timed_out", "failed"},
    "understanding": {"answered", "rejected", "cancelled", "timed_out", "failed"},
    "answered": {"cache_lookup", "answer_only", "cancelled", "timed_out", "failed"},
    "cache_lookup": {"generating", "cancelled", "timed_out", "failed"},
    "generating": {"verifying", "cancelled", "timed_out", "failed"},
    "verifying": {"healing", "browser_check", "answer_only", "cancelled", "timed_out", "failed"},
    "healing": {"verifying", "cancelled", "timed_out", "failed"},
    "browser_check": {"complete", "answer_only", "cancelled", "timed_out", "failed"},
}


@dataclass(slots=True)
class JobRecord:
    job_id: str
    question: str | None
    locale: str | None
    status: str = "queued"
    events: list[PublicEvent] = field(default_factory=list)
    state_history: list[str] = field(default_factory=lambda: ["queued"])
    answer: AnswerPayload | None = None
    simulation: SimulationMetadata | None = None
    fallback: FallbackResult | None = None
    artifact: str | None = None
    task: asyncio.Task[None] | None = None
    started_at: float = field(default_factory=time.monotonic)
    public: bool = True
    evidence_fixture_id: str | None = None
    stage_executions: list[dict[str, Any]] = field(default_factory=list)

    def public_result(self) -> PublicResult:
        return PublicResult(
            job_id=self.job_id,
            status=self.status,
            answer=self.answer,
            simulation=self.simulation,
            fallback=self.fallback,
        )


class JobManager:
    def __init__(self, backend: Any, job_timeout_seconds: float) -> None:
        self.backend = backend
        self.job_timeout_seconds = job_timeout_seconds
        self.records: dict[str, JobRecord] = {}
        self.artifacts: dict[str, str] = {}

    @property
    def active_count(self) -> int:
        return sum(record.status not in TERMINAL_STATES for record in self.records.values())

    def get(self, job_id: str) -> JobRecord | None:
        return self.records.get(job_id)

    def start(
        self,
        question: str,
        locale: str | None,
        *,
        public: bool = True,
        evidence_fixture_id: str | None = None,
    ) -> JobRecord:
        job_id = f"job_{secrets.token_hex(8)}"
        record = JobRecord(
            job_id=job_id,
            question=question,
            locale=locale,
            public=public,
            evidence_fixture_id=evidence_fixture_id,
        )
        self.records[job_id] = record
        record.task = asyncio.create_task(self._run(record))
        return record

    def start_evidence(self, question: str, locale: str, fixture_id: str) -> JobRecord:
        return self.start(
            question,
            locale,
            public=False,
            evidence_fixture_id=fixture_id,
        )

    async def _run(self, record: JobRecord) -> None:
        from server.pipeline import PipelineCancelled, run_pipeline

        try:
            await asyncio.wait_for(
                run_pipeline(self, record),
                timeout=self.job_timeout_seconds,
            )
        except TimeoutError:
            self.terminal(record, "timed_out", "job_timeout")
        except (asyncio.CancelledError, PipelineCancelled):
            self.terminal(record, "cancelled", "cancelled_by_user")
        except Exception:
            self.terminal(record, "failed", "internal_pipeline_error")
        finally:
            record.question = None

    def transition(
        self,
        record: JobRecord,
        status: str,
        detail: str,
        *,
        emit_event: bool = True,
    ) -> None:
        if record.status in TERMINAL_STATES:
            return
        if status not in ALLOWED_TRANSITIONS.get(record.status, set()):
            raise ValueError(f"invalid job transition {record.status} -> {status}")
        record.status = status
        record.state_history.append(status)
        if status not in TERMINAL_STATES and emit_event:
            self.emit(
                record,
                "stage",
                {
                    "stage": status,
                    "detail": detail[:180],
                    "elapsed_ms": self.elapsed_ms(record),
                },
            )

    def emit(self, record: JobRecord, event_type: str, payload: dict[str, Any]) -> PublicEvent:
        event = PublicEvent(
            id=len(record.events) + 1,
            type=event_type,
            job_id=record.job_id,
            timestamp_ms=int(time.time() * 1000),
            payload=payload,
        )
        record.events.append(event)
        return event

    def terminal(self, record: JobRecord, status: str, reason_code: str) -> None:
        if record.status in TERMINAL_STATES:
            return
        self.transition(record, status, reason_code)
        if status in {"cancelled", "failed", "timed_out", "rejected"}:
            self.emit(record, "terminal", {"status": status, "reason_code": reason_code})

    async def cancel(self, record: JobRecord) -> PublicResult:
        if record.task is not None and not record.task.done():
            record.task.cancel()
            try:
                await record.task
            except asyncio.CancelledError:
                pass
        return record.public_result()

    @staticmethod
    def elapsed_ms(record: JobRecord) -> int:
        return max(0, int((time.monotonic() - record.started_at) * 1000))
