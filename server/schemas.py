from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "1.0"
SCHEMA_DIR = Path(__file__).parent / "schemas"
MISCONCEPTION_PREFIX = {"ar": "تصحيح:", "en": "Correction:"}


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
    actor = document["module_spec"]["actor"]
    action = document["module_spec"]["action"]
    if document["simulatable"] and (actor is None or action is None):
        raise ContractError("a simulatable lesson requires an actor and action")
    if not document["simulatable"] and (actor is not None or action is not None):
        raise ContractError("a non-simulatable lesson must not declare an actor or action")
    misconception = document["misconception"]
    if misconception and not has_explicit_misconception_correction(
        document["lang"], misconception
    ):
        raise ContractError("a misconception requires an explicit correction")
    return document


def has_explicit_misconception_correction(language: str, value: str) -> bool:
    prefix = MISCONCEPTION_PREFIX[language]
    if not value.startswith(prefix):
        return False
    correction = value.removeprefix(prefix).strip()
    if language == "ar":
        return len(correction) >= 12 and (" لا " in correction or "ليس " in correction)
    return len(correction) >= 12 and "not " in correction.lower()


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
    tier: Literal["A", "B"]
    effective_model: str
    elapsed_ms: int = Field(ge=0)
    check_count: int = Field(ge=0)
    heal_count: int = Field(ge=0)


class RuntimeStageReceipt(ClosedModel):
    """A sanitized, ordered receipt for one runtime-model attempt."""

    stage: Literal["understand", "generate", "heal", "qa"]
    attempt: int = Field(ge=1)
    model: Literal["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
    outcome: Literal["completed", "failed"]
    elapsed_ms: int | None = Field(default=None, ge=0)
    failure_code: str | None = None


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
    runtime_receipts: list[RuntimeStageReceipt] = Field(default_factory=list)


class AskRequest(ClosedModel):
    question: str = Field(min_length=1, max_length=600)
    locale: Literal["ar", "en"] | None = None


class AskAccepted(ClosedModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    job_id: str
    stream_url: str
    result_url: str
