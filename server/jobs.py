from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from server.browser_verify import BrowserVerificationResult, verify_artifact_in_browser
from server.cache import VerifiedCache
from server.schemas import (
    AnswerPayload,
    FallbackResult,
    PublicEvent,
    PublicResult,
    SimulationMetadata,
)

TERMINAL_STATES = frozenset(
    {
        "complete",
        "answer_only",
        "rejected",
        "failed",
        "cancelled",
        "timed_out",
        "qa_inconclusive",
    }
)

ALLOWED_TRANSITIONS = {
    "queued": {"filtering", "cancelled", "timed_out", "failed"},
    "filtering": {"understanding", "cancelled", "timed_out", "failed"},
    "understanding": {"answered", "rejected", "cancelled", "timed_out", "failed"},
    "answered": {"cache_lookup", "answer_only", "cancelled", "timed_out", "failed"},
    "cache_lookup": {"generating", "browser_check", "cancelled", "timed_out", "failed"},
    "generating": {"verifying", "cancelled", "timed_out", "failed"},
    "verifying": {
        "healing",
        "browser_check",
        "answer_only",
        "qa_inconclusive",
        "cancelled",
        "timed_out",
        "failed",
    },
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
    builder_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    builder_outputs: dict[str, Any] = field(default_factory=dict)
    promote_golden: bool = False

    def public_result(self) -> PublicResult:
        return PublicResult(
            job_id=self.job_id,
            status=self.status,
            answer=self.answer,
            simulation=self.simulation,
            fallback=self.fallback,
        )


class JobManager:
    def __init__(
        self,
        backend: Any,
        public_job_timeout_seconds: float,
        evidence_job_timeout_seconds: float | None = None,
        browser_verifier: Callable[[str], BrowserVerificationResult] = verify_artifact_in_browser,
        cache: VerifiedCache | None = None,
        heartbeat_interval_seconds: float = 5.0,
    ) -> None:
        self.backend = backend
        self.public_job_timeout_seconds = public_job_timeout_seconds
        self.evidence_job_timeout_seconds = (
            public_job_timeout_seconds
            if evidence_job_timeout_seconds is None
            else evidence_job_timeout_seconds
        )
        self.records: dict[str, JobRecord] = {}
        self.artifacts: dict[str, str] = {}
        self.browser_verifier = browser_verifier
        self.cache = cache
        self.heartbeat_interval_seconds = heartbeat_interval_seconds

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
        promote_golden: bool = False,
    ) -> JobRecord:
        job_id = f"job_{secrets.token_hex(8)}"
        record = JobRecord(
            job_id=job_id,
            question=question,
            locale=locale,
            public=public,
            evidence_fixture_id=evidence_fixture_id,
            promote_golden=promote_golden,
        )
        self.records[job_id] = record
        record.task = asyncio.create_task(self._run(record))
        return record

    def start_evidence(
        self,
        question: str,
        locale: str,
        fixture_id: str,
        *,
        promote_golden: bool = False,
    ) -> JobRecord:
        return self.start(
            question,
            locale,
            public=False,
            evidence_fixture_id=fixture_id,
            promote_golden=promote_golden,
        )

    async def _run(self, record: JobRecord) -> None:
        from server.codex_runtime import CodexRuntimeError
        from server.pipeline import PipelineCancelled, run_pipeline

        heartbeat_task = asyncio.create_task(self._emit_heartbeats(record))
        try:
            timeout = (
                self.public_job_timeout_seconds
                if record.public
                else self.evidence_job_timeout_seconds
            )
            await asyncio.wait_for(
                run_pipeline(self, record),
                timeout=timeout,
            )
        except TimeoutError:
            self.terminal(record, "timed_out", "job_timeout")
        except (asyncio.CancelledError, PipelineCancelled):
            self.terminal(record, "cancelled", "cancelled_by_user")
        except CodexRuntimeError as error:
            if not record.public and error.builder_detail:
                record.builder_diagnostics.append(
                    {"code": error.code, "upstream_detail": error.builder_detail}
                )
            self.terminal(record, "failed", error.code)
        except Exception:
            self.terminal(record, "failed", "internal_pipeline_error")
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            record.question = None

    async def _emit_heartbeats(self, record: JobRecord) -> None:
        while record.status not in TERMINAL_STATES:
            await asyncio.sleep(self.heartbeat_interval_seconds)
            if record.status in TERMINAL_STATES:
                return
            self.emit(
                record,
                "heartbeat",
                {
                    "stage": record.status,
                    "elapsed_ms": self.elapsed_ms(record),
                },
            )

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
        if status in {"cancelled", "failed", "timed_out", "rejected", "qa_inconclusive"}:
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
