from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class VisionVerificationResult:
    passed: bool
    failure: dict[str, Any] | None
    verdict: dict[str, Any]


def evaluate_vision_verdict(verdict: dict[str, Any]) -> VisionVerificationResult:
    expected = {
        "actor_visible": True,
        "action_performed": True,
        "physically_consistent": True,
    }
    passed = all(verdict.get(field) is value for field, value in expected.items())
    if passed:
        return VisionVerificationResult(True, None, verdict)
    if verdict.get("actor_visible") is not True:
        code = "semantic_actor_not_visible"
    elif verdict.get("action_performed") is not True:
        code = "semantic_action_not_performed"
    else:
        code = "semantic_physics_inconsistent"
    return VisionVerificationResult(
        False,
        {
            "gate": "semantic_vision",
            "code": code,
            "expected": expected,
            "actual": verdict,
        },
        verdict,
    )
