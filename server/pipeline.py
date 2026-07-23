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
    validate_physics_fragment,
    validate_visual_fragment,
)
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


class PipelineCancelled(Exception):
    pass


@dataclass(slots=True)
class _CandidateOutcome:
    spec: GenerationCandidateSpec
    module_output: dict[str, Any] | None = None
    verification: VerificationResult | None = None
    browser_evidence: dict[str, Any] | None = None
    error: Exception | None = None


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
        if use_fragment_route and (
            not trusted_fragment_candidate
            or "/* LAYSH_CAUSAL_RESPONSE_V1 */" not in module_output["module_js"]
        ):
            return (
                VerificationResult(
                    passed=False,
                    check_count=1,
                    failures=[
                        {
                            "gate": "causal_response",
                            "code": "causal_contract_missing",
                            "expected": {
                                "trusted_fragment_causal_contract": True,
                            },
                            "actual": {
                                "trusted_fragment_causal_contract": (
                                    trusted_fragment_candidate
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
    if cache is not None and not record.fresh_generation:
        cached = cache.lookup(
            question=question,
            locale=understanding["lang"],
            domain=understanding["domain"],
            canonical_intent=understanding["canonical_intent"],
        )
        if cached is not None:
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
    effective_generation_model: str | None = None
    trusted_fragment_candidate = False

    candidate_spec_factory = getattr(
        manager.backend,
        "generation_candidate_specs",
        None,
    )
    fragment_generator = getattr(manager.backend, "generate_fragments", None)
    use_fragment_route = record.public and callable(fragment_generator)
    candidate_specs: tuple[GenerationCandidateSpec, ...] = ()
    if record.public and not use_fragment_route and callable(candidate_spec_factory):
        candidate_specs = tuple(
            candidate_spec_factory(
                understanding,
                runtime_context=runtime_context,
            )
        )

    if use_fragment_route:
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
        fragment_repair_attempts = {"physics": 0, "visual": 0}

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
        }

        def fragment_retry_request(
            failures: list[dict[str, Any]],
        ) -> tuple[str, str] | None:
            roles = {
                retry_role_by_gate.get(failure.get("gate"))
                for failure in failures
            }
            if not roles or None in roles or len(roles) != 1:
                return None
            role = roles.pop()
            if role == "physics":
                return role, "physics_fixture_mismatch"
            if any(failure.get("gate") == "causal_response" for failure in failures):
                return role, "visual_causality_mismatch"
            return role, "visual_geometry_mismatch"

        async def regenerate_trusted_fragment_candidate(
            role: str,
            failure_code: str,
        ) -> bool:
            nonlocal effective_generation_model
            nonlocal module_output
            nonlocal trusted_fragment_candidate

            if not callable(fragment_regenerator):
                return False
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
            stage_name = f"generate_{role}"
            try:
                regenerated_stage = await fragment_regenerator(
                    role,
                    understanding,
                    failure_code,
                    repair_attempt=repair_attempt,
                    runtime_context=runtime_context,
                )
                regenerated_document = stage_data(
                    regenerated_stage,
                    stage_name,
                    fragment_role=role,
                )
                fragment_validators[role](regenerated_document, understanding)
            except (CodexRuntimeError, ContractError, ValidationError, ValueError) as error:
                if isinstance(error, CodexRuntimeError):
                    record_stage_failure(stage_name, error)
                return False
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

        def semantic_failures() -> list[tuple[str, str]]:
            failures: list[tuple[str, str]] = []
            for role in ("physics", "visual"):
                try:
                    fragment_validators[role](
                        fragment_documents[role],
                        understanding,
                    )
                except (ContractError, ValidationError, ValueError) as error:
                    failures.append((role, fragment_failure_code(error)))
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
            for role, failure_code in initial_fragment_failures:
                repair_attempt = claim_fragment_repair_attempt(role)
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
        preflight_roles = {
            retry_role_by_gate.get(failure.get("gate"))
            for failure in fragment_preflight.failures
        }
        retryable_preflight = (
            not fragment_preflight.passed
            and None not in preflight_roles
            and bool(preflight_roles)
            and callable(fragment_regenerator)
        )
        if retryable_preflight:
            for role in sorted(preflight_roles):
                if role == "physics":
                    failure_code = "physics_fixture_mismatch"
                elif any(
                    failure.get("gate") == "causal_response"
                    for failure in fragment_preflight.failures
                ):
                    failure_code = "visual_causality_mismatch"
                else:
                    failure_code = "visual_geometry_mismatch"
                logger.warning(
                    "fragment preflight rejected job=%s role=%s code=%s",
                    record.job_id,
                    role,
                    failure_code,
                )
                repair_attempt = claim_fragment_repair_attempt(role)
                if repair_attempt is None:
                    _fallback(
                        manager,
                        record,
                        "generation_failed",
                        _gallery_suggestions(record.locale),
                    )
                    return
                manager.emit(
                    record,
                    "stage",
                    {
                        "stage": "generate",
                        "detail": "إعادة بناء الجزء الذي لم يجتز الفحص الحتمي",
                        "elapsed_ms": manager.elapsed_ms(record),
                    },
                )
                try:
                    regenerated_stage = await fragment_regenerator(
                        role,
                        understanding,
                        failure_code,
                        repair_attempt=repair_attempt,
                        runtime_context=runtime_context,
                    )
                    regenerated_document = stage_data(
                        regenerated_stage,
                        f"generate_{role}",
                        fragment_role=role,
                    )
                    fragment_validators[role](regenerated_document, understanding)
                except (CodexRuntimeError, ContractError, ValidationError, ValueError) as error:
                    if isinstance(error, CodexRuntimeError):
                        record_stage_failure(f"generate_{role}", error)
                    _fallback(
                        manager,
                        record,
                        "generation_failed",
                        _gallery_suggestions(record.locale),
                    )
                    return
                fragment_documents[role] = regenerated_document
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
                effective_generation_model = selected.spec.model
                record_verification_failure(selected.verification, heal_count)
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
        if verification is not None and verification.passed:
            pass
        else:
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
                    continue
                if heal_count >= 2:
                    _fallback(
                        manager,
                        record,
                        "verification_exhausted",
                        _gallery_suggestions(record.locale),
                    )
                    return
                if use_fragment_route:
                    retry_request = fragment_retry_request(verification.failures)
                    if retry_request is None:
                        _fallback(
                            manager,
                            record,
                            "verification_exhausted",
                            _gallery_suggestions(record.locale),
                        )
                        return
                    heal_count += 1
                    manager.transition(record, "healing", "إصلاح فشل تحقق محدد")
                    repaired = await regenerate_trusted_fragment_candidate(
                        *retry_request,
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
            qa_can_reheal = record.public and heal_count < 2
            qa_status, qa_result = await review_candidate(
                module_output,
                verification,
                fallback_on_rejection=not qa_can_reheal,
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
                qa_failure = qa_revision_result(verification, qa_result)
                record_verification_failure(qa_failure, heal_count)
                heal_count += 1
                manager.transition(record, "healing", "إصلاح ملاحظات المراجعة")
                if use_fragment_route:
                    repaired = await regenerate_trusted_fragment_candidate(
                        "visual",
                        "visual_quality_review_failed",
                    )
                    if not repaired:
                        _fallback(
                            manager,
                            record,
                            "generation_failed",
                            _gallery_suggestions(record.locale),
                        )
                        return
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
    privacy_safe = not contains_learner_question_echo(artifact, question)
    if cache is not None and privacy_safe:
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
                receipt=VerificationReceipt(
                    deterministic_passed=True,
                    browser_passed=bool(browser_evidence),
                    failed_gate_count=0,
                    check_count=check_count,
                ),
                route_label=STABLE_ROUTE,
            )
        except (OSError, ValueError) as error:
            if not record.public:
                record.builder_diagnostics.append(
                    {"type": "cache_write_failed", "error_type": type(error).__name__}
                )
    sim_id = "sim_" + hashlib.sha256(artifact.encode("utf-8")).hexdigest()[:16]
    manager.artifacts[sim_id] = artifact
    record.share_eligible = privacy_safe
    record.artifact = artifact
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
    effective_model = effective_generation_model or (
        generated_execution["model"] if generated_execution else "mock/offline"
    )
    record.simulation = SimulationMetadata(
        sim_id=sim_id,
        title=understanding["title"],
        lang=understanding["lang"],
        direction="rtl" if understanding["lang"] == "ar" else "ltr",
        artifact_url=f"/api/sims/{sim_id}/download",
        tier="B",
        effective_model=effective_model,
        elapsed_ms=manager.elapsed_ms(record),
        check_count=check_count,
        heal_count=heal_count,
    )
    manager.emit(
        record,
        "result",
        {
            "result_url": f"/api/jobs/{record.job_id}",
            "sim_id": sim_id,
            "title": understanding["title"],
            "tier": "B",
        },
    )
    manager.transition(record, "complete", "verified_mock_result")
