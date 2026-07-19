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
    if document["simulatable"] and len(document["checks"]) < 2:
        raise ContractError("a simulatable lesson requires at least two independent checks")
    return document


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
    status: Literal["cancelled", "failed", "timed_out", "rejected"]
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
    tier: Literal["A", "B"]
    effective_model: str
    elapsed_ms: int = Field(ge=0)
    check_count: int = Field(ge=0)
    heal_count: int = Field(ge=0)


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
    ]
    answer: AnswerPayload | None
    simulation: SimulationMetadata | None
    fallback: FallbackResult | None


class AskRequest(ClosedModel):
    question: str = Field(min_length=1, max_length=600)
    locale: Literal["ar", "en"] | None = None


class AskAccepted(ClosedModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    job_id: str
    stream_url: str
    result_url: str
