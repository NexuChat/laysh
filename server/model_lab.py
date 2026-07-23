from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from jsonschema import ValidationError
from pydantic import Field, model_validator

from server.browser_verify import BrowserVerificationResult
from server.codex_backend import RuntimeContext, StageModelSpec
from server.codex_runtime import CodexRuntimeError, StageExecution
from server.fragment_generation import (
    assemble_fragments,
    fragment_failure_diagnostic,
    validate_physics_fragment,
    validate_visual_fragment,
)
from server.model_lab_discovery import (
    DisabledEvidenceProvider,
    ModelLabDiscoveryPlan,
    ModelLabEvidenceBundle,
    ModelLabEvidenceSource,
    build_discovery_plan,
)
from server.schemas import (
    AnswerPayload,
    ClosedModel,
    ContractError,
    load_schema,
    validate_document,
    validate_module_output,
    validate_understanding,
)
from server.verify import (
    VerificationResult,
    verify_artifact_contract,
    verify_candidate,
)

LabModel = Literal["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
LabEffort = Literal["low", "medium", "high", "xhigh", "max", "ultra"]
LabSourceMode = Literal["off", "public_references"]
LabVisualMode = Literal["trusted_scene_plan", "direct_canvas", "hybrid_race"]
LabCandidateStatus = Literal[
    "queued",
    "generating",
    "verifying",
    "verified",
    "unverified",
    "rejected",
    "failed",
]
LabRunStatus = Literal["queued", "understanding", "generating", "complete", "rejected", "failed"]
LabArtifactTier = Literal["verified", "unverified_preview"]


class ModelLabStageConfig(ClosedModel):
    model: LabModel
    effort: LabEffort
    fast: bool = True

    @model_validator(mode="after")
    def effort_must_match_model(self) -> ModelLabStageConfig:
        from server.settings import LAB_REASONING_EFFORTS_BY_MODEL

        if self.effort not in LAB_REASONING_EFFORTS_BY_MODEL[self.model]:
            raise ValueError("effort is not supported by the selected model")
        return self


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
    failure_codes: list[str] = Field(default_factory=list, max_length=20)
    artifact_tier: LabArtifactTier | None = None
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


LabPipelineModelStage = Literal[
    "understand",
    "physics",
    "visual",
    "repair_1",
    "repair_2",
    "qa",
]
LabPipelineStage = Literal[
    "evidence",
    "understand",
    "physics",
    "plan",
    "visual",
    "verify",
    "browser",
    "repair_1",
    "repair_2",
    "qa",
    "finalize",
]
LabPipelineRerunStage = LabPipelineStage
LabPipelineStatus = Literal[
    "queued",
    "running",
    "complete",
    "rejected",
    "failed",
    "cancelled",
]
LabPipelineEventStatus = Literal["running", "passed", "failed", "skipped"]


class ModelLabPipelineStages(ClosedModel):
    understand: ModelLabStageConfig
    physics: ModelLabStageConfig
    visual: ModelLabStageConfig
    repair_1: ModelLabStageConfig
    repair_2: ModelLabStageConfig
    qa: ModelLabStageConfig


class ModelLabPipelineRequest(ClosedModel):
    question: str = Field(min_length=1, max_length=600)
    locale: Literal["ar", "en"] = "en"
    source_mode: LabSourceMode = "off"
    visual_mode: LabVisualMode = "trusted_scene_plan"
    stages: ModelLabPipelineStages


class ModelLabPipelineRerunRequest(ClosedModel):
    stage: LabPipelineRerunStage
    config: ModelLabStageConfig | None = None
    source_mode: LabSourceMode | None = None
    visual_mode: LabVisualMode | None = None

    @model_validator(mode="after")
    def config_matches_stage_kind(self) -> ModelLabPipelineRerunRequest:
        model_stages = {
            "understand",
            "physics",
            "visual",
            "repair_1",
            "repair_2",
            "qa",
        }
        if self.stage in model_stages and self.config is None:
            raise ValueError("a model stage rerun requires its explicit config")
        if self.stage not in model_stages and self.config is not None:
            raise ValueError("a deterministic stage does not accept model config")
        if self.source_mode is not None and self.stage != "evidence":
            raise ValueError("source mode can change only when rerunning evidence")
        if self.visual_mode is not None and self.stage not in {
            "evidence",
            "understand",
            "physics",
            "plan",
            "visual",
        }:
            raise ValueError("visual mode must rerun from a visual dependency")
        return self


class ModelLabVisualRichness(ClosedModel):
    scene_depth: bool
    physical_light: bool
    idle_motion: bool
    reactive_feedback: bool
    readable_overlays: bool


class ModelLabStageOutput(ClosedModel):
    summary: str | None = Field(default=None, max_length=600)
    formula: str | None = Field(default=None, max_length=600)
    details: list[str] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    expressions: list[str] = Field(default_factory=list, max_length=8)
    output_names: list[str] = Field(default_factory=list, max_length=8)
    issues: list[str] = Field(default_factory=list, max_length=3)
    sources: list[ModelLabEvidenceSource] = Field(default_factory=list, max_length=6)
    discovery: ModelLabDiscoveryPlan | None = None
    visual_richness: ModelLabVisualRichness | None = None
    check_count: int = Field(default=0, ge=0)
    failed_gates: list[str] = Field(default_factory=list, max_length=20)
    failure_codes: list[str] = Field(default_factory=list, max_length=20)
    artifact_url: str | None = None
    artifact_tier: LabArtifactTier | None = None


class ModelLabPipelineEvent(ClosedModel):
    revision: int = Field(ge=1)
    sequence: int = Field(ge=1)
    stage: LabPipelineStage
    kind: Literal["model", "deterministic", "source"]
    status: LabPipelineEventStatus
    attempt: int = Field(default=1, ge=1)
    model: LabModel | None = None
    effort: LabEffort | None = None
    fast: bool | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)
    output: ModelLabStageOutput = Field(default_factory=ModelLabStageOutput)


class ModelLabPipelineRunResult(ClosedModel):
    contract_version: Literal["1.0"] = "1.0"
    run_id: str
    status: LabPipelineStatus
    revision: int = Field(ge=1)
    active_stage: LabPipelineStage | None = None
    source_mode: LabSourceMode
    visual_mode: LabVisualMode
    stages: ModelLabPipelineStages
    answer: AnswerPayload | None = None
    artifact_url: str | None = None
    artifact_tier: LabArtifactTier | None = None
    timeline: list[ModelLabPipelineEvent] = Field(default_factory=list, max_length=120)


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
    failure_codes: list[str] = field(default_factory=list)
    artifact_tier: LabArtifactTier | None = None
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
            failure_codes=self.failure_codes,
            artifact_tier=self.artifact_tier,
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


@dataclass(slots=True)
class _PipelineVerification:
    passed: bool
    check_count: int
    failures: list[dict[str, Any]]
    artifact: str | None
    deterministic_check_count: int
    deterministic_failures: list[dict[str, Any]]


@dataclass(slots=True)
class _PipelineRun:
    run_id: str
    question: str
    locale: Literal["ar", "en"]
    source_mode: LabSourceMode
    visual_mode: LabVisualMode
    stages: ModelLabPipelineStages
    status: LabPipelineStatus = "queued"
    revision: int = 1
    active_stage: LabPipelineStage | None = None
    timeline: list[ModelLabPipelineEvent] = field(default_factory=list)
    answer: AnswerPayload | None = None
    artifact_url: str | None = None
    artifact_tier: LabArtifactTier | None = None
    evidence: ModelLabEvidenceBundle | None = None
    understanding: dict[str, Any] | None = None
    physics_document: dict[str, Any] | None = None
    physics_failure: dict[str, Any] | None = None
    discovery_plan: ModelLabDiscoveryPlan | None = None
    visual_fragment: dict[str, Any] | None = None
    module_output: dict[str, Any] | None = None
    verification: _PipelineVerification | None = None
    qa_result: dict[str, Any] | None = None

    def public_result(self) -> ModelLabPipelineRunResult:
        return ModelLabPipelineRunResult(
            run_id=self.run_id,
            status=self.status,
            revision=self.revision,
            active_stage=self.active_stage,
            source_mode=self.source_mode,
            visual_mode=self.visual_mode,
            stages=self.stages,
            answer=self.answer,
            artifact_url=self.artifact_url,
            artifact_tier=self.artifact_tier,
            timeline=self.timeline,
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


def _failure_codes(failures: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            f"{gate}:{code}"
            for failure in failures
            if isinstance(failure, dict)
            and isinstance((gate := failure.get("gate")), str)
            and isinstance((code := failure.get("code")), str)
            and gate.replace("_", "").isalnum()
            and code.replace("_", "").isalnum()
        }
    )[:20]


_PREVIEW_BLOCKING_GATES = frozenset(
    {
        "source_size",
        "security",
        "syntax_runtime",
        "assembly",
    }
)
_PREVIEW_BLOCKING_BROWSER_CODES = frozenset(
    {
        "browser_probe_unavailable",
        "browser_probe_timeout",
        "browser_probe_failed",
        "browser_probe_malformed",
        "first_frame_missing",
        "runtime_error_beacon",
        "external_request_observed",
    }
)
_LAB_OPTIONAL_FAILURES = frozenset(
    {
        ("scene_geometry", "scene_samples_missing"),
    }
)


def _preview_blocked_by(failures: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(failure, dict)
        and failure.get("gate") in _PREVIEW_BLOCKING_GATES
        for failure in failures
    )


def _preview_blocked_by_browser(failures: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(failure, dict)
        and failure.get("code") in _PREVIEW_BLOCKING_BROWSER_CODES
        for failure in failures
    )


def _applicable_lab_failures(
    failures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        failure
        for failure in failures
        if not (
            isinstance(failure, dict)
            and (
                failure.get("gate"),
                failure.get("code"),
            )
            in _LAB_OPTIONAL_FAILURES
        )
    ]


class ModelLabManager:
    """Ephemeral A/B generation lab isolated from the learner job pipeline."""

    def __init__(
        self,
        *,
        backend: Any,
        browser_verifier: Callable[[str], BrowserVerificationResult],
        evidence_provider: Any | None = None,
        max_concurrent_runs: int = 1,
    ) -> None:
        self.backend = backend
        self.browser_verifier = browser_verifier
        self.evidence_provider = evidence_provider or DisabledEvidenceProvider()
        self.runs: dict[str, _Run] = {}
        self.pipeline_runs: dict[str, _PipelineRun] = {}
        self.artifacts: dict[str, str] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._pipeline_tasks: dict[str, asyncio.Task[None]] = {}
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

    def get_pipeline(self, run_id: str) -> ModelLabPipelineRunResult | None:
        run = self.pipeline_runs.get(run_id)
        return run.public_result() if run is not None else None

    def start_pipeline(self, payload: ModelLabPipelineRequest) -> ModelLabAccepted:
        run_id = f"labp_{secrets.token_hex(8)}"
        run = _PipelineRun(
            run_id=run_id,
            question=payload.question,
            locale=payload.locale,
            source_mode=payload.source_mode,
            visual_mode=payload.visual_mode,
            stages=payload.stages,
            status="running",
            active_stage="evidence",
        )
        self.pipeline_runs[run_id] = run
        self._schedule_pipeline(run, start_stage="evidence")
        return ModelLabAccepted(
            run_id=run_id,
            status_url=f"/api/model-lab/pipeline/{run_id}",
        )

    def rerun_pipeline(
        self,
        run_id: str,
        payload: ModelLabPipelineRerunRequest,
    ) -> ModelLabAccepted:
        run = self.pipeline_runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status in {"queued", "running"}:
            raise RuntimeError("pipeline_run_in_progress")
        if payload.config is not None:
            run.stages = run.stages.model_copy(
                update={payload.stage: payload.config}
            )
        if payload.source_mode is not None:
            run.source_mode = payload.source_mode
        if payload.visual_mode is not None:
            run.visual_mode = payload.visual_mode
        self._invalidate_pipeline_from(run, payload.stage)
        run.revision += 1
        run.status = "running"
        run.active_stage = payload.stage
        self._schedule_pipeline(run, start_stage=payload.stage)
        return ModelLabAccepted(
            run_id=run_id,
            status_url=f"/api/model-lab/pipeline/{run_id}",
        )

    def _schedule_pipeline(
        self,
        run: _PipelineRun,
        *,
        start_stage: LabPipelineRerunStage,
    ) -> None:
        task = asyncio.create_task(
            self._execute_pipeline(run, start_stage=start_stage)
        )
        self._tasks.add(task)
        self._pipeline_tasks[run.run_id] = task

        def discard(completed: asyncio.Task[None]) -> None:
            self._tasks.discard(completed)
            if self._pipeline_tasks.get(run.run_id) is completed:
                self._pipeline_tasks.pop(run.run_id, None)

        task.add_done_callback(discard)

    async def cancel_pipeline(self, run_id: str) -> ModelLabPipelineRunResult:
        run = self.pipeline_runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        task = self._pipeline_tasks.get(run_id)
        if task is None or task.done():
            return run.public_result()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        run.status = "cancelled"
        run.active_stage = None
        return run.public_result()

    @staticmethod
    def _invalidate_pipeline_from(
        run: _PipelineRun,
        start_stage: LabPipelineRerunStage,
    ) -> None:
        if start_stage == "evidence":
            run.evidence = None
        if start_stage in {"evidence", "understand"}:
            run.understanding = None
            run.answer = None
        if start_stage in {"evidence", "understand", "physics"}:
            run.physics_document = None
            run.physics_failure = None
        if start_stage in {"evidence", "understand", "physics", "plan"}:
            run.discovery_plan = None
        if start_stage in {
            "evidence",
            "understand",
            "physics",
            "plan",
            "visual",
        }:
            run.visual_fragment = None
            run.module_output = None
        if start_stage in {
            "evidence",
            "understand",
            "physics",
            "plan",
            "visual",
            "verify",
        }:
            run.verification = None
        elif start_stage == "browser" and run.verification is not None:
            run.verification.check_count = (
                run.verification.deterministic_check_count
            )
            run.verification.failures = list(
                run.verification.deterministic_failures
            )
            run.verification.passed = False
        if start_stage != "finalize":
            run.qa_result = None
            run.artifact_url = None
            run.artifact_tier = None

    @staticmethod
    def _pipeline_config(
        run: _PipelineRun,
        stage: LabPipelineModelStage,
    ) -> ModelLabStageConfig:
        return getattr(run.stages, stage)

    @staticmethod
    def _start_pipeline_event(
        run: _PipelineRun,
        stage: LabPipelineStage,
        *,
        kind: Literal["model", "deterministic", "source"],
        attempt: int = 1,
        config: ModelLabStageConfig | None = None,
    ) -> ModelLabPipelineEvent:
        event = ModelLabPipelineEvent(
            revision=run.revision,
            sequence=len(run.timeline) + 1,
            stage=stage,
            kind=kind,
            status="running",
            attempt=attempt,
            model=config.model if config is not None else None,
            effort=config.effort if config is not None else None,
            fast=config.fast if config is not None else None,
        )
        run.timeline.append(event)
        run.active_stage = stage
        return event

    @staticmethod
    def _finish_pipeline_event(
        event: ModelLabPipelineEvent,
        *,
        status: Literal["passed", "failed", "skipped"],
        started: float,
        output: ModelLabStageOutput | None = None,
        elapsed_ms: int | None = None,
    ) -> None:
        event.status = status
        event.elapsed_ms = (
            max(0, int((time.monotonic() - started) * 1000))
            if elapsed_ms is None
            else max(0, elapsed_ms)
        )
        if output is not None:
            event.output = output

    def _skip_pipeline_model_stage(
        self,
        run: _PipelineRun,
        stage: Literal["repair_1", "repair_2", "qa"],
        *,
        summary: str,
    ) -> None:
        started = time.monotonic()
        event = self._start_pipeline_event(
            run,
            stage,
            kind="model",
            config=self._pipeline_config(run, stage),
        )
        self._finish_pipeline_event(
            event,
            status="skipped",
            started=started,
            output=ModelLabStageOutput(summary=summary),
        )

    async def cancel_all(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _execute_pipeline(
        self,
        run: _PipelineRun,
        *,
        start_stage: LabPipelineRerunStage,
    ) -> None:
        async with self._run_slots:
            context = RuntimeContext(public=True)
            try:
                await self._execute_pipeline_from(
                    run,
                    start_stage=start_stage,
                    context=context,
                )
            except asyncio.CancelledError:
                run.status = "cancelled"
                raise
            except (
                CodexRuntimeError,
                ContractError,
                ValidationError,
                OSError,
                RuntimeError,
                ValueError,
            ):
                run.status = "failed"
            finally:
                run.active_stage = None

    async def _execute_pipeline_from(
        self,
        run: _PipelineRun,
        *,
        start_stage: LabPipelineRerunStage,
        context: RuntimeContext,
    ) -> None:
        stage_order = {
            "evidence": 0,
            "understand": 1,
            "physics": 2,
            "plan": 3,
            "visual": 4,
            "verify": 5,
            "browser": 6,
            "repair_1": 7,
            "repair_2": 8,
            "qa": 9,
            "finalize": 10,
        }
        start_index = stage_order[start_stage]

        if start_index <= stage_order["evidence"]:
            await self._pipeline_evidence(run)
        if run.evidence is None:
            raise RuntimeError("pipeline_evidence_missing")

        if start_index <= stage_order["understand"]:
            if not await self._pipeline_understand(run, context):
                return
        if run.understanding is None:
            raise RuntimeError("pipeline_understanding_missing")

        if start_index <= stage_order["physics"]:
            await self._pipeline_physics(run, context)
        if run.physics_document is None:
            raise RuntimeError("pipeline_physics_missing")

        if start_index <= stage_order["plan"]:
            self._pipeline_plan(run)
        if run.discovery_plan is None:
            raise RuntimeError("pipeline_discovery_plan_missing")

        if start_index <= stage_order["visual"]:
            if not await self._pipeline_visual(run, context):
                return
        if run.module_output is None:
            raise RuntimeError("pipeline_module_missing")

        if start_stage == "finalize":
            self._pipeline_finalize(run)
            return

        if start_stage == "qa":
            if run.verification is None or not run.verification.passed:
                raise RuntimeError("pipeline_qa_requires_verified_candidate")
            await self._pipeline_qa_and_finalize(run, context, used_repairs=0)
            return

        repair_start = 1
        if start_stage == "repair_2":
            repair_start = 2
        if start_stage in {"repair_1", "repair_2"}:
            if run.verification is None or not run.verification.failures:
                self._skip_pipeline_model_stage(
                    run,
                    start_stage,
                    summary="No current gate failure requires this repair.",
                )
                await self._pipeline_qa_and_finalize(
                    run,
                    context,
                    used_repairs=repair_start,
                )
                return
        elif start_stage == "browser":
            if run.verification is None or run.verification.artifact is None:
                raise RuntimeError("pipeline_browser_artifact_missing")
            await self._pipeline_browser_only(run)
        else:
            await self._pipeline_verify(run)

        used_repairs = repair_start - 1
        for repair_number in range(repair_start, 3):
            stage = f"repair_{repair_number}"
            if run.verification is not None and run.verification.passed:
                self._skip_pipeline_model_stage(
                    run,
                    stage,
                    summary="Verification already passed; repair was not needed.",
                )
                continue
            repaired = await self._pipeline_repair(
                run,
                context,
                repair_number=repair_number,
            )
            used_repairs = repair_number
            if repaired:
                await self._pipeline_verify(run)

        await self._pipeline_qa_and_finalize(
            run,
            context,
            used_repairs=used_repairs,
        )

    async def _pipeline_evidence(self, run: _PipelineRun) -> None:
        started = time.monotonic()
        event = self._start_pipeline_event(
            run,
            "evidence",
            kind="source",
        )
        if run.source_mode == "off":
            evidence = await DisabledEvidenceProvider().collect(
                run.question,
                run.locale,
            )
        else:
            try:
                evidence = await self.evidence_provider.collect(
                    run.question,
                    run.locale,
                )
            except (OSError, RuntimeError, ValueError):
                evidence = ModelLabEvidenceBundle(
                    mode="public_references",
                    locale=run.locale,
                    status="unavailable",
                    sources=[],
                )
        run.evidence = evidence
        status: Literal["passed", "failed", "skipped"]
        if evidence.status == "ready":
            status = "passed"
            summary = "Public reference evidence is ready for the understanding stage."
        elif evidence.status == "skipped":
            status = "skipped"
            summary = "External reference lookup is off for this run."
        else:
            status = "failed"
            summary = "Reference lookup was unavailable; the isolated run continues ungrounded."
        self._finish_pipeline_event(
            event,
            status=status,
            started=started,
            output=ModelLabStageOutput(
                summary=summary,
                sources=list(evidence.sources),
            ),
        )

    async def _pipeline_understand(
        self,
        run: _PipelineRun,
        context: RuntimeContext,
    ) -> bool:
        if run.evidence is None:
            raise RuntimeError("pipeline_evidence_missing")
        config = run.stages.understand
        started = time.monotonic()
        event = self._start_pipeline_event(
            run,
            "understand",
            kind="model",
            config=config,
        )
        try:
            result = await self.backend.understand_for_lab(
                run.question,
                run.locale,
                model=config.model,
                effort=config.effort,
                fast=config.fast,
                evidence=run.evidence.model_dump(mode="json"),
                runtime_context=context,
            )
            understanding = validate_understanding(_stage_data(result))
        except (
            CodexRuntimeError,
            ContractError,
            ValidationError,
            OSError,
            ValueError,
        ):
            self._finish_pipeline_event(
                event,
                status="failed",
                started=started,
                output=ModelLabStageOutput(summary="Understanding failed."),
            )
            run.status = "failed"
            return False

        run.understanding = understanding
        run.answer = AnswerPayload(
            tldr=understanding["tldr"],
            key_formula=understanding.get("key_formula"),
        )
        details = [
            value
            for value in (
                understanding.get("title"),
                understanding.get("learning_objective"),
                understanding.get("misconception"),
            )
            if isinstance(value, str) and value
        ]
        self._finish_pipeline_event(
            event,
            status="passed",
            started=started,
            elapsed_ms=_stage_elapsed(result, 0),
            output=ModelLabStageOutput(
                summary=understanding["tldr"],
                formula=understanding.get("key_formula"),
                details=details[:12],
                output_names=list(understanding["module_spec"]["outputs"]),
                check_count=len(understanding["checks"]),
            ),
        )
        if understanding["safe"] is not True:
            run.status = "rejected"
            return False
        if understanding["simulatable"] is not True:
            run.status = "rejected"
            return False
        return True

    def _pipeline_plan(self, run: _PipelineRun) -> None:
        if (
            run.understanding is None
            or run.physics_document is None
            or run.evidence is None
        ):
            raise RuntimeError("pipeline_plan_dependencies_missing")
        started = time.monotonic()
        event = self._start_pipeline_event(
            run,
            "plan",
            kind="deterministic",
        )
        try:
            plan = build_discovery_plan(
                run.understanding,
                run.physics_document,
                source_ids=[
                    source.source_id for source in run.evidence.sources
                ],
            )
        except (ContractError, ValidationError, ValueError):
            self._finish_pipeline_event(
                event,
                status="failed",
                started=started,
                output=ModelLabStageOutput(
                    summary="The discovery plan could not be derived from the fixed contract.",
                    failed_gates=["discovery_plan"],
                    failure_codes=["discovery_plan:invalid_fixed_inputs"],
                ),
            )
            run.discovery_plan = None
            return
        run.discovery_plan = plan
        self._finish_pipeline_event(
            event,
            status="passed",
            started=started,
            output=ModelLabStageOutput(
                summary=(
                    "A language-neutral discovery loop and scientific "
                    "representation were derived locally."
                ),
                details=[
                    plan.learning_cycle.prediction,
                    plan.learning_cycle.observe,
                    plan.learning_cycle.explain,
                    plan.learning_cycle.transfer,
                ],
                discovery=plan,
            ),
        )

    async def _pipeline_physics(
        self,
        run: _PipelineRun,
        context: RuntimeContext,
    ) -> None:
        if run.understanding is None:
            raise RuntimeError("pipeline_understanding_missing")
        config = run.stages.physics
        started = time.monotonic()
        event = self._start_pipeline_event(
            run,
            "physics",
            kind="model",
            config=config,
        )
        result = await self.backend.generate_physics_for_lab(
            run.understanding,
            stage_spec=StageModelSpec(config.model, config.effort, config.fast),
            runtime_context=context,
        )
        document = _stage_data(result)
        run.physics_document = document
        run.physics_failure = None
        status: Literal["passed", "failed"] = "passed"
        try:
            validate_physics_fragment(document, run.understanding)
        except (ContractError, ValidationError, ValueError) as error:
            run.physics_failure = fragment_failure_diagnostic(
                error,
                role="physics",
                understanding=run.understanding,
            )
            status = "failed"
        expressions = [
            f"{item['name']} = {item['expression']}"
            for item in document.get("physics_expressions", [])
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("expression"), str)
        ]
        self._finish_pipeline_event(
            event,
            status=status,
            started=started,
            elapsed_ms=_stage_elapsed(result, 0),
            output=ModelLabStageOutput(
                summary=document.get("brief_summary"),
                assumptions=list(document.get("assumptions", []))[:8],
                expressions=expressions[:8],
                output_names=list(document.get("output_names", []))[:8],
                failed_gates=(
                    [run.physics_failure["gate"]]
                    if run.physics_failure is not None
                    else []
                ),
                failure_codes=(
                    [
                        "physics:"
                        + str(run.physics_failure.get("code", "contract_invalid"))
                    ]
                    if run.physics_failure is not None
                    else []
                ),
            ),
        )

    async def _pipeline_visual(
        self,
        run: _PipelineRun,
        context: RuntimeContext,
    ) -> bool:
        if (
            run.understanding is None
            or run.physics_document is None
            or run.discovery_plan is None
        ):
            raise RuntimeError("pipeline_visual_dependencies_missing")
        config = run.stages.visual
        started = time.monotonic()
        event = self._start_pipeline_event(
            run,
            "visual",
            kind="model",
            config=config,
        )
        try:
            stage_spec = StageModelSpec(
                config.model,
                config.effort,
                config.fast,
            )
            discovery_document = run.discovery_plan.model_dump(mode="json")
            if run.visual_mode == "hybrid_race":
                async def trusted_candidate() -> tuple[
                    str,
                    dict[str, Any] | None,
                    dict[str, Any],
                    dict[str, Any] | StageExecution,
                ]:
                    trusted_result = await self.backend.generate_visual_plan_for_lab(
                        run.understanding,
                        run.physics_document,
                        discovery_document,
                        stage_spec=stage_spec,
                        runtime_context=context,
                    )
                    trusted_fragment = validate_visual_fragment(
                        _stage_data(trusted_result),
                        run.understanding,
                    )
                    return (
                        "trusted_scene_plan",
                        trusted_fragment,
                        assemble_fragments(
                            run.physics_document,
                            trusted_fragment,
                            run.understanding,
                        ),
                        trusted_result,
                    )

                async def direct_candidate() -> tuple[
                    str,
                    None,
                    dict[str, Any],
                    dict[str, Any] | StageExecution,
                ]:
                    direct_result = await self.backend.generate_visual_module_for_lab(
                        run.understanding,
                        run.physics_document,
                        stage_spec=stage_spec,
                        discovery_plan=discovery_document,
                        runtime_context=context,
                    )
                    return (
                        "direct_canvas",
                        None,
                        validate_module_output(_stage_data(direct_result)),
                        direct_result,
                    )

                raw_candidates = await asyncio.gather(
                    trusted_candidate(),
                    direct_candidate(),
                    return_exceptions=True,
                )
                candidates = [
                    candidate
                    for candidate in raw_candidates
                    if not isinstance(candidate, BaseException)
                ]
                if not candidates:
                    raise ContractError("both hybrid visual strategies failed")
                reports = await asyncio.gather(
                    *(
                        asyncio.to_thread(
                            verify_candidate,
                            candidate[2],
                            run.understanding,
                        )
                        for candidate in candidates
                    ),
                    return_exceptions=True,
                )

                def candidate_rank(index: int) -> tuple[int, int, int]:
                    candidate = candidates[index]
                    report = reports[index]
                    if isinstance(report, BaseException):
                        return (0, -1_000, 0)
                    failures = _applicable_lab_failures(report.failures)
                    passed = report.artifact is not None and not failures
                    return (
                        int(passed),
                        -len(failures),
                        int(candidate[0] == "direct_canvas"),
                    )

                selected_index = max(
                    range(len(candidates)),
                    key=candidate_rank,
                )
                selected_strategy, visual_fragment, module_output, result = (
                    candidates[selected_index]
                )
                run.visual_fragment = visual_fragment
                strategy_details = [
                    f"{len(candidates)} parallel visual strategies",
                    f"selected {selected_strategy}",
                ]
            elif run.visual_mode == "trusted_scene_plan":
                result = await self.backend.generate_visual_plan_for_lab(
                    run.understanding,
                    run.physics_document,
                    discovery_document,
                    stage_spec=stage_spec,
                    runtime_context=context,
                )
                visual_fragment = validate_visual_fragment(
                    _stage_data(result),
                    run.understanding,
                )
                run.visual_fragment = visual_fragment
                module_output = assemble_fragments(
                    run.physics_document,
                    visual_fragment,
                    run.understanding,
                )
                strategy_details = ["selected trusted_scene_plan"]
            else:
                result = await self.backend.generate_visual_module_for_lab(
                    run.understanding,
                    run.physics_document,
                    stage_spec=stage_spec,
                    discovery_plan=discovery_document,
                    runtime_context=context,
                )
                run.visual_fragment = None
                module_output = validate_module_output(_stage_data(result))
                strategy_details = ["selected direct_canvas"]
        except (
            CodexRuntimeError,
            ContractError,
            ValidationError,
            OSError,
            ValueError,
        ):
            self._finish_pipeline_event(
                event,
                status="failed",
                started=started,
                output=ModelLabStageOutput(
                    summary="The visual stage did not return a valid module contract.",
                    failed_gates=["generation_contract"],
                    failure_codes=["generation_contract:module_output_invalid"],
                ),
            )
            run.status = "failed"
            return False
        run.module_output = module_output
        self._finish_pipeline_event(
            event,
            status="passed",
            started=started,
            elapsed_ms=_stage_elapsed(result, 0),
            output=ModelLabStageOutput(
                summary=(
                    f"{module_output['brief_summary']} "
                    f"Representation: {run.discovery_plan.representation.family}."
                ),
                assumptions=list(module_output["assumptions"])[:8],
                output_names=list(module_output["output_names"])[:8],
                details=strategy_details,
                discovery=run.discovery_plan,
            ),
        )
        return True

    async def _pipeline_verify(self, run: _PipelineRun) -> None:
        if run.understanding is None or run.module_output is None:
            raise RuntimeError("pipeline_verification_dependencies_missing")
        started = time.monotonic()
        attempt = 1 + sum(
            event.stage == "verify" and event.revision == run.revision
            for event in run.timeline
        )
        event = self._start_pipeline_event(
            run,
            "verify",
            kind="deterministic",
            attempt=attempt,
        )
        deterministic: VerificationResult = await asyncio.to_thread(
            verify_candidate,
            run.module_output,
            run.understanding,
        )
        failures = _applicable_lab_failures(deterministic.failures)
        if run.physics_failure is not None:
            failures = [run.physics_failure, *failures]
        check_count = deterministic.check_count + (
            1 if run.physics_failure is not None else 0
        )
        artifact = deterministic.artifact
        if artifact is None and not _preview_blocked_by(deterministic.failures):
            try:
                from server.assemble import assemble_artifact

                artifact = assemble_artifact(
                    run.understanding,
                    run.module_output,
                )
                artifact_failures, artifact_checks = verify_artifact_contract(
                    artifact,
                    run.understanding,
                    run.module_output["module_js"],
                )
                check_count += artifact_checks
                failures.extend(artifact_failures)
                if artifact_failures:
                    artifact = None
            except (OSError, ValueError):
                artifact = None

        if _preview_blocked_by(failures):
            artifact = None
        run.verification = _PipelineVerification(
            passed=not failures and artifact is not None,
            check_count=check_count,
            failures=failures,
            artifact=artifact,
            deterministic_check_count=check_count,
            deterministic_failures=list(failures),
        )
        self._finish_pipeline_event(
            event,
            status="passed" if run.verification.passed else "failed",
            started=started,
            output=ModelLabStageOutput(
                summary=(
                    "All deterministic gates passed."
                    if run.verification.passed
                    else "Deterministic gates reported actionable failures."
                ),
                check_count=check_count,
                failed_gates=_gate_names(failures),
                failure_codes=_failure_codes(failures),
            ),
        )
        await self._pipeline_browser_only(run)

    async def _pipeline_browser_only(self, run: _PipelineRun) -> None:
        started = time.monotonic()
        attempt = 1 + sum(
            event.stage == "browser" and event.revision == run.revision
            for event in run.timeline
        )
        event = self._start_pipeline_event(
            run,
            "browser",
            kind="deterministic",
            attempt=attempt,
        )
        if run.verification is None or run.verification.artifact is None:
            self._finish_pipeline_event(
                event,
                status="skipped",
                started=started,
                output=ModelLabStageOutput(
                    summary="No safe artifact was available for browser verification."
                ),
            )
            return
        try:
            async with self._browser_slots:
                browser: BrowserVerificationResult = await asyncio.to_thread(
                    self.browser_verifier,
                    run.verification.artifact,
                )
        except (OSError, RuntimeError, ValueError):
            browser_failure = {
                "gate": "browser_readiness",
                "code": "browser_probe_failed",
                "expected": {"browser_probe": "completed"},
                "actual": {"browser_probe": "failed"},
            }
            run.verification.failures.append(browser_failure)
            run.verification.passed = False
            run.verification.artifact = None
            self._finish_pipeline_event(
                event,
                status="failed",
                started=started,
                output=ModelLabStageOutput(
                    summary="Browser verification could not complete.",
                    failed_gates=["browser_readiness"],
                    failure_codes=["browser_readiness:browser_probe_failed"],
                ),
            )
            return

        run.verification.check_count += browser.check_count
        if browser.failures:
            run.verification.failures.extend(browser.failures)
        if _preview_blocked_by_browser(browser.failures):
            run.verification.artifact = None
        run.verification.passed = (
            not run.verification.failures
            and browser.passed
            and run.verification.artifact is not None
        )
        self._finish_pipeline_event(
            event,
            status="passed" if browser.passed else "failed",
            started=started,
            output=ModelLabStageOutput(
                summary=(
                    "The simulation rendered and responded in the browser."
                    if browser.passed
                    else "Browser checks reported visible or runtime issues."
                ),
                check_count=browser.check_count,
                failed_gates=_gate_names(browser.failures),
                failure_codes=_failure_codes(browser.failures),
            ),
        )

    async def _pipeline_repair(
        self,
        run: _PipelineRun,
        context: RuntimeContext,
        *,
        repair_number: int,
    ) -> bool:
        stage: Literal["repair_1", "repair_2"] = (
            "repair_1" if repair_number == 1 else "repair_2"
        )
        if (
            run.understanding is None
            or run.module_output is None
            or run.verification is None
            or not run.verification.failures
        ):
            self._skip_pipeline_model_stage(
                run,
                stage,
                summary="No current gate failure requires this repair.",
            )
            return False
        config = self._pipeline_config(run, stage)
        started = time.monotonic()
        event = self._start_pipeline_event(
            run,
            stage,
            kind="model",
            attempt=repair_number,
            config=config,
        )
        try:
            result = await self.backend.heal_for_lab(
                run.module_output,
                run.understanding,
                run.verification.failures,
                repair_number,
                stage_spec=StageModelSpec(
                    config.model,
                    config.effort,
                    config.fast,
                ),
                runtime_context=context,
            )
            module_output = validate_module_output(_stage_data(result))
        except (
            CodexRuntimeError,
            ContractError,
            ValidationError,
            OSError,
            ValueError,
        ):
            self._finish_pipeline_event(
                event,
                status="failed",
                started=started,
                output=ModelLabStageOutput(
                    summary="The repair stage did not return a valid module.",
                    failed_gates=["generation_contract"],
                    failure_codes=["generation_contract:repair_output_invalid"],
                ),
            )
            return False
        run.module_output = module_output
        self._finish_pipeline_event(
            event,
            status="passed",
            started=started,
            elapsed_ms=_stage_elapsed(result, 0),
            output=ModelLabStageOutput(
                summary=module_output["brief_summary"],
                assumptions=list(module_output["assumptions"])[:8],
                output_names=list(module_output["output_names"])[:8],
            ),
        )
        return True

    async def _pipeline_qa_and_finalize(
        self,
        run: _PipelineRun,
        context: RuntimeContext,
        *,
        used_repairs: int,
    ) -> None:
        if run.verification is None or not run.verification.passed:
            self._skip_pipeline_model_stage(
                run,
                "qa",
                summary=(
                    "QA waits for a candidate that passes deterministic "
                    "and browser gates."
                ),
            )
            self._pipeline_finalize(run)
            return

        if run.visual_mode == "hybrid_race" and used_repairs == 0:
            self._skip_pipeline_model_stage(
                run,
                "qa",
                summary=(
                    "First-pass hybrid winner passed deterministic and browser "
                    "gates; no extra QA model call was needed."
                ),
            )
            self._pipeline_finalize(run)
            return

        approved = await self._pipeline_qa(run, context)
        if not approved and used_repairs < 2 and run.qa_result is not None:
            qa_failure = {
                "gate": "qa_review",
                "code": "qa_revision_requested",
                "expected": {
                    "approved": True,
                    "issues": [],
                    "visual_richness": {
                        name: True
                        for name in run.qa_result["visual_richness"]
                    },
                },
                "actual": {
                    "approved": False,
                    "issues": run.qa_result["issues"],
                    "visual_richness": run.qa_result["visual_richness"],
                },
            }
            run.verification.failures = [qa_failure]
            run.verification.passed = False
            repair_number = used_repairs + 1
            if await self._pipeline_repair(
                run,
                context,
                repair_number=repair_number,
            ):
                await self._pipeline_verify(run)
                if run.verification.passed:
                    await self._pipeline_qa(run, context)
        self._pipeline_finalize(run)

    async def _pipeline_qa(
        self,
        run: _PipelineRun,
        context: RuntimeContext,
    ) -> bool:
        if (
            run.understanding is None
            or run.module_output is None
            or run.verification is None
        ):
            raise RuntimeError("pipeline_qa_dependencies_missing")
        config = run.stages.qa
        started = time.monotonic()
        attempt = 1 + sum(
            event.stage == "qa" and event.revision == run.revision
            for event in run.timeline
        )
        event = self._start_pipeline_event(
            run,
            "qa",
            kind="model",
            attempt=attempt,
            config=config,
        )
        gate_outcome = {
            "passed": run.verification.passed,
            "check_count": run.verification.check_count,
            "gate_names": [
                "assembly",
                "interface",
                "invariant",
                "runtime_init",
                "security",
                "source_size",
                "syntax_runtime",
                "browser_readiness",
            ],
        }
        try:
            result = await self.backend.qa_for_lab(
                run.module_output,
                run.understanding,
                gate_outcome,
                stage_spec=StageModelSpec(
                    config.model,
                    config.effort,
                    config.fast,
                ),
                runtime_context=context,
            )
            qa_result = validate_document(
                _stage_data(result),
                load_schema("qa.schema.json"),
            )
        except (
            CodexRuntimeError,
            ValidationError,
            OSError,
            ValueError,
        ):
            self._finish_pipeline_event(
                event,
                status="failed",
                started=started,
                output=ModelLabStageOutput(
                    summary="QA did not return a valid verdict."
                ),
            )
            run.qa_result = None
            return False
        run.qa_result = qa_result
        approved = qa_result["approved"] is True
        self._finish_pipeline_event(
            event,
            status="passed" if approved else "failed",
            started=started,
            elapsed_ms=_stage_elapsed(result, 0),
            output=ModelLabStageOutput(
                summary=(
                    "QA approved the verified candidate."
                    if approved
                    else "QA requested a bounded revision."
                ),
                issues=list(qa_result["issues"])[:3],
                visual_richness=ModelLabVisualRichness(
                    **qa_result["visual_richness"]
                ),
            ),
        )
        return approved

    def _pipeline_finalize(self, run: _PipelineRun) -> None:
        started = time.monotonic()
        event = self._start_pipeline_event(
            run,
            "finalize",
            kind="deterministic",
        )
        verification = run.verification
        artifact = verification.artifact if verification is not None else None
        if artifact is None:
            run.artifact_url = None
            run.artifact_tier = None
            run.status = "rejected"
            self._finish_pipeline_event(
                event,
                status="failed",
                started=started,
                output=ModelLabStageOutput(
                    summary="No safe artifact was available to display."
                ),
            )
            return

        artifact_id = f"{run.run_id}_pipeline_r{run.revision}"
        self.artifacts[artifact_id] = artifact
        run.artifact_url = f"/api/model-lab/artifacts/{artifact_id}"
        qa_approved = (
            run.qa_result is not None and run.qa_result.get("approved") is True
        )
        qa_not_required = (
            run.visual_mode == "hybrid_race"
            and run.verification.passed
            and not any(
                event.stage in {"repair_1", "repair_2"}
                and event.status == "passed"
                and event.revision == run.revision
                for event in run.timeline
            )
        )
        run.artifact_tier = (
            "verified"
            if verification.passed and (qa_approved or qa_not_required)
            else "unverified_preview"
        )
        run.status = "complete"
        self._finish_pipeline_event(
            event,
            status="passed",
            started=started,
            output=ModelLabStageOutput(
                summary=(
                    "A verified artifact is ready."
                    if run.artifact_tier == "verified"
                    else "A safe, explicitly unverified preview is ready."
                ),
                check_count=verification.check_count,
                failed_gates=_gate_names(verification.failures),
                failure_codes=_failure_codes(verification.failures),
                artifact_url=run.artifact_url,
                artifact_tier=run.artifact_tier,
            ),
        )

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
                            fast=run.understand_config.fast,
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
            fast=candidate.config.physics.fast,
        )
        visual_spec = StageModelSpec(
            model=candidate.config.visual.model,
            effort=candidate.config.visual.effort,
            fast=candidate.config.visual.fast,
        )
        try:
            physics_result, module_result = (
                await self.backend.generate_direct_module_for_lab(
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
        candidate.visual_elapsed_ms = _stage_elapsed(module_result, elapsed)
        physics_document = _stage_data(physics_result)
        module_document = _stage_data(module_result)
        physics_semantic_failure: dict[str, Any] | None = None
        try:
            validate_physics_fragment(
                physics_document,
                understanding,
            )
        except (ContractError, ValidationError, ValueError) as error:
            physics_semantic_failure = fragment_failure_diagnostic(
                error,
                role="physics",
                understanding=understanding,
            )
            candidate.failed_gates = [physics_semantic_failure["gate"]]
            candidate.failure_codes = [
                f"physics:{physics_semantic_failure['code']}"
            ]
            candidate.check_count = 1
        except OSError:
            candidate.status = "failed"
            return

        try:
            module_output = validate_module_output(module_document)
        except (ContractError, ValidationError, ValueError):
            candidate.failed_gates = ["generation_contract"]
            candidate.failure_codes = ["generation_contract:module_output_invalid"]
            candidate.check_count += 1
            candidate.status = "rejected"
            return

        candidate.status = "verifying"
        verification_started = time.monotonic()
        deterministic: VerificationResult = await asyncio.to_thread(
            verify_candidate,
            module_output,
            understanding,
        )
        candidate.check_count += deterministic.check_count
        deterministic_failures = _applicable_lab_failures(
            deterministic.failures
        )
        combined_failures = list(deterministic_failures)
        if physics_semantic_failure is not None:
            combined_failures.insert(0, physics_semantic_failure)
        candidate.failed_gates = _gate_names(combined_failures)
        candidate.failure_codes = sorted(
            set([*candidate.failure_codes, *_failure_codes(deterministic_failures)])
        )[:20]

        artifact = deterministic.artifact
        if artifact is None and not _preview_blocked_by(deterministic.failures):
            try:
                from server.assemble import assemble_artifact

                artifact = assemble_artifact(understanding, module_output)
                artifact_failures, artifact_checks = verify_artifact_contract(
                    artifact,
                    understanding,
                    module_output["module_js"],
                )
                candidate.check_count += artifact_checks
                if artifact_failures:
                    artifact = None
                    candidate.failed_gates = sorted(
                        set(
                            [
                                *candidate.failed_gates,
                                *_gate_names(artifact_failures),
                            ]
                        )
                    )[:20]
                    candidate.failure_codes = sorted(
                        set(
                            [
                                *candidate.failure_codes,
                                *_failure_codes(artifact_failures),
                            ]
                        )
                    )[:20]
            except (OSError, ValueError):
                artifact = None
        if artifact is None:
            candidate.verification_elapsed_ms = int(
                (time.monotonic() - verification_started) * 1000
            )
            candidate.status = "rejected"
            return

        try:
            async with self._browser_slots:
                browser: BrowserVerificationResult = await asyncio.to_thread(
                    self.browser_verifier,
                    artifact,
                )
        except (OSError, RuntimeError, ValueError):
            candidate.verification_elapsed_ms = int(
                (time.monotonic() - verification_started) * 1000
            )
            candidate.status = "failed"
            return
        candidate.check_count += browser.check_count
        if browser.failures:
            candidate.failed_gates = sorted(
                set([*candidate.failed_gates, *_gate_names(browser.failures)])
            )[:20]
            candidate.failure_codes = sorted(
                set([*candidate.failure_codes, *_failure_codes(browser.failures)])
            )[:20]
        if _preview_blocked_by_browser(browser.failures):
            candidate.verification_elapsed_ms = int(
                (time.monotonic() - verification_started) * 1000
            )
            candidate.status = "rejected"
            return

        artifact_id = f"{run.run_id}_{candidate.slot.lower()}"
        self.artifacts[artifact_id] = artifact
        candidate.artifact_url = f"/api/model-lab/artifacts/{artifact_id}"
        candidate.verification_elapsed_ms = int(
            (time.monotonic() - verification_started) * 1000
        )
        if (
            physics_semantic_failure is None
            and not deterministic_failures
            and browser.passed
        ):
            candidate.status = "verified"
            candidate.artifact_tier = "verified"
        else:
            candidate.status = "unverified"
            candidate.artifact_tier = "unverified_preview"
