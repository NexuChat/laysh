from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from jsonschema import ValidationError
from pydantic import Field

from server.browser_verify import BrowserVerificationResult
from server.codex_backend import RuntimeContext, StageModelSpec
from server.codex_runtime import CodexRuntimeError, StageExecution
from server.fragment_generation import (
    assemble_fragments,
    validate_physics_fragment,
    validate_visual_fragment,
)
from server.schemas import (
    AnswerPayload,
    ClosedModel,
    ContractError,
    validate_module_output,
    validate_understanding,
)
from server.verify import VerificationResult, verify_candidate

LabModel = Literal["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
LabEffort = Literal["low", "medium", "high"]
LabCandidateStatus = Literal["queued", "generating", "verifying", "verified", "rejected", "failed"]
LabRunStatus = Literal["queued", "understanding", "generating", "complete", "rejected", "failed"]


class ModelLabStageConfig(ClosedModel):
    model: LabModel
    effort: LabEffort


class ModelLabCandidateConfig(ClosedModel):
    physics: ModelLabStageConfig
    visual: ModelLabStageConfig


class ModelLabCompareRequest(ClosedModel):
    question: str = Field(min_length=1, max_length=600)
    locale: Literal["ar", "en"] = "en"
    understand: ModelLabStageConfig
    candidates: list[ModelLabCandidateConfig] = Field(min_length=2, max_length=2)


class ModelLabAccepted(ClosedModel):
    contract_version: Literal["1.0"] = "1.0"
    run_id: str
    status_url: str


class ModelLabCandidateResult(ClosedModel):
    slot: Literal["A", "B"]
    physics_model: LabModel
    physics_effort: LabEffort
    visual_model: LabModel
    visual_effort: LabEffort
    status: LabCandidateStatus
    physics_elapsed_ms: int | None = Field(default=None, ge=0)
    visual_elapsed_ms: int | None = Field(default=None, ge=0)
    verification_elapsed_ms: int | None = Field(default=None, ge=0)
    check_count: int = Field(default=0, ge=0)
    failed_gates: list[str] = Field(default_factory=list, max_length=20)
    artifact_url: str | None = None


class ModelLabRunResult(ClosedModel):
    contract_version: Literal["1.0"] = "1.0"
    run_id: str
    status: LabRunStatus
    understand_model: LabModel
    understand_effort: LabEffort
    answer: AnswerPayload | None = None
    understand_elapsed_ms: int | None = Field(default=None, ge=0)
    failure_code: Literal[
        "unsafe",
        "not_simulatable",
        "understanding_failed",
    ] | None = None
    candidates: list[ModelLabCandidateResult] = Field(min_length=2, max_length=2)


@dataclass(slots=True)
class _Candidate:
    slot: Literal["A", "B"]
    config: ModelLabCandidateConfig
    status: LabCandidateStatus = "queued"
    physics_elapsed_ms: int | None = None
    visual_elapsed_ms: int | None = None
    verification_elapsed_ms: int | None = None
    check_count: int = 0
    failed_gates: list[str] = field(default_factory=list)
    artifact_url: str | None = None

    def public_result(self) -> ModelLabCandidateResult:
        return ModelLabCandidateResult(
            slot=self.slot,
            physics_model=self.config.physics.model,
            physics_effort=self.config.physics.effort,
            visual_model=self.config.visual.model,
            visual_effort=self.config.visual.effort,
            status=self.status,
            physics_elapsed_ms=self.physics_elapsed_ms,
            visual_elapsed_ms=self.visual_elapsed_ms,
            verification_elapsed_ms=self.verification_elapsed_ms,
            check_count=self.check_count,
            failed_gates=self.failed_gates,
            artifact_url=self.artifact_url,
        )


@dataclass(slots=True)
class _Run:
    run_id: str
    understand_config: ModelLabStageConfig
    candidates: list[_Candidate]
    status: LabRunStatus = "queued"
    answer: AnswerPayload | None = None
    understand_elapsed_ms: int | None = None
    failure_code: Literal[
        "unsafe",
        "not_simulatable",
        "understanding_failed",
    ] | None = None

    def public_result(self) -> ModelLabRunResult:
        return ModelLabRunResult(
            run_id=self.run_id,
            status=self.status,
            understand_model=self.understand_config.model,
            understand_effort=self.understand_config.effort,
            answer=self.answer,
            understand_elapsed_ms=self.understand_elapsed_ms,
            failure_code=self.failure_code,
            candidates=[candidate.public_result() for candidate in self.candidates],
        )


def _stage_data(result: dict[str, Any] | StageExecution) -> dict[str, Any]:
    return result.data if isinstance(result, StageExecution) else result


def _stage_elapsed(result: dict[str, Any] | StageExecution, fallback: int) -> int:
    return result.elapsed_ms if isinstance(result, StageExecution) else fallback


def _gate_names(failures: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            gate
            for failure in failures
            if isinstance(failure, dict)
            and isinstance((gate := failure.get("gate")), str)
        }
    )[:20]


class ModelLabManager:
    """Ephemeral A/B generation lab isolated from the learner job pipeline."""

    def __init__(
        self,
        *,
        backend: Any,
        browser_verifier: Callable[[str], BrowserVerificationResult],
        max_concurrent_runs: int = 1,
    ) -> None:
        self.backend = backend
        self.browser_verifier = browser_verifier
        self.runs: dict[str, _Run] = {}
        self.artifacts: dict[str, str] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._run_slots = asyncio.Semaphore(max_concurrent_runs)
        self._browser_slots = asyncio.Semaphore(1)

    def get(self, run_id: str) -> ModelLabRunResult | None:
        run = self.runs.get(run_id)
        return run.public_result() if run is not None else None

    def start(self, payload: ModelLabCompareRequest) -> ModelLabAccepted:
        run_id = f"lab_{secrets.token_hex(8)}"
        run = _Run(
            run_id=run_id,
            understand_config=payload.understand,
            candidates=[
                _Candidate(slot="A", config=payload.candidates[0]),
                _Candidate(slot="B", config=payload.candidates[1]),
            ],
        )
        self.runs[run_id] = run
        task = asyncio.create_task(
            self._execute(
                run,
                question=payload.question,
                locale=payload.locale,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return ModelLabAccepted(
            run_id=run_id,
            status_url=f"/api/model-lab/runs/{run_id}",
        )

    async def cancel_all(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _execute(self, run: _Run, *, question: str, locale: str) -> None:
        async with self._run_slots:
            context = RuntimeContext(public=True)
            run.status = "understanding"
            started = time.monotonic()
            try:
                understanding = validate_understanding(
                    _stage_data(
                        await self.backend.understand_for_lab(
                            question,
                            locale,
                            model=run.understand_config.model,
                            effort=run.understand_config.effort,
                            runtime_context=context,
                        )
                    )
                )
            except (
                CodexRuntimeError,
                ContractError,
                ValidationError,
                OSError,
                ValueError,
            ):
                run.understand_elapsed_ms = int((time.monotonic() - started) * 1000)
                run.status = "failed"
                run.failure_code = "understanding_failed"
                return

            run.understand_elapsed_ms = int((time.monotonic() - started) * 1000)
            run.answer = AnswerPayload(
                tldr=understanding["tldr"],
                key_formula=understanding.get("key_formula"),
            )
            if understanding["safe"] is not True:
                run.status = "rejected"
                run.failure_code = "unsafe"
                return
            if understanding["simulatable"] is not True:
                run.status = "rejected"
                run.failure_code = "not_simulatable"
                return

            run.status = "generating"
            outcomes = await asyncio.gather(
                *(
                    self._build_candidate(
                        run,
                        candidate,
                        understanding=understanding,
                        context=context,
                    )
                    for candidate in run.candidates
                ),
                return_exceptions=True,
            )
            for candidate, outcome in zip(run.candidates, outcomes, strict=True):
                if isinstance(outcome, BaseException) and candidate.status not in {
                    "verified",
                    "rejected",
                    "failed",
                }:
                    candidate.status = "failed"
            run.status = "complete"

    async def _build_candidate(
        self,
        run: _Run,
        candidate: _Candidate,
        *,
        understanding: dict[str, Any],
        context: RuntimeContext,
    ) -> None:
        candidate.status = "generating"
        generation_started = time.monotonic()
        physics_spec = StageModelSpec(
            model=candidate.config.physics.model,
            effort=candidate.config.physics.effort,
        )
        visual_spec = StageModelSpec(
            model=candidate.config.visual.model,
            effort=candidate.config.visual.effort,
        )
        try:
            physics_result, visual_result = (
                await self.backend.generate_fragments_for_lab(
                    understanding,
                    physics_spec=physics_spec,
                    visual_spec=visual_spec,
                    runtime_context=context,
                )
            )
        except (CodexRuntimeError, OSError, RuntimeError):
            elapsed = int((time.monotonic() - generation_started) * 1000)
            candidate.physics_elapsed_ms = elapsed
            candidate.visual_elapsed_ms = elapsed
            candidate.status = "failed"
            return
        elapsed = int((time.monotonic() - generation_started) * 1000)
        candidate.physics_elapsed_ms = _stage_elapsed(physics_result, elapsed)
        candidate.visual_elapsed_ms = _stage_elapsed(visual_result, elapsed)
        try:
            physics_fragment = validate_physics_fragment(
                _stage_data(physics_result),
                understanding,
            )
            visual_fragment = validate_visual_fragment(
                _stage_data(visual_result),
                understanding,
            )
            module_output = validate_module_output(
                assemble_fragments(
                    physics_fragment,
                    visual_fragment,
                    understanding,
                )
            )
        except (ContractError, ValidationError, OSError, ValueError):
            candidate.failed_gates = ["generation_contract"]
            candidate.check_count = 1
            candidate.status = "rejected"
            return

        candidate.status = "verifying"
        verification_started = time.monotonic()
        deterministic: VerificationResult = await asyncio.to_thread(
            verify_candidate,
            module_output,
            understanding,
        )
        candidate.check_count = deterministic.check_count
        if not deterministic.passed or deterministic.artifact is None:
            candidate.failed_gates = _gate_names(deterministic.failures)
            candidate.verification_elapsed_ms = int(
                (time.monotonic() - verification_started) * 1000
            )
            candidate.status = "rejected"
            return

        try:
            async with self._browser_slots:
                browser: BrowserVerificationResult = await asyncio.to_thread(
                    self.browser_verifier,
                    deterministic.artifact,
                )
        except (OSError, RuntimeError, ValueError):
            candidate.verification_elapsed_ms = int(
                (time.monotonic() - verification_started) * 1000
            )
            candidate.status = "failed"
            return
        candidate.check_count += browser.check_count
        if not browser.passed:
            candidate.failed_gates = _gate_names(browser.failures)
            candidate.verification_elapsed_ms = int(
                (time.monotonic() - verification_started) * 1000
            )
            candidate.status = "rejected"
            return

        artifact_id = f"{run.run_id}_{candidate.slot.lower()}"
        self.artifacts[artifact_id] = deterministic.artifact
        candidate.artifact_url = f"/api/model-lab/artifacts/{artifact_id}"
        candidate.verification_elapsed_ms = int(
            (time.monotonic() - verification_started) * 1000
        )
        candidate.status = "verified"
