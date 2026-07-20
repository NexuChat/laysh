from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from server.browser_verify import WHOLE_CANVAS_MOTION_MIN_CHANGED_PIXEL_RATIO


@dataclass(frozen=True, slots=True)
class RetentionDecision:
    tier: Literal["A", "B", "answer_only"]
    critical_failures: tuple[dict[str, Any], ...]
    strictness_failures: tuple[dict[str, Any], ...]
    missed_strictness_checks: tuple[str, ...]

    @property
    def correctness_passed(self) -> bool:
        return not self.critical_failures


def _check_id(failure: dict[str, Any]) -> str:
    return f"{failure.get('gate', 'unknown')}.{failure.get('code', 'unknown')}"


def _is_strictness_failure(failure: dict[str, Any]) -> bool:
    gate = failure.get("gate")
    code = failure.get("code")
    if gate == "mobile_overlay_safe_band":
        return True
    if gate == "visual_richness" and code == "subject_idle_motion_insufficient":
        ratio = failure.get("actual", {}).get("changed_pixel_ratio")
        return (
            isinstance(ratio, (int, float))
            and ratio >= WHOLE_CANVAS_MOTION_MIN_CHANGED_PIXEL_RATIO
        )
    if gate == "fixture_integrity" and code == "suspect_relation_fixture":
        passing = failure.get("numeric_cross_check", {}).get("passing_fixture_ids")
        return isinstance(passing, list) and bool(passing)
    return gate == "semantic_vision" and code == "semantic_labels_obscure_subject"


def classify_verification_failures(
    failures: list[dict[str, Any]],
) -> RetentionDecision:
    strictness = tuple(failure for failure in failures if _is_strictness_failure(failure))
    critical = tuple(failure for failure in failures if not _is_strictness_failure(failure))
    if critical:
        tier: Literal["A", "B", "answer_only"] = "answer_only"
    elif strictness:
        tier = "B"
    else:
        tier = "A"
    missed = tuple(dict.fromkeys(_check_id(failure) for failure in strictness))
    return RetentionDecision(
        tier=tier,
        critical_failures=critical,
        strictness_failures=strictness,
        missed_strictness_checks=missed,
    )
