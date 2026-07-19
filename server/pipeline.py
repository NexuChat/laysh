from __future__ import annotations

import asyncio
import hashlib
from typing import Any, NoReturn

from server.codex_backend import RuntimeContext
from server.codex_runtime import StageExecution
from server.schemas import (
    AnswerPayload,
    FallbackResult,
    SimulationMetadata,
    validate_module_output,
    validate_understanding,
)
from server.verify import VerificationResult, verify_candidate


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

    record.answer = AnswerPayload(
        tldr=understanding["tldr"],
        key_formula=understanding["key_formula"],
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
    while True:
        manager.transition(record, "verifying", "فحص العقد والنتائج الحتمية")
        verification = verify_candidate(module_output, understanding)
        if verification.passed:
            break
        record_verification_failure(verification, heal_count)
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

    if heal_count:
        manager.emit(
            record,
            "stage",
            {
                "stage": "qa",
                "detail": "مراجعة المرشح المُصلح",
                "elapsed_ms": manager.elapsed_ms(record),
            },
        )
        qa_result = stage_data(
            await manager.backend.qa(
                module_output,
                understanding,
                runtime_context=runtime_context,
            ),
            "qa",
        )
        if not qa_result["approved"]:
            replacement = qa_result["replacement_module_js"]
            if replacement is None:
                _fallback(
                    manager,
                    record,
                    "qa_rejected",
                    ["لماذا يتغير شكل القمر؟", "لماذا تطفو بعض الأجسام؟"],
                )
                return
            module_output = validate_module_output(
                {**module_output, "module_js": replacement}
            )
            manager.transition(record, "healing", "تطبيق تصحيح مراجعة QA")
            manager.transition(record, "verifying", "إعادة جميع الفحوصات بعد QA")
            verification = verify_candidate(module_output, understanding)
            if not verification.passed:
                record_verification_failure(verification, heal_count)
                _fallback(
                    manager,
                    record,
                    "qa_reverification_failed",
                    ["لماذا يتغير شكل القمر؟", "لماذا تطفو بعض الأجسام؟"],
                )
                return

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
            "evidence": ["closed_schema", "restricted_source", "node_runtime", "fixtures"],
        },
    )
    sim_id = "sim_" + hashlib.sha256(artifact.encode("utf-8")).hexdigest()[:16]
    manager.artifacts[sim_id] = artifact
    record.artifact = artifact
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
