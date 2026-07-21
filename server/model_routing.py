from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

BOUNDED_SINGLE_PARAMETER = "bounded_single_parameter_v1"
COMPLEX_OR_MULTI_PARAMETER = "complex_or_multi_parameter_v1"
GENERATION_TIERS = frozenset(
    {BOUNDED_SINGLE_PARAMETER, COMPLEX_OR_MULTI_PARAMETER}
)
MEASURED_TERRA_GENERATION_TIERS = frozenset({BOUNDED_SINGLE_PARAMETER})
ROUTING_DECISION_PATH = Path(__file__).with_name("routing_decision.json")

GenerationTier = Literal[
    "bounded_single_parameter_v1",
    "complex_or_multi_parameter_v1",
]


def load_routing_decision(path: Path | None = None) -> tuple[str, ...]:
    """Load the closed data-only route selected by measured evidence."""

    selected_path = path or ROUTING_DECISION_PATH
    try:
        if selected_path.is_symlink():
            raise ValueError("routing decision cannot be a symlink")
        document = json.loads(selected_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        raise ValueError("routing_decision_invalid") from None
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "terra_generation_tiers",
    }:
        raise ValueError("routing_decision_invalid")
    tiers = document.get("terra_generation_tiers")
    if (
        document.get("schema_version") != "1.0"
        or not isinstance(tiers, list)
        or any(not isinstance(tier, str) for tier in tiers)
        or len(tiers) != len(set(tiers))
        or tiers != sorted(tiers)
        or not set(tiers) <= MEASURED_TERRA_GENERATION_TIERS
    ):
        raise ValueError("routing_decision_invalid")
    return tuple(tiers)


def routing_decision_sha256(path: Path | None = None) -> str:
    selected_path = path or ROUTING_DECISION_PATH
    load_routing_decision(selected_path)
    return hashlib.sha256(selected_path.read_bytes()).hexdigest()


def classify_generation_tier(understanding: dict[str, Any]) -> GenerationTier:
    """Classify only from closed structural complexity, never lesson identity."""

    outputs = understanding.get("module_spec", {}).get("outputs", [])
    checks = understanding.get("checks", [])
    if (
        understanding.get("secondary_parameter") is None
        and len(outputs) <= 2
        and len(checks) <= 4
    ):
        return BOUNDED_SINGLE_PARAMETER
    return COMPLEX_OR_MULTI_PARAMETER


@dataclass(frozen=True, slots=True)
class ModelRoutingPolicy:
    """Evidence-gated GPT-5.6 routing with a fail-safe direct-Sol default."""

    terra_eligible_tiers: frozenset[str] = field(
        default_factory=lambda: frozenset(load_routing_decision())
    )

    def __post_init__(self) -> None:
        unknown = self.terra_eligible_tiers - GENERATION_TIERS
        if unknown:
            raise ValueError(f"unknown generation routing tiers: {sorted(unknown)}")
        unmeasured = self.terra_eligible_tiers - MEASURED_TERRA_GENERATION_TIERS
        if unmeasured:
            raise ValueError(
                f"unmeasured generation routing tiers: {sorted(unmeasured)}"
            )

    def generation_model(self, understanding: dict[str, Any]) -> str:
        tier = classify_generation_tier(understanding)
        if tier in self.terra_eligible_tiers:
            return "gpt-5.6-terra"
        return "gpt-5.6-sol"

    def heal_model(self, understanding: dict[str, Any], attempt: int) -> str:
        if attempt == 1:
            return self.generation_model(understanding)
        if attempt == 2:
            return "gpt-5.6-sol"
        raise ValueError("heal routing supports exactly two bounded attempts")
