from __future__ import annotations

from copy import deepcopy

import pytest


def _candidate(*, artifact_sha256: str, incumbent_sha256: str | None = None) -> dict:
    return {
        "tier": "A",
        "artifact_sha256": artifact_sha256,
        "incumbent_artifact_sha256": incumbent_sha256,
        "evidence": {
            "deterministic": {"passed": True, "contract_valid": True},
            "contract": {"passed": True, "answer_complete": True},
            "qa": {"passed": True, "visual_richness": True},
            "browser": {
                "ready": True,
                "runtimeError": False,
                "externalRequests": 0,
                "cases": [
                    {"frameChanged": True, "visualSignature": 101},
                    {"frameChanged": True, "visualSignature": 202},
                    {"frameChanged": True, "visualSignature": 303},
                ],
                "idleFrameChanged": True,
                "reactiveFrameVariants": 3,
            },
            "screenshots": [
                {"viewport": "mobile", "sha256": "b" * 64, "bytes": 20_000},
                {"viewport": "desktop", "sha256": "c" * 64, "bytes": 30_000},
            ],
        },
    }


def _comparison_inputs() -> tuple[dict, dict]:
    incumbent = _candidate(artifact_sha256="a" * 64)
    candidate = _candidate(
        artifact_sha256="d" * 64,
        incumbent_sha256=incumbent["artifact_sha256"],
    )
    return incumbent, candidate


def test_incumbent_tier_a_cannot_be_replaced_by_tier_b_candidate():
    from server.promotion import PromotionReasonCode, compare_promotion_candidate

    incumbent, candidate = _comparison_inputs()
    candidate["tier"] = "B"

    decision = compare_promotion_candidate(incumbent, candidate)

    assert decision.approved is False
    assert decision.reason_code is PromotionReasonCode.CANDIDATE_TIER_REGRESSION


def test_equal_or_improved_tier_a_candidate_is_approved():
    from server.promotion import PromotionReasonCode, compare_promotion_candidate

    incumbent, candidate = _comparison_inputs()
    candidate["evidence"]["screenshots"][0]["bytes"] = 21_000
    candidate["evidence"]["browser"]["reactiveFrameVariants"] = 4

    decision = compare_promotion_candidate(incumbent, candidate)

    assert decision.approved is True
    assert decision.reason_code is PromotionReasonCode.APPROVED
    assert decision.incumbent_artifact_sha256 == incumbent["artifact_sha256"]


@pytest.mark.parametrize(
    ("mutate", "reason_name"),
    [
        (
            lambda candidate: candidate["evidence"]["screenshots"][0].update(bytes=18_000),
            "SCREENSHOT_REGRESSION",
        ),
        (
            lambda candidate: [
                item.update(visualSignature=101)
                for item in candidate["evidence"]["browser"]["cases"]
            ],
            "VISUAL_SIGNATURE_REGRESSION",
        ),
        (
            lambda candidate: candidate["evidence"]["browser"].update(
                idleFrameChanged=False
            ),
            "IDLE_FRAME_REGRESSION",
        ),
        (
            lambda candidate: candidate["evidence"]["browser"].update(
                reactiveFrameVariants=2
            ),
            "REACTIVE_FRAME_VARIANTS_REGRESSION",
        ),
    ],
)
def test_degraded_visual_or_motion_evidence_is_rejected(mutate, reason_name):
    from server.promotion import PromotionReasonCode, compare_promotion_candidate

    incumbent, candidate = _comparison_inputs()
    mutate(candidate)

    decision = compare_promotion_candidate(incumbent, candidate)

    assert decision.approved is False
    assert decision.reason_code is getattr(PromotionReasonCode, reason_name)


def test_missing_incumbent_evidence_fails_closed():
    from server.promotion import PromotionReasonCode, compare_promotion_candidate

    incumbent, candidate = _comparison_inputs()
    incomplete_incumbent = deepcopy(incumbent)
    incomplete_incumbent["evidence"].pop("screenshots")

    decision = compare_promotion_candidate(incomplete_incumbent, candidate)

    assert decision.approved is False
    assert decision.reason_code is PromotionReasonCode.MISSING_INCUMBENT_EVIDENCE


def test_stale_incumbent_hash_is_rejected():
    from server.promotion import PromotionReasonCode, compare_promotion_candidate

    incumbent, candidate = _comparison_inputs()
    candidate["incumbent_artifact_sha256"] = "e" * 64

    decision = compare_promotion_candidate(incumbent, candidate)

    assert decision.approved is False
    assert decision.reason_code is PromotionReasonCode.STALE_INCUMBENT_HASH
