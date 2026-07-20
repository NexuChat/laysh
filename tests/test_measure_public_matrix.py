from types import SimpleNamespace


def test_measurement_outcome_reports_tier_b_polish_without_correctness_failure():
    from scripts.measure_public_matrix import _outcome_fields

    record = SimpleNamespace(
        status="complete",
        simulation=SimpleNamespace(
            tier="B",
            missed_strictness_checks=[
                "mobile_overlay_safe_band.mobile_overlay_count_exceeded"
            ],
        ),
    )
    fields = _outcome_fields(record, [])

    assert fields == {
        "outcome": "Tier B",
        "correctness_critical_failures": [],
        "missed_strictness_checks": [
            "mobile_overlay_safe_band.mobile_overlay_count_exceeded"
        ],
    }


def test_measurement_outcome_reports_actor_gate_that_forced_answer_only():
    from scripts.measure_public_matrix import _outcome_fields

    attempts = [
        {
            "failures": [
                {
                    "gate": "actor_action_tracking",
                    "code": "actor_trajectory_static",
                    "expected": {},
                    "actual": {},
                },
                {
                    "gate": "mobile_overlay_safe_band",
                    "code": "mobile_overlay_count_exceeded",
                    "expected": {},
                    "actual": {},
                },
            ]
        }
    ]
    record = SimpleNamespace(status="answer_only", simulation=None)
    fields = _outcome_fields(record, attempts)

    assert fields["outcome"] == "answer-only"
    assert fields["correctness_critical_failures"] == [
        "actor_action_tracking.actor_trajectory_static"
    ]
    assert fields["missed_strictness_checks"] == []
