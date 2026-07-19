from __future__ import annotations

import asyncio
import hashlib
from typing import Any, NoReturn

from server.cache import VerificationReceipt
from server.codex_backend import RuntimeContext
from server.codex_runtime import CodexRuntimeError, StageExecution
from server.schemas import (
    AnswerPayload,
    FallbackResult,
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

    def stage_data(
        result: dict[str, Any] | StageExecution,
        stage: str,
    ) -> dict[str, Any]:
        if isinstance(result, StageExecution):
            record.stage_executions.append(
                {
                    "stage": stage,
                    "model": result.model,
                    "elapsed_ms": result.elapsed_ms,
                    "thread_id": result.thread_id,
                }
            )
            return result.data
        return result

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
    understanding = validate_understanding(
        stage_data(
            await manager.backend.understand(
                question,
                record.locale,
                runtime_context=runtime_context,
            ),
            "understand",
        )
    )

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
            stage_data(
                await manager.backend.understand(
                    question,
                    record.locale,
                    runtime_context=runtime_context,
                ),
                "understand_retry",
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
    generated = await manager.backend.generate(
        understanding,
        scenario,
        runtime_context=runtime_context,
    )
    module_output = validate_module_output(stage_data(generated, "generate"))
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
                    ["لماذا يتغير شكل القمر؟", "لماذا تطفو بعض الأجسام؟"],
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
                stage_data(
                    await manager.backend.understand(
                        question,
                        record.locale,
                        runtime_context=runtime_context,
                    ),
                    "understand_retry",
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
                ["لماذا يتغير شكل القمر؟", "لماذا تطفو بعض الأجسام؟"],
            )
            return
        heal_count += 1
        manager.transition(record, "healing", "إصلاح فشل تحقق محدد")
        module_output = validate_module_output(
            stage_data(
                await manager.backend.heal(
                    module_output,
                    understanding,
                    verification.failures,
                    heal_count,
                    runtime_context=runtime_context,
                ),
                f"heal_{heal_count}",
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
                qa_result = stage_data(
                    await manager.backend.qa(
                        module_output,
                        understanding,
                        gate_outcome,
                        runtime_context=runtime_context,
                    ),
                    "qa" if qa_attempt == 1 else "qa_retry",
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
                        ["لماذا يتغير شكل القمر؟", "لماذا تطفو بعض الأجسام؟"],
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
                ["لماذا يتغير شكل القمر؟", "لماذا تطفو بعض الأجسام؟"],
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
    if cache is not None:
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
            )
        except (OSError, ValueError) as error:
            if not record.public:
                record.builder_diagnostics.append(
                    {"type": "cache_write_failed", "error_type": type(error).__name__}
                )
    sim_id = "sim_" + hashlib.sha256(artifact.encode("utf-8")).hexdigest()[:16]
    manager.artifacts[sim_id] = artifact
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
            for execution in reversed(record.stage_executions)
            if execution["model"] != manager.backend.__class__.__name__
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
