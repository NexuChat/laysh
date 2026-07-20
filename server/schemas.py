from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "1.0"
SCHEMA_DIR = Path(__file__).parent / "schemas"


class ContractError(ValueError):
    """A document is valid JSON Schema but violates a cross-field contract."""


@cache
def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def validate_document(document: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    Draft202012Validator(schema).validate(document)
    return document


def validate_understanding(document: dict[str, Any]) -> dict[str, Any]:
    validate_document(document, load_schema("understand.schema.json"))
    if document["simulatable"]:
        if len(document["checks"]) < 2:
            raise ContractError("a simulatable lesson requires at least two independent checks")
        if document["actor"] is None or document["action"] is None:
            raise ContractError("a simulatable lesson requires an actor and action")
        tracking_output = document["actor"]["tracking_output"]
        if (
            tracking_output is not None
            and tracking_output not in document["module_spec"]["outputs"]
        ):
            raise ContractError("actor tracking_output must be a declared module output")
        signature = document["actor"]["tracking_signature"]
        reference_values = (
            signature["reference_color_rgb"],
            signature["reference_tolerance"],
        )
        if (reference_values[0] is None) != (reference_values[1] is None):
            raise ContractError("actor reference signature fields must both be null or present")
    elif document["actor"] is not None or document["action"] is not None:
        raise ContractError("a non-simulatable answer cannot claim an actor or action")
    return document


def action_contract_report(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Reject taxonomy matches that the deterministic actor adapters cannot measure honestly."""
    if not document.get("simulatable"):
        return []
    action = document.get("action")
    actor = document.get("actor") or {}
    tracking_output = actor.get("tracking_output")
    parameter = document.get("primary_parameter") or {}
    failures: list[dict[str, Any]] = []
    if action in {"oscillates", "propagates"}:
        time_tokens = ("period", "duration", "travel_time", "cycle_time")
        if not isinstance(tracking_output, str) or not any(
            token in tracking_output for token in time_tokens
        ):
            failures.append(
                {
                    "gate": "action_contract",
                    "code": "dynamic_action_tracking_output_not_time",
                    "expected": {
                        "action": action,
                        "tracking_output_semantics": "positive period or duration",
                    },
                    "actual": {"tracking_output": tracking_output},
                }
            )
    if action in {"rotates", "orbits", "phases"}:
        parameter_id = str(parameter.get("id", ""))
        unit = str(parameter.get("unit", ""))
        if not ("angle" in parameter_id or "°" in unit or unit.lower() in {"deg", "rad"}):
            failures.append(
                {
                    "gate": "action_contract",
                    "code": "angular_action_parameter_not_angle",
                    "expected": {"action": action, "primary_parameter_semantics": "angle"},
                    "actual": {"parameter_id": parameter_id, "unit": unit},
                }
            )
    if action in {"flows", "floats_sinks", "responds"} and tracking_output is None:
        failures.append(
            {
                "gate": "action_contract",
                "code": "action_tracking_output_missing",
                "expected": {"action": action, "tracking_output_declared": True},
                "actual": {"tracking_output": None},
            }
        )
    return failures


def validate_module_output(document: dict[str, Any]) -> dict[str, Any]:
    return validate_document(document, load_schema("module.schema.json"))


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnswerPayload(ClosedModel):
    tldr: str
    key_formula: str | None = None


class StagePayload(ClosedModel):
    stage: str
    detail: str = Field(max_length=180)
    elapsed_ms: int = Field(ge=0)


class VerificationPayload(ClosedModel):
    passed: bool
    check_count: int = Field(ge=0)
    heal_count: int = Field(ge=0)
    evidence: list[str] = Field(max_length=20)


class HeartbeatPayload(ClosedModel):
    stage: str
    elapsed_ms: int = Field(ge=0)


class ResultEventPayload(ClosedModel):
    result_url: str
    sim_id: str
    title: str
    tier: Literal["A", "B"]


class FallbackPayload(ClosedModel):
    reason_code: str
    suggestions: list[str] = Field(max_length=3)


class TerminalPayload(ClosedModel):
    status: Literal["cancelled", "failed", "timed_out", "rejected", "qa_inconclusive"]
    reason_code: str


EventPayload = (
    AnswerPayload
    | StagePayload
    | VerificationPayload
    | HeartbeatPayload
    | ResultEventPayload
    | FallbackPayload
    | TerminalPayload
)


class PublicEvent(ClosedModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    id: int = Field(ge=1)
    type: Literal["answer", "stage", "verification", "heartbeat", "result", "fallback", "terminal"]
    job_id: str
    timestamp_ms: int = Field(ge=0)
    payload: EventPayload


class SimulationMetadata(ClosedModel):
    sim_id: str
    title: str
    lang: Literal["ar", "en"]
    direction: Literal["rtl", "ltr"]
    artifact_url: str
    share_url: str | None = None
    tier: Literal["A", "B"]
    effective_model: str
    elapsed_ms: int = Field(ge=0)
    check_count: int = Field(ge=0)
    heal_count: int = Field(ge=0)
    missed_strictness_checks: list[str] = Field(default_factory=list, max_length=20)


class FallbackResult(ClosedModel):
    reason_code: str
    suggestions: list[str] = Field(max_length=3)


class PublicResult(ClosedModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    job_id: str
    status: Literal[
        "queued",
        "filtering",
        "understanding",
        "answered",
        "cache_lookup",
        "generating",
        "verifying",
        "healing",
        "browser_check",
        "complete",
        "answer_only",
        "rejected",
        "failed",
        "cancelled",
        "timed_out",
        "qa_inconclusive",
    ]
    answer: AnswerPayload | None
    simulation: SimulationMetadata | None
    fallback: FallbackResult | None


class SharedSimulation(ClosedModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    status: Literal["complete"] = "complete"
    answer: AnswerPayload | None
    simulation: SimulationMetadata


class AskRequest(ClosedModel):
    question: str = Field(min_length=1, max_length=600)
    locale: Literal["ar", "en"] | None = None


class AskAccepted(ClosedModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    job_id: str
    stream_url: str
    result_url: str
