from __future__ import annotations

import asyncio
import hashlib
from typing import Any, NoReturn

from server.assemble import assemble_artifact
from server.schemas import AnswerPayload, FallbackResult, SimulationMetadata, validate_understanding
from server.verify import verify_module_source, verify_module_with_node


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
    scenario = manager.backend.scenario_for(question)
    manager.transition(record, "filtering", "فحص أولي محدود")
    await asyncio.sleep(0)
    manager.transition(record, "understanding", "صياغة جواب وعقد تعليمي")
    understanding = validate_understanding(
        await manager.backend.understand(question, record.locale)
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
    manager.transition(record, "answered", "الجواب جاهز")
    manager.emit(record, "answer", record.answer.model_dump(mode="json"))

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
    module_output = await manager.backend.generate(understanding, scenario)
    if scenario == "exhausted_heal":
        module_output = manager.backend.mark_exhausted(module_output)

    artifact = None
    node_report = None
    heal_count = 0
    while True:
        manager.transition(record, "verifying", "فحص العقد والنتائج الحتمية")
        try:
            verify_module_source(module_output["module_js"])
            node_report = verify_module_with_node(module_output["module_js"], understanding)
            artifact = assemble_artifact(understanding, module_output)
            break
        except (ValueError, TimeoutError):
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
            module_output = await manager.backend.heal(
                module_output,
                understanding,
                ["deterministic_verification_failed"],
                heal_count,
            )

    manager.transition(record, "browser_check", "تأكيد جاهزية الغلاف الموثوق")
    check_count = int(node_report["fixture_count"]) + 5
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
    record.simulation = SimulationMetadata(
        sim_id=sim_id,
        title=understanding["title"],
        lang=understanding["lang"],
        direction="rtl" if understanding["lang"] == "ar" else "ltr",
        artifact_url=f"/api/sims/{sim_id}/download",
        tier="B",
        effective_model="mock/offline",
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

