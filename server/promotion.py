from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

PromotionRoute = Literal["stable", "experimental"]

STABLE_ROUTE: PromotionRoute = "stable"
EXPERIMENTAL_ROUTE: PromotionRoute = "experimental"
EXPERIMENTAL_PROMOTION_GATES = frozenset(
    {
        "contracts",
        "physics_fixtures",
        "actor_motion",
        "browser",
        "download",
        "accessibility",
    }
)

SCREENSHOT_MINIMUM_SIZE_RATIO = 0.95
REQUIRED_SCREENSHOT_VIEWPORTS = frozenset({"mobile", "desktop"})


class PromotionReasonCode(str, Enum):
    APPROVED = "approved"
    CANDIDATE_TIER_REGRESSION = "candidate_tier_regression"
    MISSING_INCUMBENT_EVIDENCE = "missing_incumbent_evidence"
    MISSING_CANDIDATE_EVIDENCE = "missing_candidate_evidence"
    STALE_INCUMBENT_HASH = "stale_incumbent_hash"
    DETERMINISTIC_REGRESSION = "deterministic_regression"
    CONTRACT_REGRESSION = "contract_regression"
    QA_REGRESSION = "qa_regression"
    BROWSER_REGRESSION = "browser_regression"
    SCREENSHOT_REGRESSION = "screenshot_regression"
    VISUAL_SIGNATURE_REGRESSION = "visual_signature_regression"
    IDLE_FRAME_REGRESSION = "idle_frame_regression"
    REACTIVE_FRAME_VARIANTS_REGRESSION = "reactive_frame_variants_regression"


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    approved: bool
    reason_code: PromotionReasonCode
    incumbent_artifact_sha256: str


def _decision(
    approved: bool,
    reason_code: PromotionReasonCode,
    incumbent: Mapping[str, Any],
) -> PromotionDecision:
    artifact_sha256 = incumbent.get("artifact_sha256")
    return PromotionDecision(
        approved=approved,
        reason_code=reason_code,
        incumbent_artifact_sha256=(artifact_sha256 if isinstance(artifact_sha256, str) else ""),
    )


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _true_paths(value: Mapping[str, Any], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if child is True:
            paths.add(path)
        elif isinstance(child, Mapping):
            paths.update(_true_paths(child, path))
    return paths


def _at_path(value: Mapping[str, Any], path: str) -> object:
    current: object = value
    for key in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _screenshot_index(value: object) -> dict[str, Mapping[str, Any]] | None:
    if not isinstance(value, list):
        return None
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in value:
        screenshot = _mapping(item)
        if screenshot is None:
            return None
        viewport = screenshot.get("viewport")
        digest = screenshot.get("sha256")
        byte_count = screenshot.get("bytes")
        if (
            not isinstance(viewport, str)
            or viewport in indexed
            or not isinstance(digest, str)
            or len(digest) != 64
            or not isinstance(byte_count, int)
            or byte_count <= 0
        ):
            return None
        indexed[viewport] = screenshot
    return indexed if set(indexed) == REQUIRED_SCREENSHOT_VIEWPORTS else None


def _browser_evidence(value: object) -> Mapping[str, Any] | None:
    browser = _mapping(value)
    if browser is None:
        return None
    cases = browser.get("cases")
    if (
        not isinstance(browser.get("ready"), bool)
        or not isinstance(browser.get("runtimeError"), bool)
        or not isinstance(browser.get("externalRequests"), int)
        or not isinstance(browser.get("idleFrameChanged"), bool)
        or not isinstance(browser.get("reactiveFrameVariants"), int)
        or not isinstance(cases, list)
        or len(cases) != 3
    ):
        return None
    for case in cases:
        item = _mapping(case)
        if (
            item is None
            or not isinstance(item.get("frameChanged"), bool)
            or not isinstance(item.get("visualSignature"), int)
        ):
            return None
    return browser


def _browser_passed(browser: Mapping[str, Any]) -> bool:
    return (
        browser["ready"] is True
        and browser["runtimeError"] is False
        and browser["externalRequests"] == 0
        and all(case["frameChanged"] is True for case in browser["cases"])
    )


def compare_promotion_candidate(
    incumbent: Mapping[str, Any], candidate: Mapping[str, Any]
) -> PromotionDecision:
    """Fail closed unless a replacement retains all incumbent promotion evidence."""

    incumbent_sha256 = incumbent.get("artifact_sha256")
    if not isinstance(incumbent_sha256, str) or len(incumbent_sha256) != 64:
        return _decision(False, PromotionReasonCode.MISSING_INCUMBENT_EVIDENCE, incumbent)
    if candidate.get("incumbent_artifact_sha256") != incumbent_sha256:
        return _decision(False, PromotionReasonCode.STALE_INCUMBENT_HASH, incumbent)
    if incumbent.get("tier") == "A" and candidate.get("tier") != "A":
        return _decision(False, PromotionReasonCode.CANDIDATE_TIER_REGRESSION, incumbent)

    incumbent_evidence = _mapping(incumbent.get("evidence"))
    candidate_evidence = _mapping(candidate.get("evidence"))
    if incumbent_evidence is None:
        return _decision(False, PromotionReasonCode.MISSING_INCUMBENT_EVIDENCE, incumbent)
    if candidate_evidence is None:
        return _decision(False, PromotionReasonCode.MISSING_CANDIDATE_EVIDENCE, incumbent)

    for section, reason in (
        ("deterministic", PromotionReasonCode.DETERMINISTIC_REGRESSION),
        ("contract", PromotionReasonCode.CONTRACT_REGRESSION),
        ("qa", PromotionReasonCode.QA_REGRESSION),
    ):
        incumbent_section = _mapping(incumbent_evidence.get(section))
        candidate_section = _mapping(candidate_evidence.get(section))
        if incumbent_section is None:
            return _decision(False, PromotionReasonCode.MISSING_INCUMBENT_EVIDENCE, incumbent)
        if candidate_section is None:
            return _decision(False, PromotionReasonCode.MISSING_CANDIDATE_EVIDENCE, incumbent)
        if any(
            _at_path(candidate_section, path) is not True
            for path in _true_paths(incumbent_section)
        ):
            return _decision(False, reason, incumbent)

    incumbent_browser = _browser_evidence(incumbent_evidence.get("browser"))
    if incumbent_browser is None or not _browser_passed(incumbent_browser):
        return _decision(False, PromotionReasonCode.MISSING_INCUMBENT_EVIDENCE, incumbent)
    candidate_browser = _browser_evidence(candidate_evidence.get("browser"))
    if candidate_browser is None or not _browser_passed(candidate_browser):
        return _decision(False, PromotionReasonCode.BROWSER_REGRESSION, incumbent)
    incumbent_signatures = {
        case["visualSignature"] for case in incumbent_browser["cases"]
    }
    candidate_signatures = {
        case["visualSignature"] for case in candidate_browser["cases"]
    }
    if len(candidate_signatures) < len(incumbent_signatures):
        return _decision(False, PromotionReasonCode.VISUAL_SIGNATURE_REGRESSION, incumbent)
    if (
        incumbent_browser["idleFrameChanged"] is True
        and candidate_browser["idleFrameChanged"] is not True
    ):
        return _decision(False, PromotionReasonCode.IDLE_FRAME_REGRESSION, incumbent)
    if candidate_browser["reactiveFrameVariants"] < incumbent_browser["reactiveFrameVariants"]:
        return _decision(
            False, PromotionReasonCode.REACTIVE_FRAME_VARIANTS_REGRESSION, incumbent
        )

    incumbent_screenshots = _screenshot_index(incumbent_evidence.get("screenshots"))
    if incumbent_screenshots is None:
        return _decision(False, PromotionReasonCode.MISSING_INCUMBENT_EVIDENCE, incumbent)
    candidate_screenshots = _screenshot_index(candidate_evidence.get("screenshots"))
    if candidate_screenshots is None:
        return _decision(False, PromotionReasonCode.MISSING_CANDIDATE_EVIDENCE, incumbent)
    for viewport, incumbent_screenshot in incumbent_screenshots.items():
        candidate_screenshot = candidate_screenshots[viewport]
        if candidate_screenshot["bytes"] < (
            incumbent_screenshot["bytes"] * SCREENSHOT_MINIMUM_SIZE_RATIO
        ):
            return _decision(False, PromotionReasonCode.SCREENSHOT_REGRESSION, incumbent)
    return _decision(True, PromotionReasonCode.APPROVED, incumbent)


def require_stable_cache_eligibility(
    *,
    route_label: str,
    receipt_verified: bool,
    passed_gates: frozenset[str],
) -> None:
    if route_label not in {STABLE_ROUTE, EXPERIMENTAL_ROUTE}:
        raise ValueError("stable cache promotion requires an explicit route label")
    if not receipt_verified:
        raise ValueError("stable cache promotion requires a verified receipt")
    if route_label == EXPERIMENTAL_ROUTE:
        missing = sorted(EXPERIMENTAL_PROMOTION_GATES - passed_gates)
        if missing:
            raise ValueError(
                "experimental route is missing stable promotion gates: "
                + ", ".join(missing)
            )
