from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _failure(code: str, expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    return {
        "gate": "actor_motion",
        "code": code,
        "expected": expected,
        "actual": actual,
    }


def _finite_unit(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if 0 <= numeric <= 1 else None


def _region(profile: Mapping[str, object]) -> dict[str, float] | None:
    raw = profile.get("actor_region")
    if not isinstance(raw, Mapping):
        return None
    fields = {name: _finite_unit(raw.get(name)) for name in ("x", "y", "width", "height")}
    if any(value is None for value in fields.values()):
        return None
    region = {name: float(value) for name, value in fields.items() if value is not None}
    if region["width"] <= 0 or region["height"] <= 0:
        return None
    if region["x"] + region["width"] > 1 or region["y"] + region["height"] > 1:
        return None
    return region


def _inside_region(
    bounds: Mapping[str, object], region: Mapping[str, float]
) -> bool:
    coordinates = {name: _finite_unit(bounds.get(name)) for name in ("x", "y", "width", "height")}
    if any(value is None for value in coordinates.values()):
        return False
    actor = {name: float(value) for name, value in coordinates.items() if value is not None}
    if actor["width"] <= 0 or actor["height"] <= 0:
        return False
    if actor["x"] + actor["width"] > 1 or actor["y"] + actor["height"] > 1:
        return False
    return (
        actor["x"] >= region["x"]
        and actor["y"] >= region["y"]
        and actor["x"] + actor["width"] <= region["x"] + region["width"]
        and actor["y"] + actor["height"] <= region["y"] + region["height"]
    )


def _centroid_key(value: object) -> tuple[float, float] | None:
    if not isinstance(value, Mapping):
        return None
    x = _finite_unit(value.get("x"))
    y = _finite_unit(value.get("y"))
    if x is None or y is None:
        return None
    return (x, y)


def evaluate_actor_trajectory(
    profile: Mapping[str, object], samples: Sequence[Mapping[str, object]]
) -> dict[str, Any]:
    """Reject anything except a visible, changing actor inside its declared region.

    The inputs are intentionally limited to an actor-only probe result. Whole-canvas
    hashes and frame counters are retained as evidence but never contribute to a pass.
    """

    failures: list[dict[str, Any]] = []
    region = _region(profile)
    expected_count = profile.get("sample_count")
    if region is None or isinstance(expected_count, bool) or not isinstance(expected_count, int):
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                _failure(
                    "actor_tracking_profile_invalid",
                    {
                        "actor_region": "normalized_nonempty_rectangle",
                        "sample_count": "positive_integer",
                    },
                    {"actor_region": profile.get("actor_region"), "sample_count": expected_count},
                )
            ],
            "evidence": {},
        }
    if expected_count < 4:
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                _failure(
                    "actor_tracking_profile_invalid",
                    {"sample_count": "integer_at_least_4"},
                    {"sample_count": expected_count},
                )
            ],
            "evidence": {},
        }
    if len(samples) != expected_count:
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                _failure(
                    "actor_sample_count_mismatch",
                    {"sample_count": expected_count},
                    {"sample_count": len(samples)},
                )
            ],
            "evidence": {},
        }

    timestamps: list[int | float] = []
    actor_signatures: list[str] = []
    actor_centroids: list[tuple[float, float]] = []
    visible_sample_count = 0
    for index, sample in enumerate(samples):
        timestamp = sample.get("time_ms")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            failures.append(
                _failure(
                    "actor_timestamps_not_strictly_increasing",
                    {"time_ms": "finite_strictly_increasing"},
                    {"sample_index": index, "time_ms": timestamp},
                )
            )
        else:
            timestamps.append(timestamp)

        actor = sample.get("actor")
        if not isinstance(actor, Mapping):
            failures.append(
                _failure(
                    "actor_not_visible",
                    {"visible_actor_samples": expected_count},
                    {"sample_index": index, "actor": actor},
                )
            )
            continue
        pixels = actor.get("visible_pixels")
        signature = actor.get("signature")
        bounds = actor.get("bounds")
        centroid = _centroid_key(actor.get("centroid"))
        visible = (
            isinstance(pixels, int)
            and not isinstance(pixels, bool)
            and pixels > 0
            and isinstance(signature, str)
            and bool(signature)
            and isinstance(bounds, Mapping)
            and _inside_region(bounds, region)
            and centroid is not None
        )
        if not visible:
            failures.append(
                _failure(
                    "actor_not_visible",
                    {
                        "visible_pixels": "positive",
                        "signature": "nonempty",
                        "bounds": "inside_actor_region",
                        "centroid": "normalized_coordinate",
                    },
                    {
                        "sample_index": index,
                        "visible_pixels": pixels,
                        "signature": signature,
                        "bounds": bounds,
                        "centroid": actor.get("centroid"),
                    },
                )
            )
            continue
        visible_sample_count += 1
        actor_signatures.append(signature)
        actor_centroids.append(centroid)

    if len(timestamps) == expected_count and any(
        later <= earlier
        for earlier, later in zip(timestamps, timestamps[1:], strict=False)
    ):
        failures.append(
            _failure(
                "actor_timestamps_not_strictly_increasing",
                {"time_ms": "strictly_increasing"},
                {"time_ms": timestamps},
            )
        )

    if visible_sample_count == expected_count:
        actor_changed = len(set(actor_signatures)) > 1 or len(set(actor_centroids)) > 1
        if not actor_changed:
            failures.append(
                _failure(
                    "actor_trajectory_static",
                    {
                        "actor_signature_or_centroid_changes": True,
                        "whole_canvas_or_frame_counter_sufficient": False,
                    },
                    {
                        "actor_signatures": actor_signatures,
                        "actor_centroids": [list(value) for value in actor_centroids],
                    },
                )
            )

    return {
        "passed": not failures,
        "check_count": 3,
        "failures": failures,
        "evidence": {
            "actor_region": region,
            "sample_count": len(samples),
            "visible_sample_count": visible_sample_count,
            "actor_signatures": actor_signatures,
            "actor_centroids": [list(value) for value in actor_centroids],
            "frame_counts": [sample.get("frame_count") for sample in samples],
            "canvas_signatures": [sample.get("canvas_signature") for sample in samples],
        },
    }
