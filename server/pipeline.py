from __future__ import annotations

import asyncio
import hashlib
from typing import Any, NoReturn

from jsonschema import ValidationError

from server.cache import VerificationReceipt
from server.codex_backend import RuntimeContext
from server.codex_runtime import CodexRuntimeError, StageExecution
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


class PipelineCancelled(Exception):
    pass


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
                )
            return result.data
        return result

    def record_stage_failure(stage: str, error: CodexRuntimeError) -> None:
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
        )

    async def stage_result(stage: str, operation: Any) -> dict[str, Any]:
        try:
            return stage_data(await operation, stage)
        except CodexRuntimeError as error:
            record_stage_failure(stage, error)
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
    if cache is not None:
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
    module_output = validate_module_output(
        await stage_result(
            "generate",
            manager.backend.generate(
                understanding,
                scenario,
                runtime_context=runtime_context,
            ),
        )
    )
    if scenario == "exhausted_heal":
        module_output = manager.backend.mark_exhausted(module_output)

    verification = None
    heal_count = 0
    fixture_refresh_count = 0
    browser_evidence: dict[str, Any] | None = None
    while True:
        if record.status != "verifying":
            manager.transition(record, "verifying", "فحص العقد والنتائج الحتمية")
        verification = verify_candidate(module_output, understanding)
        if verification.passed:
            if verification.artifact is None:
                raise RuntimeError("deterministic verification omitted its artifact")
            browser_result = await asyncio.to_thread(
                manager.browser_verifier,
                verification.artifact,
            )
            browser_evidence = browser_result.evidence
            if browser_result.passed:
                verification = VerificationResult(
                    passed=True,
                    check_count=verification.check_count + browser_result.check_count,
                    failures=[],
                    artifact=verification.artifact,
                    node_report=verification.node_report,
                )
                break
            verification = VerificationResult(
                passed=False,
                check_count=verification.check_count + browser_result.check_count,
                failures=browser_result.failures,
                artifact=None,
                node_report=verification.node_report,
            )
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

    qa_outcome: dict[str, Any] | None = None
    if heal_count or record.promote_golden:
        manager.emit(
            record,
            "stage",
            {
                "stage": "qa",
                "detail": "مراجعة المرشح المُصلح",
                "elapsed_ms": manager.elapsed_ms(record),
            },
        )
        if verification is None:
            raise RuntimeError("QA requires a verified candidate")
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
                return
        if qa_result is None:
            raise RuntimeError("QA retry loop completed without an outcome")
        if not record.public:
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
        if not qa_result["approved"]:
            if not record.public:
                record.builder_diagnostics.append(
                    {
                        "type": "qa_rejected",
                        "issues": qa_result["issues"],
                        "visual_richness": qa_result.get("visual_richness"),
                    }
                )
            _fallback(
                manager,
                record,
                "qa_rejected",
                _gallery_suggestions(record.locale),
            )
            return
        qa_outcome = qa_result

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
    effective_model = (
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
