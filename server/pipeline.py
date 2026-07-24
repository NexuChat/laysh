from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any, NoReturn

from jsonschema import ValidationError

from server.cache import VerificationReceipt
from server.codex_backend import GenerationCandidateSpec, RuntimeContext
from server.codex_runtime import CodexRuntimeError, StageExecution
from server.fragment_generation import (
    assemble_fragments,
    fragment_failure_code,
    fragment_failure_diagnostic,
    repair_visual_causal_response,
    validate_physics_fragment,
    validate_visual_fragment,
)
from server.model_lab_discovery import build_discovery_plan
from server.privacy import contains_learner_question_echo
from server.promotion import STABLE_ROUTE
from server.schemas import (
    AnswerPayload,
    ContractError,
    FallbackResult,
    RuntimeStageReceipt,
    SimulationMetadata,
    validate_module_output,
    validate_understanding,
)
from server.verify import VerificationResult, formula_presentation_report, verify_candidate

logger = logging.getLogger(__name__)


LIVE_DETERMINISTIC_PASSED_GATES = frozenset(
    {
        "closed_schema",
        "restricted_source",
        "node_runtime",
        "fixtures",
    }
)


@dataclass(frozen=True, slots=True)
class _FreshComparisonDecision:
    approved: bool
    reason_code: str


def _live_browser_checks_pass(evidence: dict[str, Any] | None) -> bool:
    """Check only the browser evidence available to live fresh rebuilds."""

    if not isinstance(evidence, dict):
        return False
    return (
        evidence.get("ready") is True
        and evidence.get("controlChanged") is True
        and evidence.get("frameChanged") is True
        and isinstance(evidence.get("canvasHashBefore"), int)
        and isinstance(evidence.get("canvasHashAfter"), int)
        and evidence["canvasHashBefore"] != evidence["canvasHashAfter"]
        and evidence.get("runtimeError") is False
        and evidence.get("externalRequests") == 0
    )


def _compare_fresh_candidate(
    incumbent: Any,
    candidate_receipt: VerificationReceipt,
    browser_evidence: dict[str, Any] | None,
) -> _FreshComparisonDecision:
    """Fail closed for fresh jobs without importing the offline promotion gate."""

    incumbent_receipt = getattr(incumbent, "receipt", None)
    incumbent_tier = getattr(incumbent, "tier", None)
    if incumbent_receipt is None or not incumbent_receipt.verified:
        return _FreshComparisonDecision(False, "missing_incumbent_evidence")
    if {"A": 2, "B": 1}.get("B", 0) < {"A": 2, "B": 1}.get(incumbent_tier, 0):
        return _FreshComparisonDecision(False, "candidate_tier_regression")
    if not (
        candidate_receipt.deterministic_passed
        and candidate_receipt.failed_gate_count == 0
        and LIVE_DETERMINISTIC_PASSED_GATES.issuperset(
            incumbent_receipt.passed_gates
        )
    ):
        return _FreshComparisonDecision(False, "deterministic_regression")
    if not candidate_receipt.browser_passed or not _live_browser_checks_pass(
        browser_evidence
    ):
        return _FreshComparisonDecision(False, "browser_regression")
    if candidate_receipt.check_count < incumbent_receipt.check_count:
        return _FreshComparisonDecision(False, "check_count_regression")
    return _FreshComparisonDecision(True, "approved")


class PipelineCancelled(Exception):
    pass


@dataclass(slots=True)
class _CandidateOutcome:
    spec: GenerationCandidateSpec
    module_output: dict[str, Any] | None = None
    verification: VerificationResult | None = None
    browser_evidence: dict[str, Any] | None = None
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class _QaVerifiedCandidate:
    module_output: dict[str, Any]
    verification: VerificationResult
    browser_evidence: dict[str, Any] | None
    qa_outcome: dict[str, Any]


async def cancellable_sleep(seconds: float) -> None:
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError as error:
        raise PipelineCancelled from error


def _fallback(manager: Any, record: Any, reason_code: str, suggestions: list[str]) -> None:
    record.fallback = FallbackResult(reason_code=reason_code, suggestions=suggestions[:3])
    manager.emit(
        record,
        "fallback",
        {"reason_code": reason_code, "suggestions": suggestions[:3]},
    )
    manager.transition(record, "answer_only", reason_code)


def _gallery_suggestions(locale: str | None) -> list[str]:
    if locale == "en":
        return ["Why does the Moon change shape?", "Why do some objects float?"]
    return ["لماذا يتغير شكل القمر؟", "لماذا تطفو بعض الأجسام؟"]


def _safe_answer_slice(document: Any) -> AnswerPayload | None:
    """Keep only an independently safe answer when simulation fields are malformed."""

    if not isinstance(document, dict) or document.get("safe") is not True:
        return None
    tldr = document.get("tldr")
    if not isinstance(tldr, str) or not tldr.strip():
        return None
    key_formula = document.get("key_formula")
    if not isinstance(key_formula, str):
        key_formula = None
    elif formula_presentation_report({"key_formula": key_formula})[0]:
        key_formula = None
    return AnswerPayload(tldr=tldr.strip(), key_formula=key_formula)


def _reject(manager: Any, record: Any, reason_code: str, suggestions: list[str]) -> NoReturn:
    record.fallback = FallbackResult(reason_code=reason_code, suggestions=suggestions[:3])
    manager.emit(
        record,
        "fallback",
        {"reason_code": reason_code, "suggestions": suggestions[:3]},
    )
    manager.terminal(record, "rejected", reason_code)
    raise PipelineCancelled


async def run_pipeline(manager: Any, record: Any) -> None:
    question = record.question or ""
    scenario_resolver = getattr(manager.backend, "scenario_for", None)
    scenario = scenario_resolver(question) if scenario_resolver else "live"
    runtime_context = RuntimeContext(
        public=record.public,
        evidence_fixture_id=record.evidence_fixture_id,
    )

    def receipt_stage_name(stage: str) -> str:
        return {
            "understand": "understand",
            "understand_retry": "understand",
            "generate": "generate",
            "generate_physics": "generate",
            "generate_visual": "generate",
            "heal_1": "heal",
            "heal_2": "heal",
            "qa": "qa",
            "qa_retry": "qa",
        }[stage]

    def next_receipt_attempt(stage: str) -> int:
        return sum(receipt.stage == stage for receipt in record.runtime_receipts) + 1

    def record_stage_attempt(
        *,
        stage: str,
        model: str,
        outcome: str,
        elapsed_ms: int | None,
        failure_code: str | None,
        thread_id: str | None,
        candidate_id: str | None = None,
        fragment_role: str | None = None,
    ) -> None:
        attempt = next_receipt_attempt(stage)
        execution = {
            "stage": stage,
            "attempt": attempt,
            "model": model,
            "outcome": outcome,
            "elapsed_ms": elapsed_ms,
            "failure_code": failure_code,
            "thread_id": thread_id,
        }
        if candidate_id is not None:
            execution["candidate_id"] = candidate_id
        if fragment_role is not None:
            execution["fragment_role"] = fragment_role
        record.stage_executions.append(execution)
        record.runtime_receipts.append(
            RuntimeStageReceipt(
                stage=stage,
                attempt=attempt,
                model=model,
                outcome=outcome,
                elapsed_ms=elapsed_ms,
                failure_code=failure_code,
            )
        )

    def stage_data(
        result: dict[str, Any] | StageExecution,
        stage: str,
        candidate_spec: GenerationCandidateSpec | None = None,
        fragment_role: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(result, StageExecution):
            stage_name = receipt_stage_name(stage)
            attempted_models = result.attempted_models or (result.model,)
            prior_failure_codes = result.prior_failure_codes
            for index, model in enumerate(attempted_models):
                completed = index == len(attempted_models) - 1
                failure_code = (
                    None
                    if completed
                    else prior_failure_codes[index]
                    if index < len(prior_failure_codes)
                    else "runtime_error"
                )
                elapsed_ms = result.elapsed_ms if completed else None
                record_stage_attempt(
                    stage=stage_name,
                    model=model,
                    outcome="completed" if completed else "failed",
                    elapsed_ms=elapsed_ms,
                    failure_code=failure_code,
                    thread_id=result.thread_id if completed else None,
                    candidate_id=(
                        candidate_spec.candidate_id if candidate_spec is not None else None
                    ),
                    fragment_role=fragment_role,
                )
            return result.data
        return result

    def record_stage_failure(
        stage: str,
        error: CodexRuntimeError,
        candidate_spec: GenerationCandidateSpec | None = None,
    ) -> None:
        model = error.safe_detail.get("model")
        if not isinstance(model, str):
            return
        record_stage_attempt(
            stage=receipt_stage_name(stage),
            model=model,
            outcome="failed",
            elapsed_ms=None,
            failure_code=error.code,
            thread_id=None,
            candidate_id=(
                candidate_spec.candidate_id if candidate_spec is not None else None
            ),
        )

    async def stage_result(
        stage: str,
        operation: Any,
        candidate_spec: GenerationCandidateSpec | None = None,
    ) -> dict[str, Any]:
        try:
            return stage_data(await operation, stage, candidate_spec)
        except CodexRuntimeError as error:
            record_stage_failure(stage, error, candidate_spec)
            raise

    def record_verification_failure(
        result: VerificationResult,
        heal_count: int,
    ) -> None:
        gate_names = sorted({failure["gate"] for failure in result.failures})
        logger.warning(
            "verification rejected job=%s heal_count=%s failures=%s",
            record.job_id,
            heal_count,
            [
                {
                    "gate": failure.get("gate"),
                    "code": failure.get("code"),
                }
                for failure in result.failures
            ],
        )
        manager.emit(
            record,
            "verification",
            {
                "passed": False,
                "check_count": result.check_count,
                "heal_count": heal_count,
                "evidence": gate_names,
            },
        )
        if not record.public:
            record.builder_diagnostics.append(
                {
                    "type": "verification_failure",
                    "attempt": heal_count,
                    "check_count": result.check_count,
                    "failures": result.failures,
                }
            )

    def qa_revision_result(
        verification: VerificationResult,
        qa_result: dict[str, Any],
    ) -> VerificationResult:
        visual_richness = qa_result["visual_richness"]
        return VerificationResult(
            passed=False,
            check_count=verification.check_count,
            failures=[
                {
                    "gate": "qa_review",
                    "code": "qa_revision_requested",
                    "expected": {
                        "approved": True,
                        "issues": [],
                        "visual_richness": {
                            name: True for name in visual_richness
                        },
                    },
                    "actual": {
                        "approved": False,
                        "issues": qa_result["issues"],
                        "visual_richness": visual_richness,
                    },
                }
            ],
            artifact=None,
            node_report=verification.node_report,
        )

    async def verify_generated_module(
        module_output: dict[str, Any],
        understanding: dict[str, Any],
    ) -> tuple[VerificationResult, dict[str, Any] | None]:
        causal_marker_present = (
            "/* LAYSH_CAUSAL_RESPONSE_V1 */" in module_output["module_js"]
        )
        causal_contract_required = use_fragment_route or use_hybrid_route
        causal_contract_valid = causal_marker_present and (
            not use_fragment_route or trusted_fragment_candidate
        )
        if causal_contract_required and not causal_contract_valid:
            return (
                VerificationResult(
                    passed=False,
                    check_count=1,
                    failures=[
                        {
                            "gate": "causal_response",
                            "code": "causal_contract_missing",
                            "expected": {
                                "causal_contract_marker": True,
                                "trusted_fragment_candidate": (
                                    True if use_fragment_route else None
                                ),
                            },
                            "actual": {
                                "causal_contract_marker": causal_marker_present,
                                "trusted_fragment_candidate": (
                                    trusted_fragment_candidate
                                    if use_fragment_route
                                    else None
                                ),
                            },
                        }
                    ],
                    artifact=None,
                    node_report={"passed": False},
                ),
                None,
            )
        verification = await asyncio.to_thread(
            verify_candidate,
            module_output,
            understanding,
        )
        if verification.passed and use_hybrid_route:
            node_report = verification.node_report or {}
            hybrid_evidence_failures = []
            causal_report = node_report.get("causal_response")
            if not isinstance(causal_report, dict) or causal_report.get("passed") is not True:
                hybrid_evidence_failures.append(
                    {
                        "gate": "causal_response",
                        "code": "causal_report_missing",
                        "expected": {"causal_report_passed": True},
                        "actual": {
                            "causal_report_passed": (
                                causal_report.get("passed")
                                if isinstance(causal_report, dict)
                                else None
                            )
                        },
                    }
                )
            representation_report = node_report.get("temporal_causal_matrix")
            if (
                not isinstance(representation_report, dict)
                or representation_report.get("passed") is not True
            ):
                hybrid_evidence_failures.append(
                    {
                        "gate": "representation_consistency",
                        "code": "representation_contract_missing",
                        "expected": {"temporal_causal_matrix_passed": True},
                        "actual": {
                            "temporal_causal_matrix_passed": (
                                representation_report.get("passed")
                                if isinstance(representation_report, dict)
                                else None
                            )
                        },
                    }
                )
            if hybrid_evidence_failures:
                return (
                    VerificationResult(
                        passed=False,
                        check_count=(
                            verification.check_count
                            + len(hybrid_evidence_failures)
                        ),
                        failures=hybrid_evidence_failures,
                        artifact=None,
                        node_report=verification.node_report,
                    ),
                    None,
                )
        if not verification.passed:
            return verification, None
        if verification.artifact is None:
            raise RuntimeError("deterministic verification omitted its artifact")
        browser_result = await manager.verify_in_browser(verification.artifact)
        if browser_result.passed:
            return (
                VerificationResult(
                    passed=True,
                    check_count=verification.check_count + browser_result.check_count,
                    failures=[],
                    artifact=verification.artifact,
                    node_report=verification.node_report,
                ),
                browser_result.evidence,
            )
        return (
            VerificationResult(
                passed=False,
                check_count=verification.check_count + browser_result.check_count,
                failures=browser_result.failures,
                artifact=None,
                node_report=verification.node_report,
            ),
            browser_result.evidence,
        )

    async def review_candidate(
        module_output: dict[str, Any],
        verification: VerificationResult,
        *,
        fallback_on_rejection: bool,
    ) -> tuple[str, dict[str, Any] | None]:
        manager.emit(
            record,
            "stage",
            {
                "stage": "qa",
                "detail": "مراجعة المرشح الموثق",
                "elapsed_ms": manager.elapsed_ms(record),
            },
        )
        gate_outcome = {
            "passed": True,
            "check_count": verification.check_count,
            "gate_names": [
                "assembly",
                "interface",
                "invariant",
                "runtime_init",
                "security",
                "source_size",
                "syntax_runtime",
            ],
        }
        qa_result = None
        for qa_attempt in (1, 2):
            try:
                qa_result = await stage_result(
                    "qa" if qa_attempt == 1 else "qa_retry",
                    manager.backend.qa(
                        module_output,
                        understanding,
                        gate_outcome,
                        runtime_context=runtime_context,
                    ),
                )
                break
            except CodexRuntimeError as error:
                if error.code != "stage_timeout":
                    raise
                if not record.public:
                    record.builder_diagnostics.append(
                        {
                            "type": "qa_timeout",
                            "attempt": qa_attempt,
                            "code": error.code,
                            "structured_output_observed": False,
                            "candidate_sha256": hashlib.sha256(
                                module_output["module_js"].encode("utf-8")
                            ).hexdigest(),
                            "input_fields": [
                                "module_source",
                                "module_spec",
                                "fixtures",
                                "gate_outcome",
                            ],
                            "gate_outcome": gate_outcome,
                        }
                    )
                if qa_attempt == 1:
                    manager.emit(
                        record,
                        "stage",
                        {
                            "stage": "qa_retry",
                            "detail": "إعادة مراجعة QA المختصرة مرة واحدة",
                            "elapsed_ms": manager.elapsed_ms(record),
                        },
                    )
                    continue
                if record.public:
                    _fallback(
                        manager,
                        record,
                        "qa_inconclusive",
                        _gallery_suggestions(record.locale),
                    )
                else:
                    manager.terminal(record, "qa_inconclusive", "qa_inconclusive")
                return "inconclusive", None
        if qa_result is None:
            raise RuntimeError("QA retry loop completed without an outcome")
        if not qa_result["approved"]:
            if not record.public:
                record.builder_diagnostics.append(
                    {
                        "type": "qa_rejected",
                        "issues": qa_result["issues"],
                        "visual_richness": qa_result.get("visual_richness"),
                    }
                )
            if fallback_on_rejection:
                _fallback(
                    manager,
                    record,
                    "qa_rejected",
                    _gallery_suggestions(record.locale),
                )
            return "rejected", qa_result
        return "approved", qa_result

    manager.transition(record, "filtering", "فحص أولي محدود", emit_event=False)
    await asyncio.sleep(0)
    manager.transition(
        record,
        "understanding",
        "صياغة جواب وعقد تعليمي",
        emit_event=False,
    )
    raw_understanding = await stage_result(
        "understand",
        manager.backend.understand(
            question,
            record.locale,
            runtime_context=runtime_context,
        ),
    )
    try:
        understanding = validate_understanding(raw_understanding)
    except (ContractError, ValidationError):
        answer = _safe_answer_slice(raw_understanding)
        if answer is None:
            raise
        record.answer = answer
        manager.transition(record, "answered", "الجواب جاهز", emit_event=False)
        manager.emit(record, "answer", answer.model_dump(mode="json"))
        _fallback(
            manager,
            record,
            "generation_failed",
            _gallery_suggestions(record.locale),
        )
        return

    if not understanding["safe"]:
        _reject(
            manager,
            record,
            understanding["reason_code"],
            understanding["suggestions"],
        )

    formula_failures, _ = formula_presentation_report(understanding)
    if formula_failures and not record.public:
        record.builder_diagnostics.append(
            {
                "type": "understanding_refresh",
                "attempt": 1,
                "trigger_failures": formula_failures,
            }
        )
        understanding = validate_understanding(
            await stage_result(
                "understand_retry",
                manager.backend.understand(
                    question,
                    record.locale,
                    runtime_context=runtime_context,
                ),
            )
        )
        formula_failures, _ = formula_presentation_report(understanding)
        if formula_failures:
            record.builder_diagnostics.append(
                {
                    "type": "understanding_refresh_exhausted",
                    "failures": formula_failures,
                }
            )
            _fallback(
                manager,
                record,
                "formula_presentation_unresolved",
                understanding["suggestions"],
            )
            return
    answer_formula = None if formula_failures else understanding["key_formula"]
    if formula_failures:
        understanding = {**understanding, "key_formula": None}

    record.answer = AnswerPayload(
        tldr=understanding["tldr"],
        key_formula=answer_formula,
    )
    manager.transition(record, "answered", "الجواب جاهز", emit_event=False)
    manager.emit(record, "answer", record.answer.model_dump(mode="json"))
    manager.emit(
        record,
        "stage",
        {
            "stage": "understanding",
            "detail": "اكتمل فهم السؤال وصياغة الجواب",
            "elapsed_ms": manager.elapsed_ms(record),
        },
    )

    if not understanding["simulatable"]:
        _fallback(
            manager,
            record,
            understanding["reason_code"],
            understanding["suggestions"],
        )
        return

    manager.transition(record, "cache_lookup", "فحص النتائج الموثقة")
    cache = manager.cache
    incumbent = None
    if cache is not None:
        cached = cache.lookup(
            question=question,
            locale=understanding["lang"],
            domain=understanding["domain"],
            canonical_intent=understanding["canonical_intent"],
        )
        if record.fresh_generation:
            incumbent = cached
        elif cached is not None:
            manager.transition(record, "browser_check", "استخدام إيصال تحقق مخزّن")
            manager.emit(
                record,
                "verification",
                {
                    "passed": True,
                    "check_count": cached.receipt.check_count,
                    "heal_count": 0,
                    "evidence": ["verified_cache", "artifact_hash", "browser_readiness"],
                },
            )
            sim_id = "sim_" + cached.artifact_sha256[:16]
            manager.artifacts[sim_id] = cached.artifact
            # A semantic hit originated from a different raw question. Because raw
            # questions are intentionally never persisted, only an exact-key hit
            # can carry a question-relative zero-echo proof into sharing.
            record.share_eligible = (
                cached.exact_key
                == cache.exact_key(question, understanding["lang"])
                and not contains_learner_question_echo(cached.artifact, question)
            )
            record.artifact = cached.artifact
            record.simulation = SimulationMetadata(
                sim_id=sim_id,
                title=cached.title,
                lang=cached.locale,
                direction=cached.direction,
                artifact_url=f"/api/sims/{sim_id}/download",
                tier=cached.tier,
                effective_model="verified/cache",
                elapsed_ms=manager.elapsed_ms(record),
                check_count=cached.receipt.check_count,
                heal_count=0,
            )
            manager.emit(
                record,
                "result",
                {
                    "result_url": f"/api/jobs/{record.job_id}",
                    "sim_id": sim_id,
                    "title": cached.title,
                    "tier": cached.tier,
                },
            )
            manager.transition(record, "complete", "verified_cache_result")
            return
    manager.transition(record, "generating", "بناء وحدة المحاكاة")
    module_output: dict[str, Any] | None = None
    verification: VerificationResult | None = None
    heal_count = 0
    fixture_refresh_count = 0
    browser_evidence: dict[str, Any] | None = None
    qa_outcome: dict[str, Any] | None = None
    qa_advisory_only = False
    qa_verified_candidate: _QaVerifiedCandidate | None = None
    effective_generation_model: str | None = None
    trusted_fragment_candidate = False
    heal_attempt_limit = (
        getattr(manager.backend, "public_heal_attempt_limit", 2)
        if record.public
        else 2
    )
    if heal_attempt_limit not in {1, 2}:
        raise RuntimeError("invalid heal attempt limit")

    candidate_spec_factory = getattr(
        manager.backend,
        "generation_candidate_specs",
        None,
    )
    fragment_generator = getattr(manager.backend, "generate_fragments", None)
    hybrid_physics_generator = getattr(
        manager.backend,
        "generate_hybrid_physics",
        None,
    )
    hybrid_visual_plan_generator = getattr(
        manager.backend,
        "generate_hybrid_visual_plan",
        None,
    )
    hybrid_visual_module_generator = getattr(
        manager.backend,
        "generate_hybrid_visual_module",
        None,
    )
    generation_strategy = getattr(
        manager.backend,
        "public_generation_strategy",
        "fragments",
    )
    hybrid_methods_ready = all(
        callable(method)
        for method in (
            hybrid_physics_generator,
            hybrid_visual_plan_generator,
            hybrid_visual_module_generator,
        )
    )
    use_hybrid_route = (
        record.public
        and generation_strategy == "hybrid"
        and hybrid_methods_ready
    )
    use_fragment_route = (
        record.public
        and generation_strategy == "fragments"
        and callable(fragment_generator)
    )
    if record.public and generation_strategy == "hybrid" and not use_hybrid_route:
        _fallback(
            manager,
            record,
            "generation_failed",
            _gallery_suggestions(record.locale),
        )
        return
    candidate_specs: tuple[GenerationCandidateSpec, ...] = ()
    if (
        record.public
        and not use_fragment_route
        and not use_hybrid_route
        and callable(candidate_spec_factory)
    ):
        candidate_specs = tuple(
            candidate_spec_factory(
                understanding,
                runtime_context=runtime_context,
            )
        )

    if use_hybrid_route:
        assert callable(hybrid_physics_generator)
        assert callable(hybrid_visual_plan_generator)
        assert callable(hybrid_visual_module_generator)
        try:
            physics_stage = await hybrid_physics_generator(
                understanding,
                runtime_context=runtime_context,
            )
        except CodexRuntimeError as error:
            record_stage_failure("generate_physics", error)
            _fallback(
                manager,
                record,
                "generation_failed",
                _gallery_suggestions(record.locale),
            )
            return
        physics_document = stage_data(
            physics_stage,
            "generate_physics",
            fragment_role="physics",
        )
        try:
            physics_document = validate_physics_fragment(
                physics_document,
                understanding,
            )
        except (ContractError, ValidationError, ValueError) as error:
            physics_regenerator = getattr(
                manager.backend,
                "regenerate_fragment",
                None,
            )
            failure_code = fragment_failure_code(error)
            if not callable(physics_regenerator):
                logger.warning(
                    "public hybrid physics contract rejected job=%s code=%s",
                    record.job_id,
                    failure_code,
                )
                _fallback(
                    manager,
                    record,
                    "generation_failed",
                    _gallery_suggestions(record.locale),
                )
                return
            failure_diagnostic = fragment_failure_diagnostic(
                error,
                role="physics",
                understanding=understanding,
            )
            manager.emit(
                record,
                "stage",
                {
                    "stage": "generate",
                    "detail": "إعادة ضبط النموذج العلمي قبل الرسم",
                    "elapsed_ms": manager.elapsed_ms(record),
                },
            )
            try:
                physics_stage = await physics_regenerator(
                    "physics",
                    understanding,
                    failure_code,
                    exact_gate_failures=[failure_diagnostic],
                    prior_fragment=physics_document,
                    repair_attempt=1,
                    runtime_context=runtime_context,
                )
                physics_document = stage_data(
                    physics_stage,
                    "generate_physics",
                    fragment_role="physics",
                )
                physics_document = validate_physics_fragment(
                    physics_document,
                    understanding,
                )
            except CodexRuntimeError as retry_error:
                record_stage_failure("generate_physics", retry_error)
                _fallback(
                    manager,
                    record,
                    "generation_failed",
                    _gallery_suggestions(record.locale),
                )
                return
            except (ContractError, ValidationError, ValueError) as retry_error:
                logger.warning(
                    "public hybrid physics repair rejected job=%s code=%s",
                    record.job_id,
                    fragment_failure_code(retry_error),
                )
                _fallback(
                    manager,
                    record,
                    "generation_failed",
                    _gallery_suggestions(record.locale),
                )
                return

        try:
            discovery_plan = build_discovery_plan(
                understanding,
                physics_document,
                source_ids=(),
            ).model_dump(mode="json")
        except (ContractError, ValidationError, ValueError) as error:
            logger.warning(
                "public hybrid physics/plan contract rejected job=%s error_type=%s",
                record.job_id,
                type(error).__name__,
            )
            _fallback(
                manager,
                record,
                "generation_failed",
                _gallery_suggestions(record.locale),
            )
            return

        backend_settings = getattr(manager.backend, "settings", None)
        hybrid_visual_model = getattr(
            backend_settings,
            "visual_model",
            "gpt-5.6-terra",
        )
        hybrid_specs = {
            "trusted_scene_plan": GenerationCandidateSpec(
                "trusted_scene_plan",
                1,
                hybrid_visual_model,
                "medium",
            ),
            "direct_canvas": GenerationCandidateSpec(
                "direct_canvas",
                2,
                hybrid_visual_model,
                "medium",
            ),
        }

        async def build_hybrid_visual(
            strategy: str,
        ) -> _CandidateOutcome:
            spec = hybrid_specs[strategy]
            try:
                if strategy == "trusted_scene_plan":
                    stage = await hybrid_visual_plan_generator(
                        understanding,
                        physics_document,
                        discovery_plan,
                        runtime_context=runtime_context,
                    )
                    visual_document = stage_data(
                        stage,
                        "generate_visual",
                        spec,
                        fragment_role=strategy,
                    )
                    visual_document = validate_visual_fragment(
                        visual_document,
                        understanding,
                    )
                    output = assemble_fragments(
                        physics_document,
                        visual_document,
                        understanding,
                    )
                else:
                    stage = await hybrid_visual_module_generator(
                        understanding,
                        physics_document,
                        discovery_plan,
                        runtime_context=runtime_context,
                    )
                    output = validate_module_output(
                        stage_data(
                            stage,
                            "generate_visual",
                            spec,
                            fragment_role=strategy,
                        )
                    )
                return _CandidateOutcome(
                    spec=spec,
                    module_output=output,
                )
            except CodexRuntimeError as error:
                record_stage_failure("generate_visual", error, spec)
                return _CandidateOutcome(spec=spec, error=error)
            except (ContractError, ValidationError, ValueError) as error:
                logger.warning(
                    "public hybrid visual rejected job=%s strategy=%s error_type=%s",
                    record.job_id,
                    strategy,
                    type(error).__name__,
                )
                return _CandidateOutcome(spec=spec, error=error)

        visual_tasks = tuple(
            asyncio.create_task(build_hybrid_visual(strategy))
            for strategy in ("trusted_scene_plan", "direct_canvas")
        )
        try:
            hybrid_outcomes = list(await asyncio.gather(*visual_tasks))
        except BaseException:
            for task in visual_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*visual_tasks, return_exceptions=True)
            raise

        if record.status != "verifying":
            manager.transition(
                record,
                "verifying",
                "فحص مرشحي المحاكاة المستقلين",
            )

        async def verify_hybrid_visual(
            outcome: _CandidateOutcome,
        ) -> _CandidateOutcome:
            if outcome.error is not None or outcome.module_output is None:
                return outcome
            candidate_verification, candidate_browser = (
                await verify_generated_module(
                    outcome.module_output,
                    understanding,
                )
            )
            outcome.verification = candidate_verification
            outcome.browser_evidence = candidate_browser
            return outcome

        verification_tasks = tuple(
            asyncio.create_task(verify_hybrid_visual(outcome))
            for outcome in hybrid_outcomes
        )
        try:
            hybrid_outcomes = list(await asyncio.gather(*verification_tasks))
        except BaseException:
            for task in verification_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*verification_tasks, return_exceptions=True)
            raise
        logger.info(
            "public hybrid candidates job=%s results=%s",
            record.job_id,
            [
                {
                    "strategy": outcome.spec.candidate_id,
                    "error": type(outcome.error).__name__
                    if outcome.error is not None
                    else None,
                    "verified": (
                        outcome.verification.passed
                        if outcome.verification is not None
                        else None
                    ),
                }
                for outcome in hybrid_outcomes
            ],
        )
        passing_hybrid = [
            outcome
            for outcome in hybrid_outcomes
            if outcome.error is None
            and outcome.module_output is not None
            and outcome.verification is not None
            and outcome.verification.passed
        ]
        if passing_hybrid:
            winner = max(
                passing_hybrid,
                key=lambda outcome: (
                    outcome.verification.check_count,
                    int(outcome.spec.candidate_id == "direct_canvas"),
                ),
            )
            module_output = winner.module_output
            verification = winner.verification
            browser_evidence = winner.browser_evidence
            effective_generation_model = (
                f"physics:{physics_stage.model}"
                f"+visual:{winner.spec.model}/{winner.spec.candidate_id}"
            )
        else:
            failed_hybrid = [
                outcome
                for outcome in hybrid_outcomes
                if outcome.module_output is not None
                and outcome.verification is not None
            ]
            if not failed_hybrid:
                _fallback(
                    manager,
                    record,
                    "generation_failed",
                    _gallery_suggestions(record.locale),
                )
                return
            selected = min(
                failed_hybrid,
                key=lambda outcome: (
                    len(outcome.verification.failures),
                    -outcome.verification.check_count,
                    outcome.spec.ordinal,
                ),
            )
            module_output = selected.module_output
            verification = selected.verification
            browser_evidence = selected.browser_evidence
            effective_generation_model = (
                f"physics:{physics_stage.model}"
                f"+visual:{selected.spec.model}/{selected.spec.candidate_id}"
            )
    elif use_fragment_route:
        try:
            physics_stage, visual_stage = await fragment_generator(
                understanding,
                runtime_context=runtime_context,
            )
        except CodexRuntimeError as error:
            record_stage_failure("generate", error)
            raise
        physics_fragment = stage_data(
            physics_stage,
            "generate_physics",
            fragment_role="physics",
        )
        visual_fragment = stage_data(
            visual_stage,
            "generate_visual",
            fragment_role="visual",
        )
        fragment_documents = {
            "physics": physics_fragment,
            "visual": visual_fragment,
        }
        fragment_stages = {
            "physics": physics_stage,
            "visual": visual_stage,
        }
        fragment_validators = {
            "physics": validate_physics_fragment,
            "visual": validate_visual_fragment,
        }
        fragment_regenerator = getattr(
            manager.backend,
            "regenerate_fragment",
            None,
        )
        fragment_semantic_attempts = {"physics": 0, "visual": 0}
        fragment_repair_attempts = {"physics": 0, "visual": 0}

        def claim_fragment_semantic_attempt(role: str) -> int | None:
            attempted = fragment_semantic_attempts[role]
            if attempted >= 2:
                return None
            repair_attempt = attempted + 1
            fragment_semantic_attempts[role] = repair_attempt
            return repair_attempt

        def claim_fragment_repair_attempt(role: str) -> int | None:
            attempted = fragment_repair_attempts[role]
            if attempted >= 2:
                return None
            repair_attempt = attempted + 1
            fragment_repair_attempts[role] = repair_attempt
            return repair_attempt

        retry_role_by_gate = {
            "fixture_integrity": "physics",
            "invariant": "physics",
            "readout_visibility": "physics",
            "scene_geometry": "visual",
            "causal_response": "visual",
            "temporal_causal_matrix": "visual",
            "representation_consistency": "visual",
        }
        browser_readiness_retry_role_by_code = {
            "canvas_pixels_unchanged": "visual",
            "visible_frame_unchanged": "visual",
        }

        def fragment_repair_plan(
            failures: list[dict[str, Any]],
        ) -> list[tuple[str, str, list[dict[str, Any]]]] | None:
            roles: set[str] = set()
            failures_by_role: dict[str, list[dict[str, Any]]] = {
                "physics": [],
                "visual": [],
            }
            browser_readiness_codes: set[str] = set()
            has_causal_response_failure = False
            for failure in failures:
                gate = failure.get("gate")
                if not isinstance(gate, str):
                    return None
                if gate == "browser_readiness":
                    code = failure.get("code")
                    if not isinstance(code, str):
                        return None
                    role = browser_readiness_retry_role_by_code.get(code)
                    if role is not None:
                        browser_readiness_codes.add(code)
                else:
                    role = retry_role_by_gate.get(gate)
                if role is None:
                    return None
                roles.add(role)
                failures_by_role[role].append(failure)
                has_causal_response_failure |= gate in {
                    "causal_response",
                    "temporal_causal_matrix",
                }
            if not roles:
                return None

            plan: list[tuple[str, str, list[dict[str, Any]]]] = []
            if "physics" in roles:
                plan.append(
                    (
                        "physics",
                        "physics_fixture_mismatch",
                        failures_by_role["physics"],
                    )
                )
            if "visual" in roles:
                if has_causal_response_failure:
                    visual_failure_code = "visual_causality_mismatch"
                elif browser_readiness_codes:
                    visual_failure_code = next(
                        code
                        for code in browser_readiness_retry_role_by_code
                        if code in browser_readiness_codes
                    )
                else:
                    visual_failure_code = "visual_geometry_mismatch"
                plan.append(
                    (
                        "visual",
                        visual_failure_code,
                        failures_by_role["visual"],
                    )
                )
            return plan

        async def regenerate_trusted_fragment_candidate(
            role: str,
            failure_code: str,
            exact_gate_failures: list[dict[str, Any]],
        ) -> bool:
            nonlocal effective_generation_model
            nonlocal module_output
            nonlocal trusted_fragment_candidate

            if not callable(fragment_regenerator):
                return False
            current_failure_code = failure_code
            current_gate_failures = list(exact_gate_failures)
            current_fragment = fragment_documents[role]
            stage_name = f"generate_{role}"
            while True:
                repair_attempt = claim_fragment_repair_attempt(role)
                if repair_attempt is None:
                    return False
                manager.emit(
                    record,
                    "stage",
                    {
                        "stage": "generate",
                        "detail": "إعادة بناء الجزء الذي لم يجتز الفحص",
                        "elapsed_ms": manager.elapsed_ms(record),
                    },
                )
                regenerated_document: dict[str, Any] | None = None
                try:
                    regenerated_stage = await fragment_regenerator(
                        role,
                        understanding,
                        current_failure_code,
                        exact_gate_failures=current_gate_failures,
                        prior_fragment=current_fragment,
                        repair_attempt=repair_attempt,
                        runtime_context=runtime_context,
                    )
                    regenerated_document = stage_data(
                        regenerated_stage,
                        stage_name,
                        fragment_role=role,
                    )
                    fragment_validators[role](regenerated_document, understanding)
                except CodexRuntimeError as error:
                    record_stage_failure(stage_name, error)
                    return False
                except (ContractError, ValidationError, ValueError) as error:
                    if regenerated_document is not None:
                        current_fragment = regenerated_document
                    current_failure_code = fragment_failure_code(error)
                    deterministic_repair = (
                        repair_visual_causal_response(
                            current_fragment,
                            understanding,
                        )
                        if role == "visual"
                        and current_failure_code
                        == "causal_channel_fixture_response_required"
                        else None
                    )
                    if deterministic_repair is not None:
                        logger.info(
                            "deterministic causal repair accepted job=%s "
                            "role=%s attempt=%s",
                            record.job_id,
                            role,
                            repair_attempt,
                        )
                        fragment_documents[role] = deterministic_repair
                        fragment_stages[role] = regenerated_stage
                        module_output = assemble_fragments(
                            fragment_documents["physics"],
                            fragment_documents["visual"],
                            understanding,
                        )
                        trusted_fragment_candidate = True
                        effective_generation_model = (
                            f"physics:{fragment_stages['physics'].model}"
                            f"+visual:{fragment_stages['visual'].model}"
                        )
                        record.builder_diagnostics.append(
                            {
                                "type": "deterministic_causal_repair",
                                "role": role,
                                "code": current_failure_code,
                                "attempt": repair_attempt,
                            }
                        )
                        return True
                    current_gate_failures = [
                        *exact_gate_failures,
                        fragment_failure_diagnostic(
                            error,
                            role=role,
                            understanding=understanding,
                        ),
                    ]
                    logger.warning(
                        "fragment gate repair rejected job=%s role=%s attempt=%s code=%s",
                        record.job_id,
                        role,
                        repair_attempt,
                        current_failure_code,
                    )
                    record.builder_diagnostics.append(
                        {
                            "type": "fragment_gate_repair_failure",
                            "role": role,
                            "code": current_failure_code,
                            "attempt": repair_attempt,
                        }
                    )
                    continue
                fragment_documents[role] = regenerated_document
                fragment_stages[role] = regenerated_stage
                module_output = assemble_fragments(
                    fragment_documents["physics"],
                    fragment_documents["visual"],
                    understanding,
                )
                trusted_fragment_candidate = True
                effective_generation_model = (
                    f"physics:{fragment_stages['physics'].model}"
                    f"+visual:{fragment_stages['visual'].model}"
                )
                return True

        def semantic_failures() -> list[tuple[str, Exception]]:
            failures: list[tuple[str, Exception]] = []
            for role in ("physics", "visual"):
                try:
                    fragment_validators[role](
                        fragment_documents[role],
                        understanding,
                    )
                except (ContractError, ValidationError, ValueError) as error:
                    failures.append((role, error))
            return failures

        while True:
            initial_fragment_failures = semantic_failures()
            if not initial_fragment_failures:
                break
            if not callable(fragment_regenerator):
                _fallback(
                    manager,
                    record,
                    "generation_failed",
                    _gallery_suggestions(record.locale),
                )
                return
            for role, failure_error in initial_fragment_failures:
                failure_code = fragment_failure_code(failure_error)
                failure_diagnostic = fragment_failure_diagnostic(
                    failure_error,
                    role=role,
                    understanding=understanding,
                )
                repair_attempt = claim_fragment_semantic_attempt(role)
                if repair_attempt is None:
                    logger.warning(
                        "fragment validation exhausted job=%s role=%s attempts=2 code=%s",
                        record.job_id,
                        role,
                        failure_code,
                    )
                    record.builder_diagnostics.append(
                        {
                            "type": "fragment_validation_exhausted",
                            "role": role,
                            "code": failure_code,
                            "attempts": 2,
                        }
                    )
                    _fallback(
                        manager,
                        record,
                        "generation_failed",
                        _gallery_suggestions(record.locale),
                    )
                    return
                logger.warning(
                    "fragment validation rejected job=%s role=%s attempt=%s code=%s",
                    record.job_id,
                    role,
                    repair_attempt,
                    failure_code,
                )
                record.builder_diagnostics.append(
                    {
                        "type": "fragment_validation_failure",
                        "role": role,
                        "code": failure_code,
                        "attempt": repair_attempt,
                    }
                )
                manager.emit(
                    record,
                    "stage",
                    {
                        "stage": "generate",
                        "detail": "إعادة بناء الجزء الذي لم يجتز عقد التجميع",
                        "elapsed_ms": manager.elapsed_ms(record),
                    },
                )
                stage_name = f"generate_{role}"
                try:
                    regenerated_stage = await fragment_regenerator(
                        role,
                        understanding,
                        failure_code,
                        exact_gate_failures=[failure_diagnostic],
                        prior_fragment=fragment_documents[role],
                        repair_attempt=repair_attempt,
                        runtime_context=runtime_context,
                    )
                except CodexRuntimeError as error:
                    record_stage_failure(stage_name, error)
                    _fallback(
                        manager,
                        record,
                        "generation_failed",
                        _gallery_suggestions(record.locale),
                    )
                    return
                fragment_documents[role] = stage_data(
                    regenerated_stage,
                    stage_name,
                    fragment_role=role,
                )
                fragment_stages[role] = regenerated_stage

        physics_fragment = fragment_documents["physics"]
        visual_fragment = fragment_documents["visual"]
        physics_stage = fragment_stages["physics"]
        visual_stage = fragment_stages["visual"]
        module_output = assemble_fragments(
            physics_fragment,
            visual_fragment,
            understanding,
        )
        trusted_fragment_candidate = True
        fragment_preflight = await asyncio.to_thread(
            verify_candidate,
            module_output,
            understanding,
        )
        preflight_repair_plan = (
            fragment_repair_plan(fragment_preflight.failures)
            if not fragment_preflight.passed and callable(fragment_regenerator)
            else None
        )
        if preflight_repair_plan is not None:
            if record.status != "verifying":
                manager.transition(record, "verifying", "فحص العقد والنتائج الحتمية")
            record_verification_failure(fragment_preflight, heal_count)
            heal_count += 1
            manager.transition(record, "healing", "إصلاح فشل تحقق محدد")
            for role, failure_code, exact_gate_failures in preflight_repair_plan:
                logger.warning(
                    "fragment preflight rejected job=%s role=%s code=%s",
                    record.job_id,
                    role,
                    failure_code,
                )
                repaired = await regenerate_trusted_fragment_candidate(
                    role,
                    failure_code,
                    exact_gate_failures,
                )
                if not repaired:
                    _fallback(
                        manager,
                        record,
                        "generation_failed",
                        _gallery_suggestions(record.locale),
                    )
                    return
            physics_fragment = fragment_documents["physics"]
            visual_fragment = fragment_documents["visual"]
            physics_stage = fragment_stages["physics"]
            visual_stage = fragment_stages["visual"]
            module_output = assemble_fragments(
                physics_fragment,
                visual_fragment,
                understanding,
            )
            trusted_fragment_candidate = True
        effective_generation_model = (
            f"physics:{physics_stage.model}+visual:{visual_stage.model}"
        )
    elif len(candidate_specs) > 1:

        async def build_candidate(spec: GenerationCandidateSpec) -> _CandidateOutcome:
            try:
                output = validate_module_output(
                    await stage_result(
                        "generate",
                        manager.backend.generate(
                            understanding,
                            scenario,
                            runtime_context=runtime_context,
                            candidate_spec=spec,
                        ),
                        spec,
                    )
                )
                candidate_verification, candidate_browser = (
                    await verify_generated_module(output, understanding)
                )
                return _CandidateOutcome(
                    spec=spec,
                    module_output=output,
                    verification=candidate_verification,
                    browser_evidence=candidate_browser,
                )
            except (CodexRuntimeError, ContractError, ValidationError) as error:
                return _CandidateOutcome(spec=spec, error=error)

        tasks = {
            asyncio.create_task(build_candidate(spec)): spec for spec in candidate_specs
        }
        pending = set(tasks)
        outcomes: list[_CandidateOutcome] = []
        winner: _CandidateOutcome | None = None
        saw_qa_rejection = False
        try:
            while pending and winner is None:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in sorted(done, key=lambda item: tasks[item].ordinal):
                    outcome = task.result()
                    outcomes.append(outcome)
                    if outcome.error is not None or outcome.verification is None:
                        continue
                    if record.status != "verifying":
                        manager.transition(
                            record,
                            "verifying",
                            "فحص مرشحي المحاكاة المستقلين",
                        )
                    if not outcome.verification.passed:
                        continue
                    if outcome.module_output is None:
                        raise RuntimeError("verified race candidate omitted module output")
                    qa_status, candidate_qa = await review_candidate(
                        outcome.module_output,
                        outcome.verification,
                        fallback_on_rejection=False,
                    )
                    if qa_status == "inconclusive":
                        return
                    if qa_status == "rejected":
                        saw_qa_rejection = True
                        continue
                    qa_outcome = candidate_qa
                    winner = outcome
                    break
        finally:
            for task in pending:
                if not task.done():
                    task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        if winner is not None:
            module_output = winner.module_output
            verification = winner.verification
            browser_evidence = winner.browser_evidence
            effective_generation_model = winner.spec.model
        else:
            failed_candidates = [
                outcome
                for outcome in outcomes
                if outcome.module_output is not None
                and outcome.verification is not None
                and not outcome.verification.passed
            ]
            if failed_candidates:
                selected = min(
                    failed_candidates,
                    key=lambda outcome: (
                        len(outcome.verification.failures),
                        -outcome.verification.check_count,
                        outcome.spec.ordinal,
                    ),
                )
                module_output = selected.module_output
                verification = selected.verification
                browser_evidence = selected.browser_evidence
                effective_generation_model = selected.spec.model
            elif saw_qa_rejection:
                _fallback(
                    manager,
                    record,
                    "qa_rejected",
                    _gallery_suggestions(record.locale),
                )
                return
            else:
                runtime_error = next(
                    (
                        outcome.error
                        for outcome in outcomes
                        if isinstance(outcome.error, CodexRuntimeError)
                    ),
                    None,
                )
                if runtime_error is not None:
                    raise runtime_error
                _fallback(
                    manager,
                    record,
                    "generation_failed",
                    _gallery_suggestions(record.locale),
                )
                return
    else:
        selected_spec = candidate_specs[0] if candidate_specs else None
        generate_options: dict[str, Any] = {"runtime_context": runtime_context}
        if selected_spec is not None:
            generate_options["candidate_spec"] = selected_spec
        module_output = validate_module_output(
            await stage_result(
                "generate",
                manager.backend.generate(
                    understanding,
                    scenario,
                    **generate_options,
                ),
                selected_spec,
            )
        )
        if selected_spec is not None:
            effective_generation_model = selected_spec.model

    if module_output is None:
        raise RuntimeError("generation completed without a module output")
    if scenario == "exhausted_heal":
        module_output = manager.backend.mark_exhausted(module_output)
        verification = None

    while True:
        if verification is None:
            if record.status != "verifying":
                manager.transition(record, "verifying", "فحص العقد والنتائج الحتمية")
            verification, browser_evidence = await verify_generated_module(
                module_output,
                understanding,
            )

        if not verification.passed:
            record_verification_failure(verification, heal_count)
            suspect_fixtures = [
                failure
                for failure in verification.failures
                if failure["gate"] == "fixture_integrity"
            ]
            if suspect_fixtures and not record.public:
                if fixture_refresh_count >= 1:
                    _fallback(
                        manager,
                        record,
                        "fixture_integrity_unresolved",
                        _gallery_suggestions(record.locale),
                    )
                    return
                fixture_refresh_count += 1
                record.builder_diagnostics.append(
                    {
                        "type": "fixture_refresh",
                        "attempt": fixture_refresh_count,
                        "trigger_failures": suspect_fixtures,
                    }
                )
                manager.emit(
                    record,
                    "stage",
                    {
                        "stage": "fixture_refresh",
                        "detail": "إعادة تدقيق عقد القياس المرجعي",
                        "elapsed_ms": manager.elapsed_ms(record),
                    },
                )
                understanding = validate_understanding(
                    await stage_result(
                        "understand_retry",
                        manager.backend.understand(
                            question,
                            record.locale,
                            runtime_context=runtime_context,
                        ),
                    )
                )
                if not understanding["safe"] or not understanding["simulatable"]:
                    _fallback(
                        manager,
                        record,
                        "fixture_refresh_invalid",
                        understanding["suggestions"],
                    )
                    return
                verification = None
                continue
            if heal_count >= heal_attempt_limit:
                if record.public and qa_verified_candidate is not None:
                    module_output = qa_verified_candidate.module_output
                    verification = qa_verified_candidate.verification
                    browser_evidence = qa_verified_candidate.browser_evidence
                    qa_outcome = qa_verified_candidate.qa_outcome
                    qa_advisory_only = True
                    break
                _fallback(
                    manager,
                    record,
                    "verification_exhausted",
                    _gallery_suggestions(record.locale),
                )
                return
            if use_fragment_route:
                repair_plan = fragment_repair_plan(verification.failures)
                if repair_plan is None:
                    _fallback(
                        manager,
                        record,
                        "verification_exhausted",
                        _gallery_suggestions(record.locale),
                    )
                    return
                heal_count += 1
                manager.transition(record, "healing", "إصلاح فشل تحقق محدد")
                for role, failure_code, exact_gate_failures in repair_plan:
                    repaired = await regenerate_trusted_fragment_candidate(
                        role,
                        failure_code,
                        exact_gate_failures,
                    )
                    if not repaired:
                        _fallback(
                            manager,
                            record,
                            "generation_failed",
                            _gallery_suggestions(record.locale),
                        )
                        return
                verification = None
                continue
            heal_count += 1
            manager.transition(record, "healing", "إصلاح فشل تحقق محدد")
            module_output = validate_module_output(
                await stage_result(
                    f"heal_{heal_count}",
                    manager.backend.heal(
                        module_output,
                        understanding,
                        verification.failures,
                        heal_count,
                        runtime_context=runtime_context,
                    ),
                )
            )
            trusted_fragment_candidate = False
            verification = None
            continue

        if (heal_count or record.promote_golden) and qa_outcome is None:
            if verification is None:
                raise RuntimeError("QA requires a verified candidate")
            qa_can_reheal = record.public and heal_count < heal_attempt_limit
            qa_status, qa_result = await review_candidate(
                module_output,
                verification,
                fallback_on_rejection=not record.public,
            )
            if not record.public and qa_result is not None:
                record.artifact = verification.artifact
                record.builder_outputs = {
                    "understanding": understanding,
                    "module_output": module_output,
                    "verification": {
                        "passed": True,
                        "check_count": verification.check_count,
                        "heal_count": heal_count,
                        "node_report": verification.node_report,
                    },
                    "browser": browser_evidence or {},
                    "qa": qa_result,
                }
            if qa_status == "rejected" and qa_can_reheal and qa_result is not None:
                qa_verified_candidate = _QaVerifiedCandidate(
                    module_output=module_output,
                    verification=verification,
                    browser_evidence=browser_evidence,
                    qa_outcome=qa_result,
                )
                qa_failure = qa_revision_result(verification, qa_result)
                record_verification_failure(qa_failure, heal_count)
                heal_count += 1
                manager.transition(record, "healing", "إصلاح ملاحظات المراجعة")
                if use_fragment_route:
                    repaired = await regenerate_trusted_fragment_candidate(
                        "visual",
                        "visual_quality_review_failed",
                        qa_failure.failures,
                    )
                    if not repaired:
                        module_output = qa_verified_candidate.module_output
                        verification = qa_verified_candidate.verification
                        browser_evidence = qa_verified_candidate.browser_evidence
                        qa_outcome = qa_verified_candidate.qa_outcome
                        qa_advisory_only = True
                        manager.transition(
                            record,
                            "verifying",
                            "الاحتفاظ بالمرشح الموثق بعد مراجعة استشارية",
                        )
                        break
                else:
                    module_output = validate_module_output(
                        await stage_result(
                            f"heal_{heal_count}",
                            manager.backend.heal(
                                module_output,
                                understanding,
                                qa_failure.failures,
                                heal_count,
                                runtime_context=runtime_context,
                            ),
                        )
                    )
                    trusted_fragment_candidate = False
                verification = None
                continue
            if (
                qa_status == "rejected"
                and not qa_can_reheal
                and record.public
                and qa_result is not None
            ):
                qa_outcome = qa_result
                qa_advisory_only = True
                break
            if qa_status != "approved" or qa_result is None:
                return
            qa_outcome = qa_result
        break

    if verification is None:
        raise RuntimeError("verified candidate missing verification result")

    manager.transition(record, "browser_check", "تأكيد جاهزية الغلاف الموثوق")
    if verification is None or verification.artifact is None:
        raise RuntimeError("verified candidate missing artifact")
    artifact = verification.artifact
    check_count = verification.check_count
    manager.emit(
        record,
        "verification",
        {
            "passed": True,
            "check_count": check_count,
            "heal_count": heal_count,
            "evidence": [
                "closed_schema",
                "restricted_source",
                "node_runtime",
                "fixtures",
                "browser_readiness",
            ],
        },
    )
    candidate_receipt = VerificationReceipt(
        deterministic_passed=True,
        browser_passed=bool(browser_evidence),
        failed_gate_count=0,
        check_count=check_count,
        passed_gates=tuple(sorted(LIVE_DETERMINISTIC_PASSED_GATES)),
    )
    candidate_privacy_safe = not contains_learner_question_echo(artifact, question)
    served_artifact = artifact
    served_title = understanding["title"]
    served_locale = understanding["lang"]
    served_direction = "rtl" if understanding["lang"] == "ar" else "ltr"
    served_tier = "B"
    served_check_count = check_count
    served_heal_count = heal_count
    served_effective_model: str | None = None
    served_share_eligible = candidate_privacy_safe
    keep_incumbent = False
    if record.fresh_generation and incumbent is not None:
        fresh_decision = _compare_fresh_candidate(
            incumbent,
            candidate_receipt,
            browser_evidence,
        )
        if not fresh_decision.approved:
            keep_incumbent = True
            record.fresh_outcome = "kept_incumbent"
            record.fresh_outcome_reason_code = fresh_decision.reason_code
            record.builder_diagnostics.append(
                {
                    "type": "fresh_candidate_kept_incumbent",
                    "reason_code": fresh_decision.reason_code,
                }
            )
            served_artifact = incumbent.artifact
            served_title = incumbent.title
            served_locale = incumbent.locale
            served_direction = incumbent.direction
            served_tier = incumbent.tier
            served_check_count = incumbent.receipt.check_count
            served_heal_count = 0
            served_effective_model = "verified/cache"
            served_share_eligible = (
                incumbent.exact_key == cache.exact_key(question, understanding["lang"])
                and not contains_learner_question_echo(incumbent.artifact, question)
            )
    if (
        cache is not None
        and candidate_privacy_safe
        and not keep_incumbent
        and not qa_advisory_only
    ):
        try:
            cache.write_verified(
                question=question,
                locale=understanding["lang"],
                domain=understanding["domain"],
                canonical_intent=understanding["canonical_intent"],
                artifact=artifact,
                title=understanding["title"],
                direction="rtl" if understanding["lang"] == "ar" else "ltr",
                tier="B",
                receipt=candidate_receipt,
                route_label=STABLE_ROUTE,
            )
        except (OSError, ValueError) as error:
            if not record.public:
                record.builder_diagnostics.append(
                    {"type": "cache_write_failed", "error_type": type(error).__name__}
                )
    sim_id = "sim_" + hashlib.sha256(served_artifact.encode("utf-8")).hexdigest()[:16]
    manager.artifacts[sim_id] = served_artifact
    record.share_eligible = served_share_eligible
    record.artifact = served_artifact
    if not record.public:
        record.builder_outputs = {
            "understanding": understanding,
            "module_output": module_output,
            "verification": {
                "passed": True,
                "check_count": check_count,
                "heal_count": heal_count,
                "node_report": verification.node_report,
            },
            "browser": browser_evidence or {},
            "qa": qa_outcome,
        }
    generated_execution = next(
        (
            execution
            for execution in record.stage_executions
            if execution["stage"] == "generate"
            and execution["outcome"] == "completed"
        ),
        None,
    )
    effective_model = served_effective_model or effective_generation_model or (
        generated_execution["model"] if generated_execution else "mock/offline"
    )
    record.simulation = SimulationMetadata(
        sim_id=sim_id,
        title=served_title,
        lang=served_locale,
        direction=served_direction,
        artifact_url=f"/api/sims/{sim_id}/download",
        tier=served_tier,
        effective_model=effective_model,
        elapsed_ms=manager.elapsed_ms(record),
        check_count=served_check_count,
        heal_count=served_heal_count,
    )
    manager.emit(
        record,
        "result",
        {
            "result_url": f"/api/jobs/{record.job_id}",
            "sim_id": sim_id,
            "title": served_title,
            "tier": served_tier,
        },
    )
    manager.transition(record, "complete", "verified_mock_result")
