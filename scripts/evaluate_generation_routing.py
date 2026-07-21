from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Coroutine
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

CALL_CAP = 12
CASE_TIMEOUT_SECONDS = 600
LATENCY_TOLERANCE_RATIO = 1.10
EVALUATED_TIER = "bounded_single_parameter_v1"
EVALUATED_MODELS = ("gpt-5.6-terra", "gpt-5.6-sol")
ABORT_CONDITIONS = (
    "projected_live_calls_exceed_12",
    "case_elapsed_seconds_exceed_600",
    "non_gpt_5_6_model_observed",
    "nontransient_runtime_or_schema_failure",
    "individual_candidate_stops_after_one_same_model_heal",
)
ROOT = Path(__file__).parents[1]
RAW_EVIDENCE_PATH = ROOT / "out" / "evidence" / "route-02-raw.json"
REPORT_PATH = ROOT / "out" / "evidence" / "route-02-routing-evaluation.json"
LIVE_LOCK_PATH = ROOT / "out" / "evidence" / ".route-02-live.lock"
FIXTURE_IDS = ("moon_phases_ar", "pendulum_ar")
USAGE_SOURCE = "codex_app_server_account_usage_read"
LIVE_CONFIRMATION = "ROUTE-02-LIVE-SPEND"
PRIOR_ABORTED_EVIDENCE_PATHS = (
    "out/evidence/route-02-aborted-preflight.json",
    "out/evidence/route-02-aborted-guard-red-2.json",
)

# These paths are the complete code/config/schema surface that can influence the
# fixed generation payload or its deterministic verdict. Keep the data-only
# routing decision separate: the measured cohort is what decides that file.
DIRECT_PROVENANCE_PATHS = {
    "evaluator_sha256": "scripts/evaluate_generation_routing.py",
    "runtime_sha256": "server/codex_runtime.py",
    "generate_prompt_sha256": "server/prompts/generate_module.md",
    "heal_prompt_sha256": "server/prompts/heal_module.md",
    "qa_prompt_sha256": "server/prompts/qa.md",
    "module_verifier_sha256": "scripts/verify_module.mjs",
    "server_verifier_sha256": "server/verify.py",
}
SOURCE_SNAPSHOT_PATHS = tuple(
    sorted(
        {
            *DIRECT_PROVENANCE_PATHS.values(),
            ".env.example",
            "deploy/laysh.service",
            "scripts/check_artifact.mjs",
            "server/assemble.py",
            "server/browser_verify.py",
            "server/codex_backend.py",
            "server/goldens.py",
            "server/model_routing.py",
            "server/scene_geometry.py",
            "server/schemas.py",
            "server/schemas/module.schema.json",
            "server/schemas/qa.schema.json",
            "server/schemas/understand.schema.json",
            "server/settings.py",
            "server/shared_state.py",
            "sim_shell/contract.js",
            "sim_shell/shell.css",
            "sim_shell/shell.html",
            "sim_shell/shell.js",
            "web/fonts/free-sans-arabic-latin.woff2",
            "web/fonts/free-serif-arabic-display.woff2",
        }
    )
)
FIXTURE_GOLDEN_PATHS = {
    "moon_phases_ar": "out/cache/golden/moon_phases.json",
    "pendulum_ar": "out/cache/golden/pendulum.json",
}
EVIDENCE_ONLY_DESCENDANT_PATHS = frozenset(
    {
        "docs/build-spec/g7-continuation/BUILD-NOTEBOOK.md",
        "out/evidence/route-02-raw.json",
        "out/evidence/route-02-routing-evaluation.json",
        "server/routing_decision.json",
    }
)


@dataclass(frozen=True, slots=True)
class LiveEvaluationDependencies:
    usage_reader: Callable[[], Coroutine[Any, Any, int]]
    case_evaluator: Callable[..., Coroutine[Any, Any, dict[str, Any]]]
    executor_factory: Callable[[], Any]
    sleep: Callable[[float], Coroutine[Any, Any, None]]


class ClosedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LiveCallEvidence(ClosedEvidence):
    stage: Literal["generate", "heal", "qa"]
    model: Literal["gpt-5.6-terra", "gpt-5.6-sol"]
    effort: Literal["medium"]
    why_model_was_called: Literal[
        "fixed_spec_candidate",
        "one_same_model_repair_after_gate_failure",
        "post_heal_closed_review",
    ]
    elapsed_ms: int = Field(ge=0)
    outcome: Literal["completed", "failed"]
    thread_id_captured: bool
    failure_code: Annotated[
        str, Field(max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    ] | None
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_outcome(self) -> LiveCallEvidence:
        if self.outcome == "completed":
            if self.failure_code is not None:
                raise ValueError("completed call cannot carry a failure code")
            if self.input_tokens + self.output_tokens <= 0:
                raise ValueError("completed live call must carry observed token usage")
        elif self.failure_code is None:
            raise ValueError("failed call must carry a failure code")
        return self


class RoutingCaseEvidence(ClosedEvidence):
    fixture_id: str = Field(min_length=1, max_length=80)
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_model: Literal["gpt-5.6-terra", "gpt-5.6-sol"]
    passed: bool
    elapsed_ms: int = Field(ge=0, le=CASE_TIMEOUT_SECONDS * 1000)
    live_calls: list[LiveCallEvidence] = Field(min_length=1, max_length=3)
    heal_count: int = Field(ge=0, le=1)
    failure_code: Annotated[
        str, Field(max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    ] | None

    @model_validator(mode="after")
    def validate_call_sequence(self) -> RoutingCaseEvidence:
        stages = [call.stage for call in self.live_calls]
        if stages[0] != "generate" or stages.count("generate") != 1:
            raise ValueError("case must contain exactly one first generate call")
        if stages not in (["generate"], ["generate", "heal"], ["generate", "heal", "qa"]):
            raise ValueError("case call sequence is invalid")
        if self.live_calls[0].model != self.generation_model:
            raise ValueError("fresh generation model mismatch")
        heals = [call for call in self.live_calls if call.stage == "heal"]
        if len(heals) != self.heal_count:
            raise ValueError("heal count does not match calls")
        if heals and heals[0].model != self.generation_model:
            raise ValueError("cross model heal forbidden in evaluation")
        qa_calls = [call for call in self.live_calls if call.stage == "qa"]
        if qa_calls and qa_calls[0].model != "gpt-5.6-sol":
            raise ValueError("evaluation QA must match production Sol QA")
        expected_reasons = {
            "generate": "fixed_spec_candidate",
            "heal": "one_same_model_repair_after_gate_failure",
            "qa": "post_heal_closed_review",
        }
        if any(
            call.why_model_was_called != expected_reasons[call.stage]
            for call in self.live_calls
        ):
            raise ValueError("call stage and reason disagree")
        failed_indexes = [
            index
            for index, call in enumerate(self.live_calls)
            if call.outcome == "failed"
        ]
        if failed_indexes and failed_indexes != [len(self.live_calls) - 1]:
            raise ValueError("a failed call must terminate the case")
        if self.passed and failed_indexes:
            raise ValueError("a passing case cannot contain a failed call")
        if self.passed and any(
            call.outcome != "completed" or not call.thread_id_captured
            for call in self.live_calls
        ):
            raise ValueError("passing calls require completed threaded evidence")
        if self.passed and any(call.elapsed_ms <= 0 for call in self.live_calls):
            raise ValueError("passing calls require positive elapsed time")
        if sum(call.elapsed_ms for call in self.live_calls) > self.elapsed_ms:
            raise ValueError("case elapsed time is below its call timings")
        if self.heal_count and self.passed and stages != ["generate", "heal", "qa"]:
            raise ValueError("a passing healed candidate requires post-heal QA")
        if self.passed and self.failure_code is not None:
            raise ValueError("passing case cannot carry a failure code")
        if not self.passed and self.failure_code is None:
            raise ValueError("case result and failure code disagree")
        if failed_indexes and self.failure_code != self.live_calls[-1].failure_code:
            raise ValueError("case failure code must match the failed call")
        return self


class AccountUsageEvidence(ClosedEvidence):
    observed: bool
    source: Literal[
        "codex_app_server_account_usage_read",
        "unavailable",
        "incomplete_account_usage_observation",
        "invalid_account_usage_observation",
    ]
    terra_delta_units: int | None = Field(default=None, ge=0)
    sol_delta_units: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_observation(self) -> AccountUsageEvidence:
        if self.observed:
            if self.source != USAGE_SOURCE:
                raise ValueError("observed account usage source is not trusted")
            if not self.terra_delta_units or not self.sol_delta_units:
                raise ValueError("observed live usage deltas must be positive")
        elif self.terra_delta_units is not None or self.sol_delta_units is not None:
            raise ValueError("unobserved usage cannot carry deltas")
        return self


class UsageObservationEvidence(ClosedEvidence):
    model: Literal["gpt-5.6-terra", "gpt-5.6-sol"]
    source: Literal["codex_app_server_account_usage_read"]
    delta_units: int = Field(gt=0)
    turn_reported_tokens: int = Field(gt=0)
    sample_count: int = Field(ge=2, le=10)
    observed_before_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T.*Z$")
    observed_after_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T.*Z$")

    @model_validator(mode="after")
    def validate_cross_check(self) -> UsageObservationEvidence:
        if self.delta_units < self.turn_reported_tokens:
            raise ValueError("account counter delta is below per-turn usage")
        before = _parse_utc_timestamp(self.observed_before_at)
        after = _parse_utc_timestamp(self.observed_after_at)
        if after <= before:
            raise ValueError("account observation timestamps are not increasing")
        return self


class FixturePromptFingerprint(ClosedEvidence):
    fixture_id: str = Field(min_length=1, max_length=80)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PriorAbortedCallEvidence(ClosedEvidence):
    path: Literal[
        "out/evidence/route-02-aborted-preflight.json",
        "out/evidence/route-02-aborted-guard-red-2.json",
    ]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: Literal["gpt-5.6-terra", "gpt-5.6-sol"]
    elapsed_ms_approximate: int = Field(gt=0)
    live_call_count_conservative: Literal[1]


class EvaluationProvenance(ClosedEvidence):
    head_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    head_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worktree_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worktree_dirty: bool
    source_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generate_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    heal_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qa_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    module_verifier_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    server_verifier_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_prompt_fingerprints: list[FixturePromptFingerprint] = Field(
        min_length=len(FIXTURE_IDS), max_length=len(FIXTURE_IDS)
    )

    @model_validator(mode="after")
    def validate_fixture_set(self) -> EvaluationProvenance:
        fixture_ids = [item.fixture_id for item in self.fixture_prompt_fingerprints]
        if set(fixture_ids) != set(FIXTURE_IDS) or len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("evaluation fixture fingerprints are incomplete")
        return self


class InflightEvidence(ClosedEvidence):
    event: Literal[
        "account_usage_before",
        "before_case",
        "before_stage",
        "after_stage",
        "after_case",
        "account_usage_after",
    ]
    fixture_id: str | None = Field(default=None, max_length=80)
    model: Literal["gpt-5.6-terra", "gpt-5.6-sol"]
    stage: Literal["generate", "heal", "qa"] | None = None
    completed_call_count: int = Field(ge=0, le=CALL_CAP)
    partial_live_calls: list[LiveCallEvidence] = Field(max_length=3)


class RoutingRawEvidence(ClosedEvidence):
    schema_version: Literal["1.0"]
    acceptance_row: Literal["ROUTE-02"]
    sanitized: Literal[True]
    call_cap: Literal[12]
    status: Literal["reserved", "running", "cohort_complete", "complete", "aborted"]
    active_model: Literal["gpt-5.6-terra", "gpt-5.6-sol"]
    evaluation_provenance: EvaluationProvenance
    cases: list[RoutingCaseEvidence] = Field(max_length=len(FIXTURE_IDS) * 2)
    usage_observations: list[UsageObservationEvidence] = Field(max_length=2)
    inflight: InflightEvidence | None

    @model_validator(mode="after")
    def validate_case_fixture_binding(self) -> RoutingRawEvidence:
        expected = {
            item.fixture_id: item.payload_sha256
            for item in self.evaluation_provenance.fixture_prompt_fingerprints
        }
        if any(
            case.fixture_id not in expected
            or case.spec_sha256 != expected[case.fixture_id]
            for case in self.cases
        ):
            raise ValueError("case spec hash is not bound to its fixture payload")
        return self


class RouteEvaluationSetItem(ClosedEvidence):
    fixture_id: str = Field(min_length=1, max_length=80)
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RouteModelMetrics(ClosedEvidence):
    case_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    live_call_count: int = Field(ge=0, le=CALL_CAP)
    heal_count: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class RouteGates(ClosedEvidence):
    complete_matrix: bool
    terra_quality: bool
    sol_baseline_quality: bool
    terra_calls_no_worse: bool
    terra_latency_within_tolerance: bool
    account_usage_observed: bool
    terra_usage_no_worse: bool
    runtime_config_matches_decision: bool


class RouteTierDecision(ClosedEvidence):
    tier: Literal["bounded_single_parameter_v1"]
    generation_model: Literal["gpt-5.6-terra", "gpt-5.6-sol"]
    adopted: bool
    decision_applied: bool
    reason: Literal[
        "terra_met_quality_calls_latency_and_observed_usage_gates",
        "direct_sol_retained_because_terra_evidence_gate_failed",
        "direct_sol_retained_because_evaluation_incomplete",
    ]


class RoutingDecisionReport(ClosedEvidence):
    schema_version: Literal["1.0"]
    acceptance_row: Literal["ROUTE-02"]
    passed: bool
    call_cap: Literal[12]
    case_timeout_seconds: Literal[600]
    latency_tolerance_ratio: Literal[1.1]
    cohort_live_calls: int = Field(ge=0, le=CALL_CAP)
    prior_aborted_live_calls: int = Field(ge=0, le=CALL_CAP)
    total_live_calls: int = Field(ge=0, le=CALL_CAP)
    prior_aborted_evidence: list[PriorAbortedCallEvidence] = Field(max_length=2)
    evaluation_set: list[RouteEvaluationSetItem]
    fresh_sol_generate_after_terra_failure: Literal[False]
    abort_conditions: list[str]
    account_observed_usage: AccountUsageEvidence
    gates: RouteGates
    metrics_by_model: dict[str, RouteModelMetrics]
    failure_codes: dict[str, int]
    tier_decision: RouteTierDecision
    configured_terra_generation_tiers: list[Literal["bounded_single_parameter_v1"]]
    routing_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: list[RoutingCaseEvidence]

    @model_validator(mode="after")
    def validate_report_cross_fields(self) -> RoutingDecisionReport:
        if set(self.metrics_by_model) != set(EVALUATED_MODELS):
            raise ValueError("routing report model metrics are incomplete")
        if tuple(self.abort_conditions) != ABORT_CONDITIONS:
            raise ValueError("routing report abort conditions changed")
        if self.prior_aborted_live_calls != sum(
            item.live_call_count_conservative for item in self.prior_aborted_evidence
        ):
            raise ValueError("prior aborted routing call count changed")
        if self.total_live_calls != (
            self.cohort_live_calls + self.prior_aborted_live_calls
        ):
            raise ValueError("routing report total call count changed")
        if self.cohort_live_calls != sum(
            metric.live_call_count for metric in self.metrics_by_model.values()
        ):
            raise ValueError("routing report cohort call count changed")
        expected_passed = (
            self.gates.complete_matrix
            and self.gates.sol_baseline_quality
            and self.gates.account_usage_observed
            and self.tier_decision.decision_applied
        )
        if self.passed != expected_passed:
            raise ValueError("routing report pass state disagrees with gates")
        return self


class FinalRoutingReport(RoutingDecisionReport):
    cohort_status: Literal["complete"]
    evaluation_provenance: EvaluationProvenance
    raw_evidence_path: str = Field(
        pattern=r"^out/evidence/[a-zA-Z0-9][a-zA-Z0-9._/-]*\.json$"
    )
    raw_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_bound_prior_aborted_attempts(self) -> FinalRoutingReport:
        paths = [item.path for item in self.prior_aborted_evidence]
        if (
            paths != list(PRIOR_ABORTED_EVIDENCE_PATHS)
            or self.prior_aborted_live_calls != 2
        ):
            raise ValueError("prior aborted routing evidence incomplete")
        return self


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return parsed


async def read_account_lifetime_tokens(
    *,
    process_factory: Any = asyncio.create_subprocess_exec,
) -> int:
    """Read one sanitized account-usage counter through the local Codex protocol."""

    codex_path = shutil.which("codex") or "/home/dev/bin/codex"
    process = await process_factory(
        codex_path,
        "app-server",
        "--stdio",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        shell=False,
    )
    if process.stdin is None or process.stdout is None:
        raise RuntimeError("codex_usage_protocol_unavailable")

    async def send(payload: dict[str, Any]) -> None:
        process.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        await process.stdin.drain()

    async def receive(response_id: int) -> dict[str, Any]:
        async with asyncio.timeout(10):
            while line := await process.stdout.readline():
                try:
                    document = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if document.get("id") == response_id:
                    return document
        raise RuntimeError("codex_usage_protocol_no_response")

    try:
        await send(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "laysh-route-eval", "version": "1.0"}
                },
            }
        )
        initialized = await receive(1)
        if initialized.get("error") is not None:
            raise RuntimeError("codex_usage_initialize_failed")
        await send({"method": "initialized"})
        await send({"id": 2, "method": "account/usage/read"})
        response = await receive(2)
        value = response.get("result", {}).get("summary", {}).get("lifetimeTokens")
        if type(value) is not int or value < 0:
            raise RuntimeError("codex_usage_counter_unavailable")
        return value
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.terminate()
            await process.wait()


def account_usage_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Reduce private account snapshots to per-cohort deltas only."""

    observations = raw.get("usage_observations", [])
    if not isinstance(observations, list) or len(observations) != 2:
        return {"observed": False, "source": "incomplete_account_usage_observation"}
    try:
        validated = [UsageObservationEvidence.model_validate(item) for item in observations]
    except (ValidationError, ValueError, TypeError):
        return {"observed": False, "source": "invalid_account_usage_observation"}
    by_model = {item.model: item for item in validated}
    if set(by_model) != set(EVALUATED_MODELS) or len(validated) != len(by_model):
        return {"observed": False, "source": "incomplete_account_usage_observation"}
    if _parse_utc_timestamp(
        by_model["gpt-5.6-sol"].observed_before_at
    ) < _parse_utc_timestamp(by_model["gpt-5.6-terra"].observed_after_at):
        return {"observed": False, "source": "invalid_account_usage_observation"}
    return {
        "observed": True,
        "source": USAGE_SOURCE,
        "terra_delta_units": by_model["gpt-5.6-terra"].delta_units,
        "sol_delta_units": by_model["gpt-5.6-sol"].delta_units,
    }


async def observe_account_usage_delta(
    *,
    before_units: int,
    turn_reported_tokens: int,
    reader: Callable[[], Coroutine[Any, Any, int]] = read_account_lifetime_tokens,
    sleep: Callable[[float], Coroutine[Any, Any, None]] = asyncio.sleep,
    max_samples: int = 6,
) -> dict[str, int]:
    """Wait for a positive stable account delta and cross-check stage usage."""

    if (
        type(before_units) is not int
        or before_units < 0
        or type(turn_reported_tokens) is not int
        or turn_reported_tokens <= 0
        or type(max_samples) is not int
        or not 1 <= max_samples <= 10
    ):
        raise ValueError("account_usage_baseline_invalid")
    previous = before_units
    sample_count = 0
    for _ in range(max_samples):
        current = await reader()
        sample_count += 1
        if type(current) is not int or current < 0:
            raise ValueError("account_usage_counter_invalid")
        if current < before_units or current < previous:
            raise ValueError("account_usage_counter_decreased")
        delta = current - before_units
        if current == previous and delta >= turn_reported_tokens:
            return {"delta_units": delta, "sample_count": sample_count}
        previous = current
        await sleep(1)
    raise ValueError("account_usage_counter_inconclusive")


def _validate_cases(
    cases: list[dict[str, Any]],
    fixture_ids: tuple[str, ...],
) -> tuple[list[dict[str, Any]], int]:
    total_calls = sum(
        len(case.get("live_calls", []))
        for case in cases
        if isinstance(case, dict) and isinstance(case.get("live_calls"), list)
    )
    if total_calls > CALL_CAP:
        raise ValueError("call_cap_exceeded")
    try:
        validated = [RoutingCaseEvidence.model_validate(case) for case in cases]
    except (ValidationError, ValueError, TypeError):
        raise ValueError("case_evidence_invalid") from None
    normalized = [case.model_dump(mode="json") for case in validated]
    expected = {(fixture_id, model) for fixture_id in fixture_ids for model in EVALUATED_MODELS}
    observed = {
        (case.get("fixture_id"), case.get("generation_model"))
        for case in normalized
    }
    if observed != expected or len(normalized) != len(expected):
        raise ValueError("evaluation_matrix_incomplete_or_duplicated")
    for fixture_id in fixture_ids:
        hashes = {
            case.get("spec_sha256")
            for case in normalized
            if case.get("fixture_id") == fixture_id
        }
        if len(hashes) != 1:
            raise ValueError("fixed_spec_changed_between_models")
    return normalized, total_calls


def _fixed_spec_hash(understanding: dict[str, Any]) -> str:
    serialized = json.dumps(
        understanding,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _git_capture(git_path: str, *args: str) -> bytes:
    return subprocess.run(  # noqa: S603 - resolved git path and fixed arguments
        [git_path, *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _worktree_fingerprint(git_path: str) -> tuple[str, bool]:
    """Fingerprint measured sources, excluding evidence and its data-only decision."""

    excluded_evidence = ":(exclude)out/evidence/**"
    excluded_decision = ":(exclude)server/routing_decision.json"
    tracked_diff = _git_capture(
        git_path,
        "diff",
        "--binary",
        "--no-ext-diff",
        "HEAD",
        "--",
        ".",
        excluded_evidence,
        excluded_decision,
    )
    untracked_output = _git_capture(
        git_path,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        ".",
        excluded_evidence,
        excluded_decision,
    )
    untracked = sorted(path for path in untracked_output.split(b"\0") if path)
    digest = hashlib.sha256()
    digest.update(tracked_diff)
    for encoded_path in untracked:
        relative = encoded_path.decode("utf-8")
        path = (ROOT / relative).resolve()
        if ROOT not in path.parents:
            raise ValueError("untracked_path_escaped_repository")
        digest.update(b"\0untracked\0")
        digest.update(encoded_path)
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest(), bool(tracked_diff or untracked)


def _provenance_content_fields(
    read_blob: Callable[[str], bytes],
) -> dict[str, Any]:
    """Derive every stable provenance field from one immutable byte reader."""

    from server.goldens import _artifact_lesson_and_module
    from server.schemas import validate_understanding

    fixture_fingerprints: list[dict[str, str]] = []
    try:
        for fixture_id in FIXTURE_IDS:
            relative = FIXTURE_GOLDEN_PATHS[fixture_id]
            document = json.loads(read_blob(relative))
            if not isinstance(document, dict) or not isinstance(
                document.get("artifact"), str
            ):
                raise ValueError("routing_fixture_unavailable")
            understanding, _ = _artifact_lesson_and_module(document["artifact"])
            fixture_fingerprints.append(
                {
                    "fixture_id": fixture_id,
                    "payload_sha256": _fixed_spec_hash(
                        validate_understanding(understanding)
                    ),
                }
            )
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("routing_fixture_unavailable") from None

    snapshot = hashlib.sha256()
    for relative in SOURCE_SNAPSHOT_PATHS:
        try:
            payload = read_blob(relative)
        except (OSError, ValueError):
            raise ValueError("evaluation_provenance_source_unavailable") from None
        snapshot.update(relative.encode("utf-8"))
        snapshot.update(b"\0")
        snapshot.update(payload)
        snapshot.update(b"\0")
    for item in fixture_fingerprints:
        snapshot.update(item["fixture_id"].encode("utf-8"))
        snapshot.update(item["payload_sha256"].encode("ascii"))
    try:
        direct_hashes = {
            name: hashlib.sha256(read_blob(relative)).hexdigest()
            for name, relative in DIRECT_PROVENANCE_PATHS.items()
        }
    except (OSError, ValueError):
        raise ValueError("evaluation_provenance_source_unavailable") from None
    return {
        "source_snapshot_sha256": snapshot.hexdigest(),
        **direct_hashes,
        "fixture_prompt_fingerprints": fixture_fingerprints,
    }


def _git_blob_reader(
    git_path: str,
    repository_root: Path,
    commit: str,
) -> Callable[[str], bytes]:
    def read_blob(relative: str) -> bytes:
        process = subprocess.run(  # noqa: S603 - resolved git and fixed paths
            [git_path, "show", f"{commit}:{relative}"],
            cwd=repository_root,
            check=False,
            capture_output=True,
        )
        if process.returncode != 0:
            raise ValueError("evaluation_provenance_source_unavailable")
        return process.stdout

    return read_blob


def _evaluation_provenance_at_commit(
    commit: str,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Rebuild stable provenance from one explicit tracked Git commit."""

    if (
        len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise ValueError("evaluation_provenance_commit_invalid")
    git_path = shutil.which("git")
    if git_path is None:
        raise ValueError("git_unavailable_for_evaluation_provenance")

    def git(*arguments: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 - resolved git and closed arguments
            [git_path, *arguments],
            cwd=repository_root,
            check=False,
            capture_output=True,
        )

    resolved = git("rev-parse", "--verify", f"{commit}^{{commit}}")
    if resolved.returncode != 0 or resolved.stdout.decode().strip() != commit:
        raise ValueError("evaluation_provenance_commit_invalid")
    tree = git("rev-parse", f"{commit}^{{tree}}")
    if tree.returncode != 0:
        raise ValueError("evaluation_provenance_commit_invalid")
    try:
        content_fields = _provenance_content_fields(
            _git_blob_reader(git_path, repository_root, commit)
        )
        return EvaluationProvenance.model_validate(
            {
                "head_commit": commit,
                "head_tree_sha256": hashlib.sha256(tree.stdout.strip()).hexdigest(),
                "worktree_state_sha256": hashlib.sha256(b"").hexdigest(),
                "worktree_dirty": False,
                **content_fields,
            }
        ).model_dump(mode="json")
    except (ValidationError, ValueError, TypeError):
        raise ValueError("evaluation_provenance_commit_invalid") from None


def _evaluation_provenance() -> dict[str, Any]:
    """Fingerprint the complete payload and runtime sources used by both cohorts."""
    content_fields = _provenance_content_fields(
        lambda relative: (ROOT / relative).read_bytes()
    )
    git_path = shutil.which("git")
    if git_path is None:
        raise ValueError("git_unavailable_for_evaluation_provenance")
    head = _git_capture(git_path, "rev-parse", "HEAD").decode().strip()
    head_tree = _git_capture(git_path, "rev-parse", "HEAD^{tree}").strip()
    worktree_state_sha256, worktree_dirty = _worktree_fingerprint(git_path)
    document: dict[str, Any] = {
        "head_commit": head,
        "head_tree_sha256": hashlib.sha256(head_tree).hexdigest(),
        "worktree_state_sha256": worktree_state_sha256,
        "worktree_dirty": worktree_dirty,
        **content_fields,
    }
    return EvaluationProvenance.model_validate(document).model_dump(mode="json")


def build_report(
    cases: list[dict[str, Any]],
    *,
    account_usage: dict[str, Any],
    fixture_ids: tuple[str, ...],
    configured_terra_tiers: set[str] | frozenset[str] | None = None,
    routing_decision_digest: str | None = None,
    prior_aborted_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a closed, sanitized routing decision from a bounded live matrix."""

    normalized_cases, cohort_live_calls = _validate_cases(cases, fixture_ids)
    try:
        normalized_prior_aborted = [
            PriorAbortedCallEvidence.model_validate(item).model_dump(mode="json")
            for item in (prior_aborted_evidence or [])
        ]
    except (ValidationError, ValueError, TypeError):
        raise ValueError("prior_aborted_evidence_invalid") from None
    if normalized_prior_aborted and [
        item["path"] for item in normalized_prior_aborted
    ] != list(PRIOR_ABORTED_EVIDENCE_PATHS):
        raise ValueError("prior_aborted_evidence_invalid")
    prior_aborted_live_calls = sum(
        item["live_call_count_conservative"] for item in normalized_prior_aborted
    )
    total_live_calls = cohort_live_calls + prior_aborted_live_calls
    if total_live_calls > CALL_CAP:
        raise ValueError("call_cap_exceeded")
    try:
        usage_evidence = AccountUsageEvidence.model_validate(account_usage)
    except (ValidationError, ValueError, TypeError):
        raise ValueError("account_usage_evidence_invalid") from None
    sanitized_usage = usage_evidence.model_dump(mode="json", exclude_none=True)
    by_model: dict[str, dict[str, Any]] = {}
    for model in EVALUATED_MODELS:
        selected = [
            case for case in normalized_cases if case["generation_model"] == model
        ]
        by_model[model] = {
            "case_count": len(selected),
            "passed_count": sum(bool(case.get("passed")) for case in selected),
            "live_call_count": sum(len(case["live_calls"]) for case in selected),
            "heal_count": sum(int(case.get("heal_count", 0)) for case in selected),
            "elapsed_ms": sum(int(case.get("elapsed_ms", 0)) for case in selected),
            "input_tokens": sum(
                int(call.get("input_tokens", 0))
                for case in selected
                for call in case["live_calls"]
            ),
            "cached_input_tokens": sum(
                int(call.get("cached_input_tokens", 0))
                for case in selected
                for call in case["live_calls"]
            ),
            "output_tokens": sum(
                int(call.get("output_tokens", 0))
                for case in selected
                for call in case["live_calls"]
            ),
        }

    terra = by_model["gpt-5.6-terra"]
    sol = by_model["gpt-5.6-sol"]
    usage_observed = sanitized_usage.get("observed") is True
    usage_comparable = (
        usage_observed
        and isinstance(sanitized_usage.get("terra_delta_units"), int)
        and isinstance(sanitized_usage.get("sol_delta_units"), int)
    )
    gates = {
        "complete_matrix": all(
            item["case_count"] == len(fixture_ids) for item in by_model.values()
        ),
        "terra_quality": terra["passed_count"] == len(fixture_ids),
        "sol_baseline_quality": sol["passed_count"] == len(fixture_ids),
        "terra_calls_no_worse": terra["live_call_count"] <= sol["live_call_count"],
        "terra_latency_within_tolerance": terra["elapsed_ms"]
        <= sol["elapsed_ms"] * LATENCY_TOLERANCE_RATIO,
        "account_usage_observed": usage_observed,
        "terra_usage_no_worse": usage_comparable
        and sanitized_usage["terra_delta_units"] <= sanitized_usage["sol_delta_units"],
    }
    terra_adopted = all(gates.values())
    evaluation_complete = (
        gates["complete_matrix"]
        and gates["sol_baseline_quality"]
        and gates["account_usage_observed"]
        and usage_comparable
    )
    expected_tiers = {EVALUATED_TIER} if terra_adopted else set()
    configured_tiers = set(configured_terra_tiers or ())
    decision_applied = evaluation_complete and configured_tiers == expected_tiers
    gates["runtime_config_matches_decision"] = decision_applied
    decision = {
        "tier": EVALUATED_TIER,
        "generation_model": "gpt-5.6-terra" if terra_adopted else "gpt-5.6-sol",
        "adopted": terra_adopted,
        "decision_applied": decision_applied,
        "reason": (
            "terra_met_quality_calls_latency_and_observed_usage_gates"
            if terra_adopted
            else (
                "direct_sol_retained_because_terra_evidence_gate_failed"
                if evaluation_complete
                else "direct_sol_retained_because_evaluation_incomplete"
            )
        ),
    }
    failure_codes = Counter(
        case.get("failure_code")
        for case in normalized_cases
        if case.get("failure_code") is not None
    )
    if routing_decision_digest is None:
        from server.model_routing import routing_decision_sha256

        routing_decision_digest = routing_decision_sha256()
    document = {
        "schema_version": "1.0",
        "acceptance_row": "ROUTE-02",
        "passed": evaluation_complete and decision_applied,
        "call_cap": CALL_CAP,
        "case_timeout_seconds": CASE_TIMEOUT_SECONDS,
        "latency_tolerance_ratio": LATENCY_TOLERANCE_RATIO,
        "cohort_live_calls": cohort_live_calls,
        "prior_aborted_live_calls": prior_aborted_live_calls,
        "total_live_calls": total_live_calls,
        "prior_aborted_evidence": normalized_prior_aborted,
        "evaluation_set": [
            {
                "fixture_id": fixture_id,
                "spec_sha256": next(
                    case["spec_sha256"]
                    for case in normalized_cases
                    if case["fixture_id"] == fixture_id
                ),
            }
            for fixture_id in fixture_ids
        ],
        "fresh_sol_generate_after_terra_failure": False,
        "abort_conditions": list(ABORT_CONDITIONS),
        "account_observed_usage": sanitized_usage,
        "gates": gates,
        "metrics_by_model": by_model,
        "failure_codes": dict(sorted(failure_codes.items())),
        "tier_decision": decision,
        "configured_terra_generation_tiers": sorted(configured_tiers),
        "routing_decision_sha256": routing_decision_digest,
        "cases": normalized_cases,
    }
    try:
        return RoutingDecisionReport.model_validate(document).model_dump(mode="json")
    except (ValidationError, ValueError, TypeError):
        raise ValueError("routing_report_invalid") from None


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_tracked_raw_evidence(
    relative_path: str,
    *,
    repository_root: Path,
) -> tuple[dict[str, Any], str]:
    root = repository_root.resolve()
    candidate = Path(relative_path)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.parts[:2] != ("out", "evidence")
        or candidate.suffix != ".json"
    ):
        raise ValueError("routing_raw_evidence_path_invalid")
    path = root / candidate
    if path.is_symlink() or not path.is_file():
        raise ValueError("routing_raw_evidence_path_invalid")
    resolved = path.resolve()
    if root not in resolved.parents:
        raise ValueError("routing_raw_evidence_path_invalid")
    git_path = shutil.which("git")
    if git_path is None:
        raise ValueError("git_unavailable_for_routing_evidence")
    tracked = subprocess.run(  # noqa: S603 - resolved git and closed relative path
        [git_path, "ls-files", "--error-unmatch", "--", candidate.as_posix()],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if tracked.returncode != 0:
        raise ValueError("routing_raw_evidence_untracked")
    payload = resolved.read_bytes()
    try:
        document = json.loads(payload)
    except json.JSONDecodeError:
        raise ValueError("routing_raw_evidence_invalid") from None
    return document, hashlib.sha256(payload).hexdigest()


def _load_prior_aborted_evidence(repository_root: Path) -> list[dict[str, Any]]:
    """Bind the two known conservative attempts into every live/final budget."""

    root = repository_root.resolve()
    git_path = shutil.which("git")
    if git_path is None:
        raise ValueError("git_unavailable_for_routing_evidence")
    records: list[dict[str, Any]] = []
    expected = {
        PRIOR_ABORTED_EVIDENCE_PATHS[0]: {
            "outcome": "aborted_by_test_guard_red",
            "model": "gpt-5.6-sol",
            "remaining_processes_after_root_check": None,
        },
        PRIOR_ABORTED_EVIDENCE_PATHS[1]: {
            "outcome": "aborted_by_confirmation_guard_red",
            "model": "gpt-5.6-terra",
            "remaining_processes_after_root_check": 0,
        },
    }
    common_keys = {
        "schema_version",
        "acceptance_row",
        "sanitized",
        "recorded_at",
        "passed",
        "outcome",
        "stage",
        "model",
        "effort",
        "elapsed_ms_approximate",
        "structured_output",
        "token_usage",
        "live_call_count_conservative",
        "reason",
    }
    for relative in PRIOR_ABORTED_EVIDENCE_PATHS:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("prior_aborted_evidence_invalid")
        tracked = subprocess.run(  # noqa: S603 - resolved git and fixed path
            [git_path, "ls-files", "--error-unmatch", "--", relative],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if tracked.returncode != 0:
            raise ValueError("prior_aborted_evidence_untracked")
        payload = path.read_bytes()
        indexed = subprocess.run(  # noqa: S603 - resolved git and fixed path
            [git_path, "show", f":{relative}"],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if indexed.returncode != 0 or indexed.stdout != payload:
            raise ValueError("prior_aborted_evidence_changed")
        try:
            document = json.loads(payload)
        except json.JSONDecodeError:
            raise ValueError("prior_aborted_evidence_invalid") from None
        specification = expected[relative]
        keys = common_keys | (
            {"remaining_processes_after_root_check"}
            if specification["remaining_processes_after_root_check"] is not None
            else set()
        )
        try:
            _parse_utc_timestamp(document["recorded_at"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("prior_aborted_evidence_invalid") from None
        if (
            not isinstance(document, dict)
            or set(document) != keys
            or document.get("schema_version") != "1.0"
            or document.get("acceptance_row") != "ROUTE-02"
            or document.get("sanitized") is not True
            or document.get("passed") is not False
            or document.get("outcome") != specification["outcome"]
            or document.get("stage") != "generate"
            or document.get("model") != specification["model"]
            or document.get("effort") != "medium"
            or type(document.get("elapsed_ms_approximate")) is not int
            or document["elapsed_ms_approximate"] <= 0
            or document.get("structured_output") is not False
            or document.get("token_usage") is not None
            or document.get("live_call_count_conservative") != 1
            or not isinstance(document.get("reason"), str)
            or not document["reason"]
            or document.get("remaining_processes_after_root_check")
            != specification["remaining_processes_after_root_check"]
        ):
            raise ValueError("prior_aborted_evidence_invalid")
        records.append(
            PriorAbortedCallEvidence.model_validate(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "model": document["model"],
                    "elapsed_ms_approximate": document["elapsed_ms_approximate"],
                    "live_call_count_conservative": 1,
                }
            ).model_dump(mode="json")
        )
    return records


def _require_measured_provenance_compatible_with_current(
    measured: dict[str, Any],
    current: dict[str, Any],
    *,
    repository_root: Path,
    allow_descendant_head: bool,
) -> None:
    stable_fields = (
        "source_snapshot_sha256",
        "evaluator_sha256",
        "runtime_sha256",
        "generate_prompt_sha256",
        "heal_prompt_sha256",
        "qa_prompt_sha256",
        "module_verifier_sha256",
        "server_verifier_sha256",
        "fixture_prompt_fingerprints",
    )
    if any(measured[field] != current[field] for field in stable_fields):
        raise ValueError("evaluation_provenance_changed")
    if not allow_descendant_head:
        if measured != current:
            raise ValueError("evaluation_provenance_changed")
        return

    git_path = shutil.which("git")
    if git_path is None:
        raise ValueError("git_unavailable_for_evaluation_provenance")

    def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 - resolved git and closed arguments
            [git_path, *arguments],
            cwd=repository_root,
            check=check,
            capture_output=True,
        )

    actual_head = git("rev-parse", "HEAD").stdout.decode().strip()
    anchor_head = current["head_commit"]
    current_tree_process = git(
        "rev-parse", f"{anchor_head}^{{tree}}", check=False
    )
    if current_tree_process.returncode != 0:
        raise ValueError("evaluation_provenance_changed")
    current_tree = current_tree_process.stdout.strip()
    if current["head_tree_sha256"] != hashlib.sha256(current_tree).hexdigest():
        raise ValueError("evaluation_provenance_changed")
    measured_tree_process = git(
        "rev-parse", f"{measured['head_commit']}^{{tree}}", check=False
    )
    if measured_tree_process.returncode != 0 or measured[
        "head_tree_sha256"
    ] != hashlib.sha256(measured_tree_process.stdout.strip()).hexdigest():
        raise ValueError("evaluation_provenance_changed")
    ancestor = git(
        "merge-base",
        "--is-ancestor",
        measured["head_commit"],
        anchor_head,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError("evaluation_provenance_changed")

    changed_output = git(
        "diff",
        "--name-only",
        "--no-renames",
        "-z",
        measured["head_commit"],
        anchor_head,
        "--",
    ).stdout
    changed_paths = {
        item.decode("utf-8") for item in changed_output.split(b"\0") if item
    }
    if not changed_paths <= EVIDENCE_ONLY_DESCENDANT_PATHS:
        raise ValueError("evaluation_provenance_changed")

    head_descends_from_anchor = git(
        "merge-base",
        "--is-ancestor",
        anchor_head,
        actual_head,
        check=False,
    )
    if head_descends_from_anchor.returncode != 0:
        raise ValueError("evaluation_provenance_changed")
    after_anchor_output = git(
        "diff",
        "--name-only",
        "--no-renames",
        "-z",
        anchor_head,
        actual_head,
        "--",
    ).stdout
    after_anchor_paths = {
        item.decode("utf-8")
        for item in after_anchor_output.split(b"\0")
        if item
    }
    if any(
        not (
            path.startswith("out/evidence/")
            or path == "docs/build-spec/g7-continuation/BUILD-NOTEBOOK.md"
            or path == "server/routing_decision.json"
        )
        for path in after_anchor_paths
    ):
        raise ValueError("evaluation_provenance_changed")

    try:
        historical_fields = _provenance_content_fields(
            _git_blob_reader(
                git_path,
                repository_root,
                measured["head_commit"],
            )
        )
    except ValueError:
        raise ValueError("evaluation_provenance_changed") from None
    if any(
        measured.get(field) != value
        for field, value in historical_fields.items()
    ):
        raise ValueError("evaluation_provenance_changed")
    try:
        anchor_fields = _provenance_content_fields(
            _git_blob_reader(git_path, repository_root, anchor_head)
        )
    except ValueError:
        raise ValueError("evaluation_provenance_changed") from None
    if any(current.get(field) != value for field, value in anchor_fields.items()):
        raise ValueError("evaluation_provenance_changed")
    if (
        measured.get("worktree_dirty") is not False
        or measured.get("worktree_state_sha256")
        != hashlib.sha256(b"").hexdigest()
        or current.get("worktree_dirty") is not False
        or current.get("worktree_state_sha256")
        != hashlib.sha256(b"").hexdigest()
    ):
        raise ValueError("evaluation_provenance_changed")


def build_report_from_raw(
    raw: dict[str, Any],
    *,
    configured_terra_tiers: set[str] | frozenset[str] | None = None,
    current_provenance: dict[str, Any] | None = None,
    routing_decision_path: Path | None = None,
    raw_evidence_path: Path | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Finalize only a complete, closed, app-server-observed two-model cohort."""

    try:
        validated = RoutingRawEvidence.model_validate(raw)
    except (ValidationError, ValueError, TypeError):
        raise ValueError("raw_evidence_invalid") from None
    if (
        validated.status != "complete"
        or validated.active_model != "gpt-5.6-sol"
        or validated.inflight is not None
    ):
        raise ValueError("raw_evidence_incomplete")
    normalized_raw = validated.model_dump(mode="json")
    try:
        current = EvaluationProvenance.model_validate(
            current_provenance if current_provenance is not None else _evaluation_provenance()
        ).model_dump(mode="json")
    except (ValidationError, ValueError, TypeError):
        raise ValueError("current_evaluation_provenance_invalid") from None
    if normalized_raw["evaluation_provenance"] != current:
        raise ValueError("evaluation_provenance_changed")
    if raw_evidence_path is None:
        raise ValueError("routing_raw_evidence_path_required")
    selected_root = (repository_root or ROOT).resolve()
    try:
        relative_raw_path = raw_evidence_path.resolve().relative_to(selected_root)
    except (OSError, ValueError):
        raise ValueError("routing_raw_evidence_path_invalid") from None
    loaded_raw, raw_digest = _load_tracked_raw_evidence(
        relative_raw_path.as_posix(),
        repository_root=selected_root,
    )
    try:
        normalized_loaded_raw = RoutingRawEvidence.model_validate(loaded_raw).model_dump(
            mode="json"
        )
    except (ValidationError, ValueError, TypeError):
        raise ValueError("routing_raw_evidence_invalid") from None
    if normalized_loaded_raw != normalized_raw:
        raise ValueError("routing_raw_evidence_mismatch")
    from server.model_routing import load_routing_decision, routing_decision_sha256

    decision_tiers = set(load_routing_decision(routing_decision_path))
    if configured_terra_tiers is None:
        configured_terra_tiers = (
            decision_tiers
            if routing_decision_path is not None
            else repository_configured_terra_tiers()
        )
    elif set(configured_terra_tiers) != decision_tiers:
        raise ValueError("runtime_route_config_mismatch")
    report = build_report(
        normalized_raw["cases"],
        account_usage=account_usage_from_raw(normalized_raw),
        fixture_ids=FIXTURE_IDS,
        configured_terra_tiers=configured_terra_tiers,
        routing_decision_digest=routing_decision_sha256(routing_decision_path),
        prior_aborted_evidence=_load_prior_aborted_evidence(selected_root),
    )
    report["cohort_status"] = "complete"
    report["evaluation_provenance"] = normalized_raw["evaluation_provenance"]
    report["raw_evidence_path"] = relative_raw_path.as_posix()
    report["raw_evidence_sha256"] = raw_digest
    return validate_routing_report(
        report,
        routing_decision_path=routing_decision_path,
        current_provenance=current,
        repository_root=selected_root,
        require_current_provenance=True,
    )


def validate_routing_report(
    report: dict[str, Any],
    *,
    routing_decision_path: Path | None = None,
    current_provenance: dict[str, Any] | None = None,
    current_commit: str | None = None,
    repository_root: Path | None = None,
    require_current_provenance: bool = True,
) -> dict[str, Any]:
    """Rebuild and reject open, stale, or contradictory final route evidence."""

    try:
        validated = FinalRoutingReport.model_validate(report).model_dump(mode="json")
    except (ValidationError, ValueError, TypeError):
        raise ValueError("routing_report_invalid") from None
    selected_root = (repository_root or ROOT).resolve()
    raw_document, raw_digest = _load_tracked_raw_evidence(
        validated["raw_evidence_path"],
        repository_root=selected_root,
    )
    if validated["raw_evidence_sha256"] != raw_digest:
        raise ValueError("routing_raw_evidence_changed")
    try:
        validated_raw = RoutingRawEvidence.model_validate(raw_document)
    except (ValidationError, ValueError, TypeError):
        raise ValueError("routing_raw_evidence_invalid") from None
    if (
        validated_raw.status != "complete"
        or validated_raw.active_model != "gpt-5.6-sol"
        or validated_raw.inflight is not None
    ):
        raise ValueError("routing_raw_evidence_incomplete")
    normalized_raw = validated_raw.model_dump(mode="json")

    from server.model_routing import load_routing_decision, routing_decision_sha256

    decision_digest = routing_decision_sha256(routing_decision_path)
    if validated["routing_decision_sha256"] != decision_digest:
        raise ValueError("routing_decision_changed")
    if current_provenance is not None and current_commit is not None:
        raise ValueError("current_evaluation_provenance_ambiguous")
    supplied_current_provenance = current_provenance is not None
    git_derived_current = current_commit is not None
    if current_commit is not None:
        current_provenance = _evaluation_provenance_at_commit(
            current_commit,
            repository_root=selected_root,
        )
    elif require_current_provenance and current_provenance is None:
        current_provenance = _evaluation_provenance()
        git_derived_current = True
    if current_provenance is not None:
        try:
            normalized_current = EvaluationProvenance.model_validate(
                current_provenance
            ).model_dump(mode="json")
        except (ValidationError, ValueError, TypeError):
            raise ValueError("current_evaluation_provenance_invalid") from None
        _require_measured_provenance_compatible_with_current(
            normalized_raw["evaluation_provenance"],
            normalized_current,
            repository_root=selected_root,
            allow_descendant_head=(
                require_current_provenance
                and (git_derived_current or not supplied_current_provenance)
            ),
        )

    provenance_hashes = {
        item["fixture_id"]: item["payload_sha256"]
        for item in normalized_raw["evaluation_provenance"][
            "fixture_prompt_fingerprints"
        ]
    }
    expected_evaluation_set = [
        {"fixture_id": fixture_id, "spec_sha256": provenance_hashes[fixture_id]}
        for fixture_id in FIXTURE_IDS
    ]
    try:
        canonical = build_report(
            normalized_raw["cases"],
            account_usage=account_usage_from_raw(normalized_raw),
            fixture_ids=FIXTURE_IDS,
            configured_terra_tiers=set(load_routing_decision(routing_decision_path)),
            routing_decision_digest=decision_digest,
            prior_aborted_evidence=_load_prior_aborted_evidence(selected_root),
        )
    except (KeyError, ValidationError, ValueError, TypeError):
        raise ValueError("routing_report_noncanonical") from None
    if canonical["evaluation_set"] != expected_evaluation_set:
        raise ValueError("routing_report_noncanonical")
    canonical_final = {
        **canonical,
        "cohort_status": "complete",
        "evaluation_provenance": normalized_raw["evaluation_provenance"],
        "raw_evidence_path": validated["raw_evidence_path"],
        "raw_evidence_sha256": raw_digest,
    }
    if validated != canonical_final:
        raise ValueError("routing_report_noncanonical")
    return validated


async def _evaluate_case(
    *,
    fixture_id: str,
    model: str,
    executor: Any,
    checkpoint: Callable[[str, dict[str, Any], list[dict[str, Any]]], None],
) -> dict[str, Any]:
    from server.browser_verify import verify_artifact_in_browser
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.codex_runtime import CodexRuntimeError, StageExecution
    from server.goldens import _artifact_lesson_and_module, load_pinned_golden
    from server.schemas import validate_module_output, validate_understanding
    from server.settings import Settings
    from server.verify import VerificationResult, verify_candidate

    golden_id = fixture_id.removesuffix("_ar")
    document = load_pinned_golden(golden_id)
    if document is None:
        raise RuntimeError("routing fixture is not a verified pinned artifact")
    understanding, _ = _artifact_lesson_and_module(document["artifact"])
    understanding = validate_understanding(understanding)
    settings = Settings(
        generate_model=model,
        heal_model=model,
        qa_model="gpt-5.6-sol",
        record_runtime=True,
    )
    backend = CodexBackend(executor=executor, settings=settings)
    context = RuntimeContext(public=False, evidence_fixture_id=fixture_id)
    calls: list[dict[str, Any]] = []
    started = time.monotonic()

    async def stage(
        name: str, operation: Callable[[], Coroutine[Any, Any, StageExecution]]
    ) -> StageExecution:
        effort = {"generate": "medium", "heal": "medium", "qa": "medium"}[name]
        reason = {
            "generate": "fixed_spec_candidate",
            "heal": "one_same_model_repair_after_gate_failure",
            "qa": "post_heal_closed_review",
        }[name]
        stage_started = time.monotonic()
        checkpoint(
            "before_stage",
            {"fixture_id": fixture_id, "model": model, "stage": name},
            calls,
        )
        try:
            result = await operation()
        except CodexRuntimeError as error:
            calls.append(
                {
                    "stage": name,
                    "model": error.safe_detail.get("model", model),
                    "effort": effort,
                    "why_model_was_called": reason,
                    "elapsed_ms": int((time.monotonic() - stage_started) * 1000),
                    "outcome": "failed",
                    "thread_id_captured": False,
                    "failure_code": error.code,
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                }
            )
            checkpoint(
                "after_stage",
                {"fixture_id": fixture_id, "model": model, "stage": name},
                calls,
            )
            raise
        calls.append(
            {
                "stage": name,
                "model": result.model,
                "effort": effort,
                "why_model_was_called": reason,
                "elapsed_ms": result.elapsed_ms,
                "outcome": "completed",
                "thread_id_captured": bool(result.thread_id),
                "failure_code": None,
                "input_tokens": result.input_tokens,
                "cached_input_tokens": result.cached_input_tokens,
                "output_tokens": result.output_tokens,
            }
        )
        checkpoint(
            "after_stage",
            {"fixture_id": fixture_id, "model": model, "stage": name},
            calls,
        )
        return result

    def with_browser(result: VerificationResult) -> VerificationResult:
        if not result.passed or result.artifact is None:
            return result
        browser = verify_artifact_in_browser(result.artifact)
        if browser.passed:
            return VerificationResult(
                passed=True,
                check_count=result.check_count + browser.check_count,
                failures=[],
                artifact=result.artifact,
                node_report=result.node_report,
            )
        return VerificationResult(
            passed=False,
            check_count=result.check_count + browser.check_count,
            failures=browser.failures,
            artifact=None,
            node_report=result.node_report,
        )

    heal_count = 0
    failure_code: str | None = None
    try:
        generated = await stage(
            "generate",
            lambda: backend.generate(understanding, runtime_context=context),
        )
        module_output = validate_module_output(generated.data)
        verification = with_browser(verify_candidate(module_output, understanding))
        if not verification.passed:
            heal_count = 1
            healed = await stage(
                "heal",
                lambda: backend.heal(
                    module_output,
                    understanding,
                    verification.failures,
                    1,
                    runtime_context=context,
                ),
            )
            module_output = validate_module_output(healed.data)
            verification = with_browser(verify_candidate(module_output, understanding))
        qa_approved = True
        if heal_count and verification.passed:
            reviewed = await stage(
                "qa",
                lambda: backend.qa(
                    module_output,
                    understanding,
                    {
                        "passed": True,
                        "check_count": verification.check_count,
                        "gate_names": [
                            "assembly",
                            "browser_readiness",
                            "interface",
                            "invariant",
                            "security",
                        ],
                    },
                    runtime_context=context,
                ),
            )
            qa_approved = reviewed.data.get("approved") is True
        passed = verification.passed and qa_approved
        if not passed:
            failure_code = (
                "qa_rejected" if verification.passed else "deterministic_verification_failed"
            )
    except (CodexRuntimeError, ValueError) as error:
        passed = False
        failure_code = (
            error.code
            if isinstance(error, CodexRuntimeError)
            else "contract_validation_failed"
        )
    return {
        "fixture_id": fixture_id,
        "spec_sha256": _fixed_spec_hash(understanding),
        "generation_model": model,
        "passed": passed,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "live_calls": calls,
        "heal_count": heal_count,
        "failure_code": failure_code,
    }


@contextmanager
def _exclusive_evaluation_lock(lock_path: Path):
    """Hold one advisory lock for the complete spend/checkpoint transaction."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("routing_evaluation_locked") from None
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


async def run_live_cohort(
    *,
    model: str,
    raw_path: Path,
    append: bool,
    confirmed: bool = False,
    dependencies: LiveEvaluationDependencies | None = None,
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("live_evaluation_confirmation_required")
    if dependencies is None:
        raise ValueError("live_evaluation_dependencies_required")
    if model not in EVALUATED_MODELS:
        raise ValueError("live evaluation model must be Terra or Sol")
    with _exclusive_evaluation_lock(LIVE_LOCK_PATH):
        return await _run_live_cohort_locked(
            model=model,
            raw_path=raw_path,
            append=append,
            confirmed=confirmed,
            dependencies=dependencies,
        )


async def _run_live_cohort_locked(
    *,
    model: str,
    raw_path: Path,
    append: bool,
    confirmed: bool = False,
    dependencies: LiveEvaluationDependencies | None = None,
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("live_evaluation_confirmation_required")
    if dependencies is None:
        raise ValueError("live_evaluation_dependencies_required")
    if model not in EVALUATED_MODELS:
        raise ValueError("live evaluation model must be Terra or Sol")
    append_raw: RoutingRawEvidence | None = None
    if not append:
        if model != "gpt-5.6-terra":
            raise ValueError("terra_must_run_first")
        if raw_path.exists():
            raise ValueError("routing_raw_evidence_already_exists")
    else:
        if model != "gpt-5.6-sol" or not raw_path.exists():
            raise ValueError("append_requires_complete_terra_cohort")
        try:
            append_raw = RoutingRawEvidence.model_validate_json(
                raw_path.read_text(encoding="utf-8")
            )
        except (ValidationError, ValueError, OSError):
            raise ValueError("append_requires_complete_terra_cohort") from None
        if (
            append_raw.status != "cohort_complete"
            or append_raw.active_model != "gpt-5.6-terra"
            or append_raw.inflight is not None
        ):
            raise ValueError("append_requires_complete_terra_cohort")
    prior_aborted = _load_prior_aborted_evidence(ROOT)
    prior_aborted_call_count = sum(
        item["live_call_count_conservative"] for item in prior_aborted
    )
    if prior_aborted_call_count != 2:
        raise ValueError("prior_aborted_evidence_invalid")
    existing: list[dict[str, Any]] = []
    usage_observations: list[dict[str, Any]] = []
    current_provenance = _evaluation_provenance()
    if (
        current_provenance.get("worktree_dirty") is not False
        or current_provenance.get("worktree_state_sha256")
        != hashlib.sha256(b"").hexdigest()
    ):
        raise ValueError("evaluation_worktree_dirty")
    if append:
        assert append_raw is not None
        raw = append_raw
        if raw.evaluation_provenance.model_dump(mode="json") != current_provenance:
            raise ValueError("evaluation_provenance_changed")
        existing = [case.model_dump(mode="json") for case in raw.cases]
        usage_observations = [
            item.model_dump(mode="json") for item in raw.usage_observations
        ]
        terra_cases = [
            case
            for case in existing
            if case.get("generation_model") == "gpt-5.6-terra"
        ]
        terra_usage = [
            item
            for item in usage_observations
            if item.get("model") == "gpt-5.6-terra"
        ]
        if (
            len(terra_cases) != len(FIXTURE_IDS)
            or {case.get("fixture_id") for case in terra_cases} != set(FIXTURE_IDS)
            or len(terra_usage) != 1
        ):
            raise ValueError("append_requires_complete_terra_cohort")
    prior_calls = sum(len(case.get("live_calls", [])) for case in existing)
    if (
        prior_aborted_call_count + prior_calls + len(FIXTURE_IDS) * 3
        > CALL_CAP
    ):
        raise ValueError("projected_live_calls_exceed_12")
    if any(case.get("generation_model") == model for case in existing):
        raise ValueError("model cohort already exists in raw evidence")

    document: dict[str, Any] = {
        "schema_version": "1.0",
        "acceptance_row": "ROUTE-02",
        "sanitized": True,
        "call_cap": CALL_CAP,
        "status": "reserved",
        "active_model": model,
        "evaluation_provenance": current_provenance,
        "cases": existing,
        "usage_observations": usage_observations,
        "inflight": None,
    }
    _atomic_json(raw_path, document)

    executor = dependencies.executor_factory()
    document["status"] = "running"
    document["inflight"] = {
        "event": "account_usage_before",
        "fixture_id": None,
        "model": model,
        "stage": None,
        "completed_call_count": prior_calls,
        "partial_live_calls": [],
    }
    _atomic_json(raw_path, document)
    observed_before_at = _utc_now()
    try:
        usage_before = await dependencies.usage_reader()
    except Exception:
        document["status"] = "aborted"
        _atomic_json(raw_path, document)
        raise
    cases = [*existing]

    def checkpoint(
        event: str,
        details: dict[str, Any],
        partial_live_calls: list[dict[str, Any]],
    ) -> None:
        completed_call_count = sum(
            len(case.get("live_calls", [])) for case in cases
        ) + len(partial_live_calls)
        total_completed_call_count = prior_aborted_call_count + completed_call_count
        if total_completed_call_count > CALL_CAP or (
            event == "before_stage" and total_completed_call_count >= CALL_CAP
        ):
            raise ValueError("live_call_budget_exhausted")
        document["status"] = "running"
        document["cases"] = cases
        document["inflight"] = {
            "event": event,
            "fixture_id": details.get("fixture_id"),
            "model": model,
            "stage": details.get("stage"),
            "completed_call_count": completed_call_count,
            "partial_live_calls": partial_live_calls,
        }
        _atomic_json(raw_path, document)

    for fixture_id in FIXTURE_IDS:
        checkpoint(
            "before_case",
            {"fixture_id": fixture_id, "model": model, "stage": None},
            [],
        )
        try:
            async with asyncio.timeout(CASE_TIMEOUT_SECONDS):
                case = await dependencies.case_evaluator(
                    fixture_id=fixture_id,
                    model=model,
                    executor=executor,
                    checkpoint=checkpoint,
                )
        except Exception:
            document["status"] = "aborted"
            _atomic_json(raw_path, document)
            raise
        try:
            normalized_case = RoutingCaseEvidence.model_validate(case).model_dump(
                mode="json"
            )
        except (ValidationError, ValueError, TypeError):
            document["status"] = "aborted"
            _atomic_json(raw_path, document)
            raise ValueError("case_evidence_invalid") from None
        cases.append(normalized_case)
        checkpoint(
            "after_case",
            {"fixture_id": fixture_id, "model": model, "stage": None},
            [],
        )
        if normalized_case.get("failure_code") not in {
            None,
            "deterministic_verification_failed",
            "qa_rejected",
        }:
            break
    turn_reported_tokens = sum(
        int(call.get("input_tokens", 0)) + int(call.get("output_tokens", 0))
        for case in cases
        if case.get("generation_model") == model
        for call in case.get("live_calls", [])
    )
    checkpoint(
        "account_usage_after",
        {"fixture_id": None, "model": model, "stage": None},
        [],
    )
    try:
        observed_delta = await observe_account_usage_delta(
            before_units=usage_before,
            turn_reported_tokens=turn_reported_tokens,
            reader=dependencies.usage_reader,
            sleep=dependencies.sleep,
        )
    except Exception:
        document["status"] = "aborted"
        _atomic_json(raw_path, document)
        raise
    usage_observations.append(
        UsageObservationEvidence.model_validate(
            {
                "model": model,
                "source": USAGE_SOURCE,
                **observed_delta,
                "turn_reported_tokens": turn_reported_tokens,
                "observed_before_at": observed_before_at,
                "observed_after_at": _utc_now(),
            }
        ).model_dump(mode="json")
    )
    cohort_cases = [case for case in cases if case.get("generation_model") == model]
    cohort_complete = (
        len(cohort_cases) == len(FIXTURE_IDS)
        and {case.get("fixture_id") for case in cohort_cases} == set(FIXTURE_IDS)
    )
    document.update(
        {
            "status": (
                "complete" if append and cohort_complete else "cohort_complete"
                if cohort_complete
                else "aborted"
            ),
            "cases": cases,
            "usage_observations": usage_observations,
            "inflight": None,
        }
    )
    if _evaluation_provenance() != current_provenance:
        document["status"] = "aborted"
        _atomic_json(raw_path, document)
        raise ValueError("evaluation_provenance_changed")
    normalized = RoutingRawEvidence.model_validate(document).model_dump(mode="json")
    _atomic_json(raw_path, normalized)
    return normalized


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded GPT-5.6 generation routing evaluation")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--live-model", choices=EVALUATED_MODELS)
    action.add_argument("--finalize", action="store_true")
    parser.add_argument("--raw-path", type=Path, default=RAW_EVIDENCE_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--confirm-live-spend")
    return parser


def _production_live_dependencies() -> LiveEvaluationDependencies:
    from server.codex_runtime import CodexExecutor
    from server.goldens import GOLDEN_FIXTURE_IDS
    from server.settings import Settings

    settings = Settings(record_runtime=True)

    def executor_factory() -> CodexExecutor:
        return CodexExecutor(
            stage_timeout_seconds=settings.evidence_stage_timeout_seconds,
            evidence_stage_timeout_seconds=settings.evidence_stage_timeout_seconds,
            record_runtime=True,
            evidence_allowlist=frozenset(GOLDEN_FIXTURE_IDS),
        )

    return LiveEvaluationDependencies(
        usage_reader=read_account_lifetime_tokens,
        case_evaluator=_evaluate_case,
        executor_factory=executor_factory,
        sleep=asyncio.sleep,
    )


def _assignment(path: Path, prefix: str) -> str:
    matches = [
        line.removeprefix(prefix).strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(prefix)
    ]
    if len(matches) != 1:
        raise ValueError(f"runtime_route_assignment_invalid:{path.name}")
    return matches[0]


def repository_configured_terra_tiers() -> set[str]:
    """Require code defaults, example env, and deployment routing to agree."""

    from server.model_routing import load_routing_decision
    from server.settings import Settings

    env_path = ROOT / ".env.example"
    service_path = ROOT / "deploy" / "laysh.service"
    decision_tiers = set(load_routing_decision())
    env_override = {
        item
        for item in _assignment(env_path, "LAYSH_TERRA_GENERATION_TIERS=").split(",")
        if item
    }
    service_override = {
        item
        for item in _assignment(
            service_path, "Environment=LAYSH_TERRA_GENERATION_TIERS="
        ).split(",")
        if item
    }
    env_tiers = env_override or decision_tiers
    service_tiers = service_override or decision_tiers
    code_tiers = set(Settings().terra_generation_tiers)
    qa_models = {
        Settings().qa_model,
        _assignment(env_path, "LAYSH_QA_MODEL="),
        _assignment(service_path, "Environment=LAYSH_QA_MODEL="),
    }
    if env_tiers != service_tiers or env_tiers != code_tiers:
        raise ValueError("runtime_route_config_mismatch")
    if qa_models != {"gpt-5.6-sol"}:
        raise ValueError("ordinary_qa_route_unmeasured")
    return decision_tiers


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.live_model:
        confirmed = args.confirm_live_spend == LIVE_CONFIRMATION
        dependencies = _production_live_dependencies() if confirmed else None
        raw = asyncio.run(
            run_live_cohort(
                model=args.live_model,
                raw_path=args.raw_path,
                append=args.append,
                confirmed=confirmed,
                dependencies=dependencies,
            )
        )
        print(json.dumps(raw, ensure_ascii=False))
        return 0
    raw = json.loads(args.raw_path.read_text(encoding="utf-8"))
    report = build_report_from_raw(
        raw,
        raw_evidence_path=args.raw_path,
        repository_root=ROOT,
    )
    _atomic_json(args.report_path, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
