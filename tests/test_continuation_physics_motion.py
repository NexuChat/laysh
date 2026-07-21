from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _actor(x: float, y: float, *, width: float = 0.08, height: float = 0.08) -> dict[str, object]:
    return {
        "centroid": {"x": x, "y": y},
        "bounds": {"x": x - width / 2, "y": y - height / 2, "width": width, "height": height},
    }


def test_moon_phase_proof_requires_orbit_and_illumination_geometry():
    from server.physics_motion import evaluate_action_physics

    profile = {"kind": "moon_phases", "tolerance": 0.01}
    samples = [
        {
            "control_value": 0,
            "model_outputs": {"lit_fraction": 0.0},
            "actor": _actor(0.28, 0.5),
            "illumination": {"signature": "new", "visible_pixels": 10},
        },
        {
            "control_value": 90,
            "model_outputs": {"lit_fraction": 0.5},
            "actor": _actor(0.5, 0.28),
            "illumination": {"signature": "quarter", "visible_pixels": 52},
        },
        {
            "control_value": 180,
            "model_outputs": {"lit_fraction": 1.0},
            "actor": _actor(0.72, 0.5),
            "illumination": {"signature": "full", "visible_pixels": 100},
        },
    ]

    report = evaluate_action_physics(profile, samples, [])

    assert report["passed"] is True
    static_icon = deepcopy(samples)
    for sample in static_icon:
        sample["illumination"] = {"signature": "same-icon", "visible_pixels": 52}
    rejected = evaluate_action_physics(profile, static_icon, [])
    assert "moon_illumination_geometry_static" in {
        failure["code"] for failure in rejected["failures"]
    }


def test_pendulum_proof_requires_reversal_and_a_period_from_length_model():
    from server.physics_motion import evaluate_action_physics

    period = 2 * math.pi * math.sqrt(1 / 9.81)
    profile = {
        "kind": "pendulum",
        "gravity_m_s2": 9.81,
        "period_tolerance_ratio": 0.05,
        "pivot_x": 0.5,
        "position_tolerance": 0.02,
    }
    controls = [
        {
            "control_value": 0.25,
            "model_outputs": {"period_s": 2 * math.pi * math.sqrt(0.25 / 9.81)},
        },
        {"control_value": 1.0, "model_outputs": {"period_s": period}},
        {"control_value": 2.0, "model_outputs": {"period_s": 2 * math.pi * math.sqrt(2 / 9.81)}},
    ]
    temporal = [
        {
            "control_value": 1.0,
            "samples": [
                {"time_ms": 0, "actor": _actor(0.5, 0.68)},
                {"time_ms": round(period * 250), "actor": _actor(0.58, 0.65)},
                {"time_ms": round(period * 500), "actor": _actor(0.5, 0.68)},
                {"time_ms": round(period * 750), "actor": _actor(0.42, 0.65)},
                {"time_ms": round(period * 1000), "actor": _actor(0.5, 0.68)},
            ],
        }
    ]

    report = evaluate_action_physics(profile, controls, temporal)

    assert report["passed"] is True
    wrong_period = deepcopy(temporal)
    wrong_period[0]["samples"][-1]["time_ms"] = 1_000
    rejected = evaluate_action_physics(profile, controls, wrong_period)
    assert "pendulum_period_mismatch" in {failure["code"] for failure in rejected["failures"]}


def test_pendulum_direction_threshold_is_distinct_from_cycle_endpoint_tolerance():
    from server.physics_motion import evaluate_action_physics

    period = 2 * math.pi * math.sqrt(1 / 9.81)
    profile = {
        "kind": "pendulum",
        "gravity_m_s2": 9.81,
        "period_tolerance_ratio": 0.05,
        "pivot_x": 0.5,
        "position_tolerance": 0.01,
        "endpoint_tolerance": 0.03,
    }
    controls = [{"control_value": 1.0, "model_outputs": {"period_s": period}}]
    temporal = [
        {
            "control_value": 1.0,
            "samples": [
                {"time_ms": 0, "actor": _actor(0.5, 0.68)},
                {"time_ms": round(period * 250), "actor": _actor(0.54, 0.65)},
                {"time_ms": round(period * 500), "actor": _actor(0.5, 0.68)},
                {"time_ms": round(period * 750), "actor": _actor(0.46, 0.65)},
                {"time_ms": round(period * 1000), "actor": _actor(0.52, 0.68)},
            ],
        }
    ]

    report = evaluate_action_physics(profile, controls, temporal)

    assert report["passed"] is True


def test_pendulum_reversal_uses_actor_trajectory_not_the_highlight_centroid_bias():
    from server.physics_motion import evaluate_action_physics

    period = 2 * math.pi * math.sqrt(1 / 9.81)
    profile = {
        "kind": "pendulum",
        "gravity_m_s2": 9.81,
        "period_tolerance_ratio": 0.05,
        "pivot_x": 0.5,
        "position_tolerance": 0.007,
        "endpoint_tolerance": 0.03,
    }
    controls = [{"control_value": 1.0, "model_outputs": {"period_s": period}}]
    temporal = [
        {
            "control_value": 1.0,
            "samples": [
                {"time_ms": 0, "actor": _actor(0.526, 0.68)},
                {"time_ms": round(period * 250), "actor": _actor(0.514, 0.68)},
                {"time_ms": round(period * 500), "actor": _actor(0.535, 0.68)},
                {"time_ms": round(period * 750), "actor": _actor(0.546, 0.68)},
                {"time_ms": round(period * 1000), "actor": _actor(0.527, 0.68)},
            ],
        }
    ]

    report = evaluate_action_physics(profile, controls, temporal)

    assert report["passed"] is True


def test_day_night_proof_requires_landmark_rotation_against_fixed_light():
    from server.physics_motion import evaluate_action_physics

    profile = {"kind": "day_night", "tolerance": 0.01, "light_direction": "from_left"}
    samples = [
        {
            "control_value": 0,
            "model_outputs": {"light_alignment": 1.0, "daylight": 1},
            "actor": _actor(0.56, 0.46),
        },
        {
            "control_value": 90,
            "model_outputs": {"light_alignment": 0.0, "daylight": 0},
            "actor": _actor(0.68, 0.34),
        },
        {
            "control_value": 180,
            "model_outputs": {"light_alignment": -1.0, "daylight": 0},
            "actor": _actor(0.8, 0.46),
        },
    ]

    report = evaluate_action_physics(profile, samples, [])

    assert report["passed"] is True
    static_landmark = deepcopy(samples)
    for sample in static_landmark:
        sample["actor"] = _actor(0.68, 0.46)
    rejected = evaluate_action_physics(profile, static_landmark, [])
    assert "day_night_landmark_not_rotating" in {
        failure["code"] for failure in rejected["failures"]
    }


def test_sound_proof_requires_spatial_phase_not_an_amplitude_pulse():
    from server.physics_motion import evaluate_action_physics

    profile = {"kind": "sound_pitch", "tolerance": 0.02, "minimum_spatial_variation": 0.05}
    samples = [
        {
            "control_value": 110,
            "model_outputs": {"wavelength_m": 343 / 110, "period_ms": 1000 / 110},
        },
        {
            "control_value": 440,
            "model_outputs": {"wavelength_m": 343 / 440, "period_ms": 1000 / 440},
        },
        {
            "control_value": 880,
            "model_outputs": {"wavelength_m": 343 / 880, "period_ms": 1000 / 880},
        },
    ]
    temporal = [
        {
            "control_value": 440,
            "samples": [
                {"time_ms": 0, "phase_columns": [0.25, 0.55, 0.75, 0.45]},
                {"time_ms": 120, "phase_columns": [0.55, 0.75, 0.45, 0.25]},
            ],
        }
    ]

    report = evaluate_action_physics(profile, samples, temporal)

    assert report["passed"] is True
    amplitude_only = deepcopy(temporal)
    amplitude_only[0]["samples"] = [
        {"time_ms": 0, "phase_columns": [0.25, 0.25, 0.25, 0.25]},
        {"time_ms": 120, "phase_columns": [0.75, 0.75, 0.75, 0.75]},
    ]
    rejected = evaluate_action_physics(profile, samples, amplitude_only)
    assert "sound_spatial_phase_missing" in {failure["code"] for failure in rejected["failures"]}


def test_circuit_proof_requires_carrier_motion_to_increase_with_current():
    from server.physics_motion import evaluate_action_physics

    profile = {"kind": "simple_circuit", "tolerance": 0.01, "minimum_speed_ratio": 1.5}
    controls = [
        {"control_value": 2, "model_outputs": {"current_a": 3.0, "power_w": 18.0}},
        {"control_value": 12, "model_outputs": {"current_a": 0.5, "power_w": 3.0}},
    ]
    temporal = [
        {
            "control_value": 2,
            "samples": [
                {"time_ms": 0, "actor": _actor(0.2, 0.4)},
                {"time_ms": 100, "actor": _actor(0.35, 0.4)},
                {"time_ms": 200, "actor": _actor(0.5, 0.4)},
            ],
        },
        {
            "control_value": 12,
            "samples": [
                {"time_ms": 0, "actor": _actor(0.2, 0.4)},
                {"time_ms": 100, "actor": _actor(0.24, 0.4)},
                {"time_ms": 200, "actor": _actor(0.28, 0.4)},
            ],
        },
    ]

    report = evaluate_action_physics(profile, controls, temporal)

    assert report["passed"] is True
    equal_speed = deepcopy(temporal)
    equal_speed[1]["samples"][1]["actor"] = _actor(0.35, 0.4)
    equal_speed[1]["samples"][2]["actor"] = _actor(0.5, 0.4)
    rejected = evaluate_action_physics(profile, controls, equal_speed)
    assert "circuit_carrier_speed_inconsistent" in {
        failure["code"] for failure in rejected["failures"]
    }


def test_buoyancy_proof_requires_model_consistent_equilibrium_at_waterline():
    from server.physics_motion import evaluate_action_physics

    profile = {"kind": "buoyancy", "tolerance": 0.01, "waterline_y": 0.39}
    samples = [
        {
            "control_value": 250,
            "model_outputs": {"submerged_fraction": 0.25, "floats": 1},
            "actor": _actor(0.5, 0.35, height=0.16),
        },
        {
            "control_value": 750,
            "model_outputs": {"submerged_fraction": 0.75, "floats": 1},
            "actor": _actor(0.5, 0.43, height=0.16),
        },
        {
            "control_value": 1200,
            "model_outputs": {"submerged_fraction": 1.0, "floats": 0},
            "actor": _actor(0.5, 0.72, height=0.16),
        },
    ]

    report = evaluate_action_physics(profile, samples, [])

    assert report["passed"] is True
    floating_above_water = deepcopy(samples)
    floating_above_water[1]["actor"] = _actor(0.5, 0.2, height=0.1)
    rejected = evaluate_action_physics(profile, floating_above_water, [])
    assert "buoyancy_equilibrium_mismatch" in {failure["code"] for failure in rejected["failures"]}


def test_each_pinned_golden_declares_its_action_specific_physics_profile():
    expected = {
        "moon_phases_ar": "moon_phases",
        "pendulum_ar": "pendulum",
        "day_night_ar": "day_night",
        "sound_pitch_ar": "sound_pitch",
        "simple_circuit_ar": "simple_circuit",
        "buoyancy_ar": "buoyancy",
    }

    for fixture_id, kind in expected.items():
        fixture = json.loads(
            (ROOT / "server" / "fixtures" / f"{fixture_id}.json").read_text("utf-8")
        )
        profile = fixture["review_contract"]["physics_motion"]
        assert profile["kind"] == kind
        assert len(profile["control_values"]) >= 3
        assert all(isinstance(value, (int, float)) for value in profile["control_values"])
