from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def _failure(
    code: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> dict[str, Any]:
    return {
        "gate": "physics_motion",
        "code": code,
        "expected": expected,
        "actual": actual,
    }


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _output(sample: Mapping[str, object], name: str) -> float | None:
    outputs = sample.get("model_outputs")
    return _number(outputs.get(name)) if isinstance(outputs, Mapping) else None


def _centroid(sample: Mapping[str, object]) -> tuple[float, float] | None:
    actor = sample.get("actor")
    if not isinstance(actor, Mapping):
        return None
    point = actor.get("centroid")
    if not isinstance(point, Mapping):
        return None
    x = _number(point.get("x"))
    y = _number(point.get("y"))
    return (x, y) if x is not None and y is not None else None


def _bounds(sample: Mapping[str, object]) -> tuple[float, float, float, float] | None:
    actor = sample.get("actor")
    if not isinstance(actor, Mapping):
        return None
    bounds = actor.get("bounds")
    if not isinstance(bounds, Mapping):
        return None
    values = tuple(_number(bounds.get(field)) for field in ("x", "y", "width", "height"))
    if any(value is None for value in values):
        return None
    x, y, width, height = (float(value) for value in values if value is not None)
    return (x, y, width, height) if width > 0 and height > 0 else None


def _control_value(sample: Mapping[str, object]) -> float | None:
    return _number(sample.get("control_value"))


def _within(actual: float | None, expected: float, tolerance: float) -> bool:
    return actual is not None and abs(actual - expected) <= tolerance


def _expect_output(
    failures: list[dict[str, Any]],
    *,
    code: str,
    sample: Mapping[str, object],
    output: str,
    expected: float,
    tolerance: float,
) -> None:
    actual = _output(sample, output)
    if not _within(actual, expected, tolerance):
        failures.append(
            _failure(
                code,
                {"output": output, "value": expected, "tolerance": tolerance},
                {"control_value": _control_value(sample), "value": actual},
            )
        )


def _strictly_increasing(values: Sequence[float]) -> bool:
    return all(later > earlier for earlier, later in zip(values, values[1:], strict=False))


def _moon(
    profile: Mapping[str, object],
    control_samples: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, Any]], int]:
    failures: list[dict[str, Any]] = []
    tolerance = _number(profile.get("tolerance")) or 0.01
    centroids: list[tuple[float, float]] = []
    illumination_signatures: list[str] = []
    illumination_pixels: list[int] = []
    for sample in control_samples:
        angle = _control_value(sample)
        if angle is None:
            failures.append(
                _failure(
                    "moon_angle_missing",
                    {"control_value_degrees": "finite"},
                    {"control_value": sample.get("control_value")},
                )
            )
            continue
        expected = (1 - math.cos(math.radians(angle))) / 2
        _expect_output(
            failures,
            code="moon_lit_fraction_mismatch",
            sample=sample,
            output="lit_fraction",
            expected=expected,
            tolerance=tolerance,
        )
        centroid = _centroid(sample)
        if centroid is not None:
            centroids.append(centroid)
        illumination = sample.get("illumination")
        if isinstance(illumination, Mapping):
            signature = illumination.get("signature")
            pixels = illumination.get("visible_pixels")
            if isinstance(signature, str) and signature:
                illumination_signatures.append(signature)
            if isinstance(pixels, int) and not isinstance(pixels, bool) and pixels > 0:
                illumination_pixels.append(pixels)
    if len(set(centroids)) < 2:
        failures.append(
            _failure(
                "moon_orbit_not_observed",
                {"distinct_orbital_positions": 2},
                {"centroids": [list(point) for point in centroids]},
            )
        )
    if len(set(illumination_signatures)) < 2 or len(set(illumination_pixels)) < 2:
        failures.append(
            _failure(
                "moon_illumination_geometry_static",
                {"distinct_illumination_geometries": 2},
                {
                    "signatures": illumination_signatures,
                    "visible_pixels": illumination_pixels,
                },
            )
        )
    return failures, len(control_samples) + 2


def _pendulum(
    profile: Mapping[str, object],
    control_samples: Sequence[Mapping[str, object]],
    temporal_runs: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, Any]], int]:
    failures: list[dict[str, Any]] = []
    gravity = _number(profile.get("gravity_m_s2")) or 9.81
    tolerance_ratio = _number(profile.get("period_tolerance_ratio")) or 0.05
    position_tolerance = _number(profile.get("position_tolerance")) or 0.02
    endpoint_tolerance = _number(profile.get("endpoint_tolerance")) or position_tolerance
    periods: dict[float, float] = {}
    for sample in control_samples:
        length = _control_value(sample)
        if length is None or length <= 0:
            failures.append(
                _failure(
                    "pendulum_length_missing",
                    {"positive_length_m": True},
                    {"control_value": sample.get("control_value")},
                )
            )
            continue
        expected = 2 * math.pi * math.sqrt(length / gravity)
        periods[length] = expected
        _expect_output(
            failures,
            code="pendulum_period_model_mismatch",
            sample=sample,
            output="period_s",
            expected=expected,
            tolerance=expected * tolerance_ratio,
        )
    if not temporal_runs:
        failures.append(
            _failure(
                "pendulum_temporal_trace_missing",
                {"temporal_runs": 1},
                {"temporal_runs": 0},
            )
        )
        return failures, len(control_samples) + 1
    run = temporal_runs[0]
    length = _number(run.get("control_value"))
    samples = run.get("samples")
    expected_period = periods.get(length) if length is not None else None
    if expected_period is None or not isinstance(samples, Sequence) or len(samples) < 5:
        failures.append(
            _failure(
                "pendulum_temporal_trace_missing",
                {"matched_length_trace_samples": 5},
                {
                    "control_value": length,
                    "sample_count": len(samples) if isinstance(samples, Sequence) else 0,
                },
            )
        )
        return failures, len(control_samples) + 1
    trace = [sample for sample in samples if isinstance(sample, Mapping)]
    times = [_number(sample.get("time_ms")) for sample in trace]
    centroids = [_centroid(sample) for sample in trace]
    if any(value is None for value in times) or not _strictly_increasing(
        [float(value) for value in times if value is not None]
    ):
        failures.append(
            _failure(
                "pendulum_temporal_trace_invalid",
                {"time_ms": "strictly_increasing"},
                {"time_ms": times},
            )
        )
    usable = [point for point in centroids if point is not None]
    displacements = [
        later[0] - earlier[0]
        for earlier, later in zip(usable, usable[1:], strict=False)
    ]
    if (
        not displacements
        or max(displacements) <= position_tolerance
        or min(displacements) >= -position_tolerance
    ):
        failures.append(
            _failure(
                "pendulum_direction_not_reversed",
                {
                    "horizontal_displacements": "contains_positive_and_negative",
                    "minimum_motion": position_tolerance,
                },
                {"horizontal_displacements": displacements},
            )
        )
    if len(times) == len(trace) and len(centroids) == len(trace) and all(centroids):
        duration_ms = float(times[-1]) - float(times[0])
        endpoint_distance = math.dist(centroids[0], centroids[-1])
        if (
            abs(duration_ms - expected_period * 1000) > expected_period * 1000 * tolerance_ratio
            or endpoint_distance > endpoint_tolerance
        ):
            failures.append(
                _failure(
                    "pendulum_period_mismatch",
                    {
                        "period_ms": expected_period * 1000,
                        "tolerance_ratio": tolerance_ratio,
                        "endpoint_distance_max": endpoint_tolerance,
                    },
                    {"duration_ms": duration_ms, "endpoint_distance": endpoint_distance},
                )
            )
    return failures, len(control_samples) + 3


def _day_night(
    profile: Mapping[str, object],
    control_samples: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, Any]], int]:
    failures: list[dict[str, Any]] = []
    tolerance = _number(profile.get("tolerance")) or 0.01
    observations: list[tuple[float, float, float]] = []
    for sample in control_samples:
        degrees = _control_value(sample)
        if degrees is None:
            failures.append(
                _failure(
                    "day_night_rotation_missing",
                    {"rotation_degrees": "finite"},
                    {"control_value": sample.get("control_value")},
                )
            )
            continue
        alignment = math.cos(math.radians(degrees))
        if abs(alignment) < 1e-12:
            alignment = 0.0
        expected_daylight = 1 if alignment > 0 else 0
        _expect_output(
            failures,
            code="day_night_alignment_mismatch",
            sample=sample,
            output="light_alignment",
            expected=alignment,
            tolerance=tolerance,
        )
        _expect_output(
            failures,
            code="day_night_daylight_mismatch",
            sample=sample,
            output="daylight",
            expected=expected_daylight,
            tolerance=tolerance,
        )
        centroid = _centroid(sample)
        if centroid is not None:
            observations.append((alignment, centroid[0], centroid[1]))
    if len(observations) < 2:
        failures.append(
            _failure(
                "day_night_landmark_not_rotating",
                {"visible_landmark_positions": 2},
                {"observations": observations},
            )
        )
        return failures, len(control_samples) + 1
    brightest = max(observations, key=lambda value: value[0])
    darkest = min(observations, key=lambda value: value[0])
    moving = len({(x, y) for _, x, y in observations}) >= 2
    from_left = profile.get("light_direction") == "from_left"
    direction_matches = brightest[1] < darkest[1] if from_left else brightest[1] > darkest[1]
    if not moving or not direction_matches:
        failures.append(
            _failure(
                "day_night_landmark_not_rotating",
                {
                    "fixed_light": profile.get("light_direction"),
                    "bright_side_landmark_x_relation": "less_than_dark_side"
                    if from_left
                    else "greater_than_dark_side",
                },
                {"brightest": brightest, "darkest": darkest, "observations": observations},
            )
        )
    return failures, len(control_samples) + 1


def _sound_pitch(
    profile: Mapping[str, object],
    control_samples: Sequence[Mapping[str, object]],
    temporal_runs: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, Any]], int]:
    failures: list[dict[str, Any]] = []
    tolerance = _number(profile.get("tolerance")) or 0.02
    minimum_variation = _number(profile.get("minimum_spatial_variation")) or 0.05
    for sample in control_samples:
        frequency = _control_value(sample)
        if frequency is None or frequency <= 0:
            failures.append(
                _failure(
                    "sound_frequency_missing",
                    {"frequency_hz": "positive"},
                    {"control_value": sample.get("control_value")},
                )
            )
            continue
        _expect_output(
            failures,
            code="sound_wavelength_mismatch",
            sample=sample,
            output="wavelength_m",
            expected=343 / frequency,
            tolerance=tolerance,
        )
        _expect_output(
            failures,
            code="sound_period_mismatch",
            sample=sample,
            output="period_ms",
            expected=1000 / frequency,
            tolerance=tolerance,
        )
    phase_samples = [
        sample
        for run in temporal_runs
        if isinstance(run.get("samples"), Sequence)
        for sample in run["samples"]
        if isinstance(sample, Mapping)
    ]
    columns: list[list[float]] = []
    for sample in phase_samples:
        values = sample.get("phase_columns")
        if not isinstance(values, Sequence) or len(values) < 3:
            continue
        numeric = [_number(value) for value in values]
        if all(value is not None for value in numeric):
            columns.append([float(value) for value in numeric if value is not None])
    spatial = all(max(values) - min(values) >= minimum_variation for values in columns)
    temporal = len(columns) >= 2 and any(
        abs(later - earlier) >= minimum_variation
        for earlier, later in zip(columns[0], columns[-1], strict=True)
    )
    if not spatial or not temporal:
        failures.append(
            _failure(
                "sound_spatial_phase_missing",
                {
                    "minimum_spatial_variation": minimum_variation,
                    "propagates_over_time": True,
                },
                {"phase_columns": columns},
            )
        )
    return failures, len(control_samples) * 2 + 1


def _trace_speed(samples: Sequence[Mapping[str, object]]) -> float | None:
    if len(samples) < 2:
        return None
    times = [_number(sample.get("time_ms")) for sample in samples]
    points = [_centroid(sample) for sample in samples]
    if any(value is None for value in times) or any(point is None for point in points):
        return None
    numeric_times = [float(value) for value in times if value is not None]
    numeric_points = [point for point in points if point is not None]
    duration = numeric_times[-1] - numeric_times[0]
    if duration <= 0 or not _strictly_increasing(numeric_times):
        return None
    travelled = sum(
        math.dist(left, right)
        for left, right in zip(numeric_points, numeric_points[1:], strict=False)
    )
    return travelled / duration


def _simple_circuit(
    profile: Mapping[str, object],
    control_samples: Sequence[Mapping[str, object]],
    temporal_runs: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, Any]], int]:
    failures: list[dict[str, Any]] = []
    tolerance = _number(profile.get("tolerance")) or 0.01
    minimum_speed_ratio = _number(profile.get("minimum_speed_ratio")) or 1.2
    currents: dict[float, float] = {}
    for sample in control_samples:
        resistance = _control_value(sample)
        if resistance is None or resistance <= 0:
            failures.append(
                _failure(
                    "circuit_resistance_missing",
                    {"resistance_ohm": "positive"},
                    {"control_value": sample.get("control_value")},
                )
            )
            continue
        current = 6 / resistance
        currents[resistance] = current
        _expect_output(
            failures,
            code="circuit_current_mismatch",
            sample=sample,
            output="current_a",
            expected=current,
            tolerance=tolerance,
        )
        _expect_output(
            failures,
            code="circuit_power_mismatch",
            sample=sample,
            output="power_w",
            expected=36 / resistance,
            tolerance=tolerance,
        )
    speeds: list[tuple[float, float, float]] = []
    for run in temporal_runs:
        resistance = _number(run.get("control_value"))
        samples = run.get("samples")
        if resistance is None or resistance not in currents or not isinstance(samples, Sequence):
            continue
        trace = [sample for sample in samples if isinstance(sample, Mapping)]
        speed = _trace_speed(trace)
        if speed is not None:
            speeds.append((currents[resistance], resistance, speed))
    if len(speeds) < 2:
        failures.append(
            _failure(
                "circuit_carrier_trace_missing",
                {"current_levels": 2},
                {"traces": speeds},
            )
        )
        return failures, len(control_samples) * 2 + 1
    high_current = max(speeds, key=lambda value: value[0])
    low_current = min(speeds, key=lambda value: value[0])
    if high_current[2] < low_current[2] * minimum_speed_ratio:
        failures.append(
            _failure(
                "circuit_carrier_speed_inconsistent",
                {
                    "higher_current_moves_faster": True,
                    "minimum_speed_ratio": minimum_speed_ratio,
                },
                {"high_current": high_current, "low_current": low_current},
            )
        )
    return failures, len(control_samples) * 2 + 1


def _buoyancy(
    profile: Mapping[str, object],
    control_samples: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, Any]], int]:
    failures: list[dict[str, Any]] = []
    tolerance = _number(profile.get("tolerance")) or 0.01
    waterline = _number(profile.get("waterline_y"))
    if waterline is None:
        failures.append(
            _failure(
                "buoyancy_waterline_missing",
                {"waterline_y": "normalized"},
                {"waterline_y": profile.get("waterline_y")},
            )
        )
        return failures, 1
    heights: list[tuple[float, float]] = []
    for sample in control_samples:
        density = _control_value(sample)
        if density is None or density <= 0:
            failures.append(
                _failure(
                    "buoyancy_density_missing",
                    {"density_kg_m3": "positive"},
                    {"control_value": sample.get("control_value")},
                )
            )
            continue
        fraction = min(density / 1000, 1)
        floats = 1 if density <= 1000 else 0
        _expect_output(
            failures,
            code="buoyancy_submerged_fraction_mismatch",
            sample=sample,
            output="submerged_fraction",
            expected=fraction,
            tolerance=tolerance,
        )
        _expect_output(
            failures,
            code="buoyancy_float_state_mismatch",
            sample=sample,
            output="floats",
            expected=floats,
            tolerance=tolerance,
        )
        centroid = _centroid(sample)
        bounds = _bounds(sample)
        if centroid is not None:
            heights.append((density, centroid[1]))
        if bounds is None:
            failures.append(
                _failure(
                    "buoyancy_equilibrium_mismatch",
                    {"actor_bounds": "visible"},
                    {"density_kg_m3": density, "bounds": None},
                )
            )
            continue
        _, top, _, height = bounds
        bottom = top + height
        equilibrium = top <= waterline <= bottom if floats else top >= waterline
        if not equilibrium:
            failures.append(
                _failure(
                    "buoyancy_equilibrium_mismatch",
                    {
                        "floating_body_intersects_waterline": bool(floats),
                        "sunk_body_below_waterline": not bool(floats),
                        "waterline_y": waterline,
                    },
                    {"density_kg_m3": density, "top": top, "bottom": bottom},
                )
            )
    heights.sort()
    if len(heights) >= 2 and any(
        later_y <= earlier_y
        for (_, earlier_y), (_, later_y) in zip(heights, heights[1:], strict=False)
    ):
        failures.append(
            _failure(
                "buoyancy_equilibrium_mismatch",
                {"actor_centroid_y": "increases_with_density"},
                {"density_and_y": heights},
            )
        )
    return failures, len(control_samples) * 3 + 1


def evaluate_action_physics(
    profile: Mapping[str, object],
    control_samples: Sequence[Mapping[str, object]],
    temporal_runs: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Evaluate the declared physical action from model outputs and actor traces."""

    kind = profile.get("kind")
    handlers = {
        "moon_phases": lambda: _moon(profile, control_samples),
        "pendulum": lambda: _pendulum(profile, control_samples, temporal_runs),
        "day_night": lambda: _day_night(profile, control_samples),
        "sound_pitch": lambda: _sound_pitch(profile, control_samples, temporal_runs),
        "simple_circuit": lambda: _simple_circuit(profile, control_samples, temporal_runs),
        "buoyancy": lambda: _buoyancy(profile, control_samples),
    }
    handler = handlers.get(kind)
    if handler is None:
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                _failure(
                    "physics_motion_kind_unknown",
                    {"kind": sorted(handlers)},
                    {"kind": kind},
                )
            ],
            "evidence": {},
        }
    failures, check_count = handler()
    return {
        "passed": not failures,
        "check_count": check_count,
        "failures": failures,
        "evidence": {
            "kind": kind,
            "control_sample_count": len(control_samples),
            "temporal_run_count": len(temporal_runs),
        },
    }
