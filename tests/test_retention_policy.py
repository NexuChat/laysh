import pytest


def failure(gate, code, *, actual=None, numeric_cross_check=None):
    value = {
        "gate": gate,
        "code": code,
        "expected": {},
        "actual": actual or {},
    }
    if numeric_cross_check is not None:
        value["numeric_cross_check"] = numeric_cross_check
    return value


def test_all_checks_pass_is_tier_a():
    from server.retention_policy import classify_verification_failures

    decision = classify_verification_failures([])

    assert decision.tier == "A"
    assert decision.correctness_passed is True
    assert decision.missed_strictness_checks == ()


@pytest.mark.parametrize(
    "diagnostic,check_id",
    [
        (
            failure("mobile_overlay_safe_band", "mobile_overlay_count_exceeded"),
            "mobile_overlay_safe_band.mobile_overlay_count_exceeded",
        ),
        (
            failure(
                "visual_richness",
                "subject_idle_motion_insufficient",
                actual={"changed_pixel_ratio": 0.004},
            ),
            "visual_richness.subject_idle_motion_insufficient",
        ),
        (
            failure(
                "fixture_integrity",
                "suspect_relation_fixture",
                numeric_cross_check={"passing_fixture_ids": ["low", "high"]},
            ),
            "fixture_integrity.suspect_relation_fixture",
        ),
        (
            failure("semantic_vision", "semantic_labels_obscure_subject"),
            "semantic_vision.semantic_labels_obscure_subject",
        ),
    ],
)
def test_allowlisted_strictness_failure_is_tier_b(diagnostic, check_id):
    from server.retention_policy import classify_verification_failures

    decision = classify_verification_failures([diagnostic])

    assert decision.tier == "B"
    assert decision.correctness_passed is True
    assert decision.critical_failures == ()
    assert decision.missed_strictness_checks == (check_id,)


@pytest.mark.parametrize(
    "diagnostic",
    [
        failure("security", "forbidden_capability"),
        failure("invariant", "numeric_fixture_mismatch"),
        failure("render_output_consistency", "rendered_output_discontinuity"),
        failure("actor_action_tracking", "actor_trajectory_static"),
        failure("semantic_vision", "semantic_action_not_performed"),
        failure("semantic_vision", "semantic_physics_inconsistent"),
        failure(
            "visual_richness",
            "subject_idle_motion_insufficient",
            actual={"changed_pixel_ratio": 0.0004},
        ),
        failure("visual_richness", "whole_canvas_idle_motion_insufficient"),
        failure("fixture_integrity", "unknown_fixture_problem"),
        failure("future_gate", "unknown_failure"),
    ],
)
def test_correctness_or_unknown_failure_is_answer_only(diagnostic):
    from server.retention_policy import classify_verification_failures

    decision = classify_verification_failures([diagnostic])

    assert decision.tier == "answer_only"
    assert decision.correctness_passed is False
    assert decision.critical_failures == (diagnostic,)

