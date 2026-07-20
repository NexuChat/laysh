from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _profile() -> dict[str, object]:
    return {
        "actor_region": {"x": 0.2, "y": 0.2, "width": 0.5, "height": 0.5},
        "sample_count": 4,
        "sample_interval_ms": 100,
    }


def _samples() -> list[dict[str, object]]:
    return [
        {
            "time_ms": index * 100,
            "frame_count": index + 1,
            "canvas_signature": f"canvas-{index}",
            "actor": {
                "visible_pixels": 48,
                "signature": f"actor-{index}",
                "centroid": {"x": 0.3 + index * 0.04, "y": 0.45},
                "bounds": {"x": 0.26 + index * 0.04, "y": 0.4, "width": 0.08, "height": 0.1},
            },
        }
        for index in range(4)
    ]


def test_actor_tracking_requires_a_trajectory_inside_the_declared_actor_region():
    from server.motion import evaluate_actor_trajectory

    report = evaluate_actor_trajectory(_profile(), _samples())

    assert report["passed"] is True
    assert report["evidence"]["actor_signatures"] == [
        "actor-0",
        "actor-1",
        "actor-2",
        "actor-3",
    ]
    assert report["evidence"]["frame_counts"] == [1, 2, 3, 4]


def test_actor_tracking_rejects_decorative_motion_and_invisible_actors():
    from server.motion import evaluate_actor_trajectory

    background_only = _samples()
    for index, sample in enumerate(background_only):
        sample["canvas_signature"] = f"moving-background-{index}"
        sample["actor"] = {
            "visible_pixels": 48,
            "signature": "unchanged-actor",
            "centroid": {"x": 0.4, "y": 0.45},
            "bounds": {"x": 0.36, "y": 0.4, "width": 0.08, "height": 0.1},
        }

    particles_outside_actor = _samples()
    for index, sample in enumerate(particles_outside_actor):
        sample["canvas_signature"] = f"particles-outside-{index}"
        sample["actor"] = {
            "visible_pixels": 48,
            "signature": "unchanged-actor",
            "centroid": {"x": 0.4, "y": 0.45},
            "bounds": {"x": 0.36, "y": 0.4, "width": 0.08, "height": 0.1},
        }

    hidden_actor = _samples()
    for sample in hidden_actor:
        sample["actor"] = {
            "visible_pixels": 0,
            "signature": "",
            "centroid": None,
            "bounds": None,
        }

    off_canvas_actor = _samples()
    for sample in off_canvas_actor:
        sample["actor"] = {
            "visible_pixels": 48,
            "signature": "moving-off-canvas",
            "centroid": {"x": 1.2, "y": 0.45},
            "bounds": {"x": 1.1, "y": 0.4, "width": 0.08, "height": 0.1},
        }

    frame_counter_only = _samples()
    for index, sample in enumerate(frame_counter_only):
        sample["frame_count"] = 100 + index
        sample["canvas_signature"] = "same-canvas"
        sample["actor"] = {
            "visible_pixels": 48,
            "signature": "unchanged-actor",
            "centroid": {"x": 0.4, "y": 0.45},
            "bounds": {"x": 0.36, "y": 0.4, "width": 0.08, "height": 0.1},
        }

    cases = {
        "moving_background_only": background_only,
        "particles_outside_actor_region": particles_outside_actor,
        "hidden_actor": hidden_actor,
        "off_canvas_actor": off_canvas_actor,
        "frame_counter_only": frame_counter_only,
    }
    for name, samples in cases.items():
        report = evaluate_actor_trajectory(_profile(), samples)
        assert report["passed"] is False, name
        codes = {failure["code"] for failure in report["failures"]}
        if name in {"hidden_actor", "off_canvas_actor"}:
            assert "actor_not_visible" in codes
        else:
            assert "actor_trajectory_static" in codes


def test_actor_tracking_rejects_too_few_or_non_chronological_samples():
    from server.motion import evaluate_actor_trajectory

    too_few = evaluate_actor_trajectory(_profile(), _samples()[:3])
    assert too_few["passed"] is False
    assert {failure["code"] for failure in too_few["failures"]} == {
        "actor_sample_count_mismatch"
    }

    non_chronological = _samples()
    non_chronological[2]["time_ms"] = non_chronological[1]["time_ms"]
    report = evaluate_actor_trajectory(_profile(), non_chronological)
    assert report["passed"] is False
    assert "actor_timestamps_not_strictly_increasing" in {
        failure["code"] for failure in report["failures"]
    }


def test_each_pinned_golden_declares_a_closed_actor_tracking_profile():
    expected_actor_actions = {
        "moon_phases_ar": ("moon", "orbits"),
        "pendulum_ar": ("pendulum_bob", "oscillates"),
        "day_night_ar": ("earth_landmark", "rotates"),
        "sound_pitch_ar": ("wavefront", "propagates"),
        "simple_circuit_ar": ("charge_carrier", "flows"),
        "buoyancy_ar": ("floating_body", "floats_sinks"),
    }

    for fixture_id, actor_action in expected_actor_actions.items():
        fixture = json.loads(
            (ROOT / "server" / "fixtures" / f"{fixture_id}.json").read_text("utf-8")
        )
        contract = fixture["review_contract"]
        profile = contract["actor_tracking"]
        assert (contract["actor"], contract["action"]) == actor_action
        assert set(profile) == {
            "actor_region",
            "sample_count",
            "sample_interval_ms",
            "actor_color",
        }
        assert set(profile["actor_region"]) == {"x", "y", "width", "height"}
        assert set(profile["actor_color"]) == {
            "red",
            "green",
            "blue",
            "tolerance",
        }
        assert profile["sample_count"] >= 4
        assert profile["sample_interval_ms"] >= 16
        assert 0 <= profile["actor_region"]["x"] < 1
        assert 0 <= profile["actor_region"]["y"] < 1
        assert 0 < profile["actor_region"]["width"] <= 1
        assert 0 < profile["actor_region"]["height"] <= 1
        assert profile["actor_region"]["x"] + profile["actor_region"]["width"] <= 1
        assert profile["actor_region"]["y"] + profile["actor_region"]["height"] <= 1
