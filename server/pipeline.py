from __future__ import annotations

import asyncio
import hashlib
import tempfile
from pathlib import Path
from typing import Any, NoReturn

from server.cache import VerificationReceipt
from server.codex_backend import RuntimeContext
from server.codex_runtime import CodexRuntimeError, StageExecution
from server.schemas import (
    AnswerPayload,
    ContractError,
    FallbackResult,
    SimulationMetadata,
    action_contract_report,
    validate_module_output,
    validate_understanding,
)
from server.verify import (
    VerificationResult,
    formula_presentation_report,
    misconception_report,
    verify_candidate,
)
from server.vision_verify import evaluate_vision_verdict


class PipelineCancelled(Exception):
    pass


def _localized(record: Any, arabic: str, english: str) -> str:
    return english if record.locale == "en" else arabic


def _default_suggestions(record: Any) -> list[str]:
    if record.locale == "en":
        return ["Why does the Moon change shape?", "Why do some objects float?"]
    return ["لماذا يتغير شكل القمر؟", "لماذا تطفو بعض الأجسام؟"]


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


def _complete_from_cache(manager: Any, record: Any, cached: Any) -> None:
    manager.transition(
        record,
        "browser_check",
        _localized(record, "استخدام إيصال تحقق مخزّن", "Using a stored verification receipt"),
    )
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
    sim_id = cached.cache_id
    manager.artifacts[sim_id] = cached.artifact
    record.artifact = cached.artifact
    record.simulation = SimulationMetadata(
        sim_id=sim_id,
        title=cached.title,
        lang=cached.locale,
        direction=cached.direction,
        artifact_url=f"/api/sims/{sim_id}/download",
        share_url=f"/sims/{sim_id}",
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

    async def repair_understanding_contract(
        candidate: dict[str, Any],
        failures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        repair = getattr(manager.backend, "repair_understanding", None)
        if repair is None:
            result = await manager.backend.understand(
                question,
                record.locale,
                runtime_context=runtime_context,
            )
        else:
            result = await repair(
                candidate,
                failures,
                record.locale,
                runtime_context=runtime_context,
            )
        return validate_understanding(stage_data(result, "understand_retry"))

    cache = manager.cache
    manager.transition(
        record,
        "filtering",
        _localized(record, "فحص أولي محدود", "Running a limited precheck"),
        emit_event=False,
    )
    await asyncio.sleep(0)
    if cache is not None:
        exact = cache.lookup_exact(question=question, locale=record.locale)
        if exact is not None and exact.answer is not None:
            record.answer = AnswerPayload.model_validate(exact.answer)
            manager.emit(record, "answer", record.answer.model_dump(mode="json"))
            manager.transition(
                record,
                "cache_lookup",
                _localized(record, "فحص النتائج الموثقة", "Checking verified results"),
            )
            _complete_from_cache(manager, record, exact)
            return
    manager.transition(
        record,
        "understanding",
        _localized(record, "صياغة جواب وعقد تعليمي", "Drafting an answer and lesson contract"),
        emit_event=False,
    )
    initial_understanding = stage_data(
        await manager.backend.understand(
            question,
            record.locale,
            runtime_context=runtime_context,
        ),
        "understand",
    )
    try:
        understanding = validate_understanding(initial_understanding)
    except ContractError as error:
        if not record.public:
            raise
        manager.emit(
            record,
            "stage",
            {
                "stage": "understanding_retry",
                "detail": _localized(
                    record,
                    "إعادة ضبط عقد القياس مرة واحدة",
                    "Rebuilding the measurement contract once",
                ),
                "elapsed_ms": manager.elapsed_ms(record),
            },
        )
        understanding = await repair_understanding_contract(
            initial_understanding,
            [
                {
                    "gate": "understanding_contract",
                    "code": "cross_field_invalid",
                    "expected": {"cross_field_contract_valid": True},
                    "actual": {"diagnostic": str(error)[:180]},
                }
            ],
        )

    if not understanding["safe"]:
        _reject(
            manager,
            record,
            understanding["reason_code"],
            understanding["suggestions"],
        )

    misconception_failures, _ = misconception_report(understanding)
    if misconception_failures and record.public:
        manager.emit(
            record,
            "stage",
            {
                "stage": "understanding_retry",
                "detail": _localized(
                    record,
                    "إعادة ضبط التصحيح المفاهيمي مرة واحدة",
                    "Rebuilding the corrective explanation once",
                ),
                "elapsed_ms": manager.elapsed_ms(record),
            },
        )
        understanding = await repair_understanding_contract(
            understanding,
            misconception_failures,
        )
        if not understanding["safe"]:
            _reject(
                manager,
                record,
                understanding["reason_code"],
                understanding["suggestions"],
            )
        misconception_failures, _ = misconception_report(understanding)

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
    manager.transition(
        record,
        "answered",
        _localized(record, "الجواب جاهز", "The answer is ready"),
        emit_event=False,
    )
    manager.emit(record, "answer", record.answer.model_dump(mode="json"))
    manager.emit(
        record,
        "stage",
        {
            "stage": "understanding",
            "detail": _localized(
                record,
                "اكتمل فهم السؤال وصياغة الجواب",
                "The question is understood and the answer is ready",
            ),
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

    if misconception_failures:
        _fallback(
            manager,
            record,
            "corrective_misconception_unresolved",
            understanding["suggestions"] or _default_suggestions(record),
        )
        return

    action_failures = action_contract_report(understanding)
    if action_failures:
        if not record.public:
            record.builder_diagnostics.append(
                {"type": "action_contract_failure", "failures": action_failures}
            )
        _fallback(
            manager,
            record,
            "action_contract_unrepresentable",
            understanding["suggestions"] or _default_suggestions(record),
        )
        return

    manager.transition(
        record,
        "cache_lookup",
        _localized(record, "فحص النتائج الموثقة", "Checking verified results"),
    )
    if cache is not None:
        cached = cache.lookup(
            question=question,
            locale=understanding["lang"],
            domain=understanding["domain"],
            canonical_intent=understanding["canonical_intent"],
        )
        if cached is not None:
            _complete_from_cache(manager, record, cached)
            return
    manager.transition(
        record,
        "generating",
        _localized(record, "بناء وحدة المحاكاة", "Building the simulation module"),
    )
    try:
        generated = await manager.backend.generate(
            understanding,
            scenario,
            runtime_context=runtime_context,
        )
    except CodexRuntimeError as error:
        if error.code != "stage_timeout" or not record.public:
            raise
        _fallback(manager, record, "generation_timeout", _default_suggestions(record))
        return
    module_output = validate_module_output(stage_data(generated, "generate"))
    if scenario == "exhausted_heal":
        module_output = manager.backend.mark_exhausted(module_output)

    verification = None
    heal_count = 0
    fixture_refresh_count = 0
    browser_evidence: dict[str, Any] | None = None
    vision_verdict: dict[str, Any] | None = None
    while True:
        if record.status != "verifying":
            manager.transition(
                record,
                "verifying",
                _localized(
                    record,
                    "فحص العقد والنتائج الحتمية",
                    "Checking the contract and deterministic results",
                ),
            )
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
                vision_result = None
                vision_attempts = (1,) if record.public else (1, 2)
                for vision_attempt in vision_attempts:
                    try:
                        with tempfile.TemporaryDirectory(prefix="laysh-vision-") as temporary:
                            frame_paths: list[Path] = []
                            for index, frame in enumerate(browser_result.vision_frames, start=1):
                                path = Path(temporary) / f"frame-{index}.png"
                                path.write_bytes(frame)
                                frame_paths.append(path)
                            vision_stage = await manager.backend.vision(
                                understanding,
                                frame_paths,
                                browser_result.evidence.get("visionFrameStates", []),
                                runtime_context=runtime_context,
                            )
                        vision_verdict = stage_data(vision_stage, "vision")
                        vision_result = evaluate_vision_verdict(vision_verdict)
                        break
                    except CodexRuntimeError as error:
                        if error.code != "stage_timeout":
                            raise
                        if not record.public:
                            record.builder_diagnostics.append(
                                {
                                    "type": "vision_timeout",
                                    "attempt": vision_attempt,
                                    "code": error.code,
                                    "candidate_sha256": hashlib.sha256(
                                        module_output["module_js"].encode("utf-8")
                                    ).hexdigest(),
                                }
                            )
                        if vision_attempt < vision_attempts[-1]:
                            continue
                        _fallback(
                            manager,
                            record,
                            "vision_inconclusive",
                            _default_suggestions(record),
                        )
                        return
                if vision_result is None:
                    raise RuntimeError("vision retry loop completed without an outcome")
                if vision_result.passed:
                    verification = VerificationResult(
                        passed=True,
                        check_count=verification.check_count + browser_result.check_count + 1,
                        failures=[],
                        artifact=verification.artifact,
                        node_report=verification.node_report,
                    )
                    break
                if vision_result.failure is None:
                    raise RuntimeError("failed vision verdict omitted its diagnostic")
                verification = VerificationResult(
                    passed=False,
                    check_count=verification.check_count + browser_result.check_count + 1,
                    failures=[vision_result.failure],
                    artifact=None,
                    node_report=verification.node_report,
                )
            else:
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
        if suspect_fixtures and record.public:
            _fallback(
                manager,
                record,
                "fixture_integrity_unresolved",
                _default_suggestions(record),
            )
            return
        if suspect_fixtures and not record.public:
            if fixture_refresh_count >= 1:
                _fallback(
                    manager,
                    record,
                    "fixture_integrity_unresolved",
                    _default_suggestions(record),
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
                    "detail": _localized(
                        record,
                        "إعادة تدقيق عقد القياس المرجعي",
                        "Rechecking the reference measurement contract",
                    ),
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
        maximum_heal_attempts = 1 if record.public else 2
        if heal_count >= maximum_heal_attempts:
            _fallback(
                manager,
                record,
                "verification_exhausted",
                _default_suggestions(record),
            )
            return
        if record.public:
            remaining_seconds = (
                manager.public_job_timeout_seconds
                - manager.elapsed_ms(record) / 1000
            )
            if remaining_seconds < manager.public_heal_cycle_reserve_seconds:
                _fallback(
                    manager,
                    record,
                    "insufficient_heal_budget",
                    _default_suggestions(record),
                )
                return
        heal_count += 1
        manager.transition(
            record,
            "healing",
            _localized(
                record,
                "إصلاح فشل تحقق محدد",
                "Repairing a specific verification failure",
            ),
        )
        try:
            healed = await manager.backend.heal(
                module_output,
                understanding,
                verification.failures,
                heal_count,
                runtime_context=runtime_context,
            )
        except CodexRuntimeError as error:
            if error.code != "stage_timeout" or not record.public:
                raise
            _fallback(manager, record, "healing_timeout", _default_suggestions(record))
            return
        module_output = validate_module_output(stage_data(healed, f"heal_{heal_count}"))

    qa_outcome: dict[str, Any] | None = None
    if heal_count or record.promote_golden:
        manager.emit(
            record,
            "stage",
            {
                "stage": "qa",
                "detail": _localized(
                    record,
                    "مراجعة المرشح المُصلح",
                    "Reviewing the repaired candidate",
                ),
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
                "actor_action_tracking",
                "browser_readiness",
                "interface",
                "invariant",
                "mobile_overlay_safe_band",
                "render_output_consistency",
                "runtime_init",
                "semantic_vision",
                "security",
                "source_size",
                "syntax_runtime",
            ],
        }
        qa_result = None
        qa_attempts = (1,) if record.public else (1, 2)
        for qa_attempt in qa_attempts:
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
                if qa_attempt < qa_attempts[-1]:
                    manager.emit(
                        record,
                        "stage",
                        {
                            "stage": "qa_retry",
                            "detail": _localized(
                                record,
                                "إعادة مراجعة QA المختصرة مرة واحدة",
                                "Repeating the concise QA review once",
                            ),
                            "elapsed_ms": manager.elapsed_ms(record),
                        },
                    )
                    continue
                if record.public:
                    _fallback(
                        manager,
                        record,
                        "qa_inconclusive",
                        _default_suggestions(record),
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
                "vision": vision_verdict or {},
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
                _default_suggestions(record),
            )
            return
        qa_outcome = qa_result

    manager.transition(
        record,
        "browser_check",
        _localized(
            record,
            "تأكيد جاهزية الغلاف الموثوق",
            "Confirming trusted-shell readiness",
        ),
    )
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
    cached_entry = None
    if cache is not None:
        try:
            cached_entry = cache.write_verified(
                question=question,
                locale=understanding["lang"],
                domain=understanding["domain"],
                canonical_intent=understanding["canonical_intent"],
                artifact=artifact,
                title=understanding["title"],
                summary=understanding["tldr"],
                direction="rtl" if understanding["lang"] == "ar" else "ltr",
                tier="B",
                answer=record.answer.model_dump(mode="json") if record.answer else None,
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
    sim_id = (
        cached_entry.cache_id
        if cached_entry is not None
        else "sim_" + hashlib.sha256(artifact.encode("utf-8")).hexdigest()[:16]
    )
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
        share_url=f"/sims/{sim_id}" if cached_entry is not None else None,
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
