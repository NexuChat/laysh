from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import server.pipeline as pipeline_module
from server.browser_verify import BrowserVerificationResult, verify_artifact_in_browser
from server.codex_backend import CodexBackend
from server.codex_runtime import CodexExecutor, StageExecution
from server.jobs import JobManager
from server.settings import Settings
from server.verify import VerificationResult
from server.vision_verify import evaluate_vision_verdict

ROOT = Path(__file__).parents[1]
ORIGINAL_VERIFY_CANDIDATE = pipeline_module.verify_candidate
MEASUREMENT_BY_CANDIDATE_HASH: dict[str, Measurement] = {}

# These are repository-owned, non-personal release benchmarks. The report stores only
# their stable IDs so arbitrary learner questions can never enter committed evidence.
BENCHMARK_CASES = (
    ("rainbow_refraction_ar", "لماذا تتكون قوس قزح بعد المطر؟", "ar"),
    ("seasons_tilt_en", "Why do seasons change during the year?", "en"),
    ("lever_torque_en", "How does a longer lever make lifting easier?", "en"),
    ("evaporation_ar", "لماذا يتبخر الماء أسرع في الحرارة؟", "ar"),
    ("magnetism_en", "How does distance affect the force between two magnets?", "en"),
)


def _understanding_contract_failures(data: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if data.get("simulatable"):
        actor = data.get("actor") or {}
        tracking_output = actor.get("tracking_output")
        outputs = (data.get("module_spec") or {}).get("outputs", [])
        if tracking_output is not None and tracking_output not in outputs:
            failures.append(
                {
                    "gate": "understanding_contract",
                    "code": "tracking_output_not_declared",
                    "expected": {"tracking_output_in_module_outputs": True},
                    "actual": {"tracking_output": tracking_output, "module_outputs": outputs},
                }
            )
        signature = actor.get("tracking_signature") or {}
        reference_color = signature.get("reference_color_rgb")
        reference_tolerance = signature.get("reference_tolerance")
        if (reference_color is None) != (reference_tolerance is None):
            failures.append(
                {
                    "gate": "understanding_contract",
                    "code": "partial_reference_signature",
                    "expected": {"reference_fields_both_null_or_present": True},
                    "actual": {
                        "reference_color_present": reference_color is not None,
                        "reference_tolerance_present": reference_tolerance is not None,
                    },
                }
            )
    return failures


def _sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class Measurement:
    case_id: str
    locale: str
    started_at: float = field(default_factory=time.monotonic)
    stage_timings: list[dict[str, Any]] = field(default_factory=list)
    verification_attempts: list[dict[str, Any]] = field(default_factory=list)
    candidate_attempt_by_hash: dict[str, int] = field(default_factory=dict)
    candidate_source_by_hash: dict[str, str] = field(default_factory=dict)
    understanding_summary: dict[str, Any] = field(default_factory=dict)

    def timed_stage(self, stage: str, elapsed_ms: int, model: str | None = None) -> None:
        item: dict[str, Any] = {"stage": stage, "elapsed_ms": elapsed_ms}
        if model:
            item["model"] = model
        self.stage_timings.append(item)

    def remember_candidate(self, result: StageExecution, attempt: int) -> StageExecution:
        source = str(result.data["module_js"])
        digest = _sha256(source)
        self.candidate_attempt_by_hash[digest] = attempt
        self.candidate_source_by_hash[digest] = source
        MEASUREMENT_BY_CANDIDATE_HASH[digest] = self
        return result

    def record_verification(self, attempt: int, gate: str, result: Any) -> None:
        failures = list(result.failures)
        self.verification_attempts.append(
            {
                "attempt": attempt,
                "gate_phase": gate,
                "passed": bool(result.passed),
                "check_count": int(result.check_count),
                "failures": failures,
            }
        )


class MeasuredBackend(CodexBackend):
    def __init__(self, *, measurement: Measurement, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.measurement = measurement

    async def _timed(
        self,
        name: str,
        action: Callable[[], Awaitable[StageExecution]],
    ) -> StageExecution:
        started = time.monotonic()
        try:
            result = await action()
        except Exception:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            self.measurement.timed_stage(name, elapsed_ms)
            raise
        elapsed_ms = int((time.monotonic() - started) * 1000)
        self.measurement.timed_stage(name, elapsed_ms, result.model)
        return result

    async def understand(self, *args: Any, **kwargs: Any) -> StageExecution:
        result = await self._timed(
            "understand", lambda: CodexBackend.understand(self, *args, **kwargs)
        )
        data = result.data
        self.measurement.understanding_summary = {
            "simulatable": data.get("simulatable"),
            "reason_code": data.get("reason_code"),
            "domain": data.get("domain"),
            "canonical_intent": data.get("canonical_intent"),
            "actor_id": (data.get("actor") or {}).get("id"),
            "action": data.get("action"),
            "fixture_count": len(data.get("checks", [])),
            "primary_parameter_id": (data.get("primary_parameter") or {}).get("id"),
            "tracking_output": (data.get("actor") or {}).get("tracking_output"),
            "contract_failures": _understanding_contract_failures(data),
        }
        return result

    async def generate(self, *args: Any, **kwargs: Any) -> StageExecution:
        result = await self._timed(
            "generate", lambda: CodexBackend.generate(self, *args, **kwargs)
        )
        return self.measurement.remember_candidate(result, 0)

    async def heal(self, *args: Any, **kwargs: Any) -> StageExecution:
        attempt = int(args[3] if len(args) > 3 else kwargs["attempt"])
        result = await self._timed(
            f"heal_{attempt}", lambda: CodexBackend.heal(self, *args, **kwargs)
        )
        return self.measurement.remember_candidate(result, attempt)

    async def qa(self, *args: Any, **kwargs: Any) -> StageExecution:
        return await self._timed(
            "qa", lambda: CodexBackend.qa(self, *args, **kwargs)
        )

    async def vision(self, *args: Any, **kwargs: Any) -> StageExecution:
        result = await self._timed(
            "vision", lambda: CodexBackend.vision(self, *args, **kwargs)
        )
        evaluated = evaluate_vision_verdict(result.data)
        if not evaluated.passed and evaluated.failure is not None:
            attempt = max(self.measurement.candidate_attempt_by_hash.values(), default=0)
            self.measurement.verification_attempts.append(
                {
                    "attempt": attempt,
                    "gate_phase": "semantic_vision",
                    "passed": False,
                    "check_count": 1,
                    "failures": [evaluated.failure],
                }
            )
        return result


def _measured_verify_candidate(
    module_output: dict[str, Any], understanding: dict[str, Any]
) -> VerificationResult:
    started = time.monotonic()
    result = ORIGINAL_VERIFY_CANDIDATE(module_output, understanding)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    digest = _sha256(str(module_output["module_js"]))
    measurement = MEASUREMENT_BY_CANDIDATE_HASH[digest]
    measurement.timed_stage("deterministic_verify", elapsed_ms)
    attempt = measurement.candidate_attempt_by_hash.get(digest, 0)
    measurement.record_verification(attempt, "deterministic", result)
    return result


def _measured_browser_verifier(
    measurement: Measurement,
) -> Callable[[str], BrowserVerificationResult]:

    def browser(artifact: str) -> BrowserVerificationResult:
        started = time.monotonic()
        result = verify_artifact_in_browser(artifact)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        measurement.timed_stage("browser_verify", elapsed_ms)
        attempt = 0
        for digest, source in measurement.candidate_source_by_hash.items():
            if source in artifact:
                attempt = measurement.candidate_attempt_by_hash[digest]
                break
        measurement.record_verification(attempt, "browser", result)
        return result

    return browser


async def _run_case(
    case_id: str,
    question: str,
    locale: str,
    settings: Settings,
    concurrency: asyncio.Semaphore,
) -> dict[str, Any]:
    measurement = Measurement(case_id=case_id, locale=locale)
    executor = CodexExecutor(
        stage_timeout_seconds=settings.public_stage_timeout_seconds,
        evidence_stage_timeout_seconds=settings.evidence_stage_timeout_seconds,
        record_runtime=False,
        service_tier=settings.service_tier,
    )
    backend = MeasuredBackend(measurement=measurement, executor=executor, settings=settings)
    browser = _measured_browser_verifier(measurement)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=settings.public_job_timeout_seconds,
        evidence_job_timeout_seconds=settings.evidence_job_timeout_seconds,
        browser_verifier=browser,
        cache=None,
        max_concurrent_jobs=1,
        max_queued_jobs=0,
    )
    async with concurrency:
        record = manager.start(question, locale, public=True)
        if record.task is None:
            raise RuntimeError("public benchmark job did not start")
        await record.task
    total_elapsed_ms = manager.elapsed_ms(record)
    first_answer_ms = next(
        (
            event.payload.elapsed_ms
            for event in record.events
            if event.type == "stage" and getattr(event.payload, "stage", None) == "understanding"
        ),
        None,
    )
    result = {
        "case_id": case_id,
        "locale": locale,
        "status": record.status,
        "fallback_reason": record.fallback.reason_code if record.fallback else None,
        "total_elapsed_ms": total_elapsed_ms,
        "first_answer_ms": first_answer_ms,
        "heal_count": record.simulation.heal_count if record.simulation else len(
            [item for item in measurement.stage_timings if item["stage"].startswith("heal_")]
        ),
        "understanding": measurement.understanding_summary,
        "stage_timings": measurement.stage_timings,
        "verification_attempts": measurement.verification_attempts,
    }
    summary_keys = ("case_id", "status", "total_elapsed_ms", "heal_count")
    print(json.dumps({key: result[key] for key in summary_keys}))
    return result


async def run(
    output: Path,
    phase: str,
    max_concurrency: int,
    selected_case_ids: frozenset[str],
) -> int:
    settings = Settings.from_env()
    if settings.backend != "codex":
        raise RuntimeError("LAYSH_CODEX_BACKEND=codex is required for live measurement")
    concurrency = asyncio.Semaphore(max_concurrency)
    cases = tuple(
        case for case in BENCHMARK_CASES if not selected_case_ids or case[0] in selected_case_ids
    )
    unknown = selected_case_ids - {case[0] for case in cases}
    if unknown:
        raise ValueError(f"unknown benchmark case IDs: {sorted(unknown)}")
    pipeline_module.verify_candidate = _measured_verify_candidate
    try:
        results = await asyncio.gather(
            *(
                _run_case(case_id, question, locale, settings, concurrency)
                for case_id, question, locale in cases
            )
        )
    finally:
        pipeline_module.verify_candidate = ORIGINAL_VERIFY_CANDIDATE
    completed = [result for result in results if result["status"] == "complete"]
    report = {
        "schema_version": "1.0",
        "phase": phase,
        "runtime_mode": "public_ephemeral",
        "job_timeout_seconds": settings.public_job_timeout_seconds,
        "case_count": len(results),
        "success_count": len(completed),
        "success_rate": len(completed) / len(results),
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--max-concurrency", type=int, default=1, choices=(1, 2))
    parser.add_argument("--case-id", action="append", default=[])
    arguments = parser.parse_args()
    return asyncio.run(
        run(
            arguments.output,
            arguments.phase,
            arguments.max_concurrency,
            frozenset(arguments.case_id),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
