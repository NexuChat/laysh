from __future__ import annotations

from typing import Any


def _failure(code: str, expected: object, actual: object) -> dict[str, Any]:
    return {
        "gate": "semantic_visual_qa",
        "code": code,
        "expected": expected,
        "actual": actual,
    }


def semantic_visual_qa_report(
    verdict: dict[str, Any],
    *,
    deterministic_passed: bool,
    browser_passed: bool,
) -> dict[str, Any]:
    """Combine a supplemental visual verdict with authoritative local gates."""

    failures: list[dict[str, Any]] = []
    if not deterministic_passed or not browser_passed:
        failures.append(
            _failure(
                "deterministic_gates_authoritative",
                {"deterministic_passed": True, "browser_passed": True},
                {
                    "deterministic_passed": deterministic_passed,
                    "browser_passed": browser_passed,
                },
            )
        )
    for field in ("actor_visible", "action_performed", "physically_consistent"):
        if verdict.get(field) is not True:
            failures.append(_failure(f"{field}_failed", True, verdict.get(field)))
    defects = verdict.get("defects")
    if defects:
        failures.append(_failure("visual_defects_reported", [], defects))
    return {
        "passed": not failures,
        "check_count": 5,
        "failures": failures,
        "verdict": verdict,
    }
