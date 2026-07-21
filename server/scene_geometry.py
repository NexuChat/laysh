from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any

SCENE_GEOMETRY_CONTRACT_VERSION = "1.0"
SUPPORTED_GEOMETRY_TYPES = frozenset({"circle"})
OVERLAP_POLICIES = frozenset({"forbid", "allow", "scientific_occlusion"})
CONTACT_POLICIES = frozenset({"forbid", "allow", "required"})
CLIPPING_POLICIES = frozenset({"forbid", "allow"})

_ROOT_FIELDS = frozenset(
    {"schemaVersion", "phase", "viewport", "state", "objects", "relations"}
)
_VIEWPORT_FIELDS = frozenset({"width", "height", "safeInset"})
_STATE_FIELDS = frozenset({"id", "timeMs"})
_OBJECT_FIELDS = frozenset({"id", "scientific", "geometry", "clippingPolicy"})
_CIRCLE_FIELDS = frozenset({"type", "cx", "cy", "radius"})
_RELATION_FIELDS = frozenset(
    {"objects", "overlapPolicy", "contactPolicy", "minimumClearance"}
)
_PHASES = frozenset({"candidate", "clamped", "post_fit"})
_CONTACT_TOLERANCE_PX = 1e-6


@dataclass(frozen=True, slots=True)
class GeometryValidationResult:
    passed: bool
    check_count: int
    failures: list[dict[str, Any]]
    minimum_clearance_px: float | None


def _failure(
    code: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    sample_index: int,
    state: object = None,
) -> dict[str, Any]:
    return {
        "gate": "scene_geometry",
        "code": code,
        "expected": expected,
        "actual": actual,
        "sample_index": sample_index,
        "state": state,
    }


def _unknown_fields(value: object, allowed: frozenset[str]) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted(str(key) for key in value if key not in allowed)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _contract_failure(
    failures: list[dict[str, Any]],
    *,
    sample_index: int,
    state: object,
    code: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> None:
    failures.append(
        _failure(
            code,
            expected,
            actual,
            sample_index=sample_index,
            state=state,
        )
    )


def _validated_sample(
    sample: object,
    *,
    sample_index: int,
    failures: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]] | None:
    if not isinstance(sample, dict):
        _contract_failure(
            failures,
            sample_index=sample_index,
            state=None,
            code="scene_contract_invalid_type",
            expected={"sample": "object"},
            actual={"sample_type": type(sample).__name__},
        )
        return None
    state = sample.get("state")
    unknown = _unknown_fields(sample, _ROOT_FIELDS)
    if unknown:
        _contract_failure(
            failures,
            sample_index=sample_index,
            state=state,
            code="scene_contract_unknown_field",
            expected={"allowed_fields": sorted(_ROOT_FIELDS)},
            actual={"fields": unknown},
        )
        return None
    if sample.get("schemaVersion") != SCENE_GEOMETRY_CONTRACT_VERSION:
        _contract_failure(
            failures,
            sample_index=sample_index,
            state=state,
            code="scene_contract_version_mismatch",
            expected={"schemaVersion": SCENE_GEOMETRY_CONTRACT_VERSION},
            actual={"schemaVersion": sample.get("schemaVersion")},
        )
        return None
    if sample.get("phase") not in _PHASES:
        _contract_failure(
            failures,
            sample_index=sample_index,
            state=state,
            code="scene_contract_invalid_phase",
            expected={"phase": sorted(_PHASES)},
            actual={"phase": sample.get("phase")},
        )
        return None
    if not isinstance(state, dict) or _unknown_fields(state, _STATE_FIELDS):
        _contract_failure(
            failures,
            sample_index=sample_index,
            state=state,
            code="scene_contract_invalid_state",
            expected={"fields": sorted(_STATE_FIELDS)},
            actual={"state": state},
        )
        return None

    viewport = sample.get("viewport")
    if not isinstance(viewport, dict) or _unknown_fields(viewport, _VIEWPORT_FIELDS):
        _contract_failure(
            failures,
            sample_index=sample_index,
            state=state,
            code="scene_contract_invalid_viewport",
            expected={"fields": sorted(_VIEWPORT_FIELDS)},
            actual={"viewport": viewport},
        )
        return None
    width = _finite_number(viewport.get("width"))
    height = _finite_number(viewport.get("height"))
    safe_inset = _finite_number(viewport.get("safeInset", 0))
    if (
        width is None
        or height is None
        or safe_inset is None
        or width <= 0
        or height <= 0
        or safe_inset < 0
        or safe_inset * 2 >= min(width, height)
    ):
        _contract_failure(
            failures,
            sample_index=sample_index,
            state=state,
            code="scene_contract_invalid_viewport",
            expected={"finite_positive_bounds": True, "safeInset": ">= 0 and inside viewport"},
            actual={"viewport": viewport},
        )
        return None

    objects = sample.get("objects")
    if not isinstance(objects, list) or not objects:
        _contract_failure(
            failures,
            sample_index=sample_index,
            state=state,
            code="scene_contract_objects_missing",
            expected={"objects": "nonempty_array"},
            actual={"objects": objects},
        )
        return None
    objects_by_id: dict[str, dict[str, Any]] = {}
    for item in objects:
        if not isinstance(item, dict) or _unknown_fields(item, _OBJECT_FIELDS):
            _contract_failure(
                failures,
                sample_index=sample_index,
                state=state,
                code="scene_contract_invalid_object",
                expected={"fields": sorted(_OBJECT_FIELDS)},
                actual={"object": item},
            )
            continue
        object_id = item.get("id")
        scientific = item.get("scientific", True)
        clipping_policy = item.get("clippingPolicy", "forbid")
        geometry = item.get("geometry")
        if (
            not isinstance(object_id, str)
            or not object_id
            or object_id in objects_by_id
            or not isinstance(scientific, bool)
            or clipping_policy not in CLIPPING_POLICIES
            or not isinstance(geometry, dict)
        ):
            _contract_failure(
                failures,
                sample_index=sample_index,
                state=state,
                code="scene_contract_invalid_object",
                expected={
                    "unique_nonempty_id": True,
                    "scientific": "boolean",
                    "clippingPolicy": sorted(CLIPPING_POLICIES),
                    "geometry": "object",
                },
                actual={"object": item},
            )
            continue
        geometry_type = geometry.get("type")
        if geometry_type not in SUPPORTED_GEOMETRY_TYPES:
            if scientific:
                _contract_failure(
                    failures,
                    sample_index=sample_index,
                    state=state,
                    code="unsupported_scientific_geometry",
                    expected={"geometryTypes": sorted(SUPPORTED_GEOMETRY_TYPES)},
                    actual={"object": object_id, "geometryType": geometry_type},
                )
            continue
        values = {
            key: _finite_number(geometry.get(key)) for key in ("cx", "cy", "radius")
        }
        if (
            _unknown_fields(geometry, _CIRCLE_FIELDS)
            or any(value is None for value in values.values())
            or values["radius"] <= 0
        ):
            _contract_failure(
                failures,
                sample_index=sample_index,
                state=state,
                code="invalid_circle_geometry",
                expected={"fields": sorted(_CIRCLE_FIELDS), "finite_positive_radius": True},
                actual={"object": object_id, "geometry": geometry},
            )
            continue
        objects_by_id[object_id] = {
            **item,
            "scientific": scientific,
            "clippingPolicy": clipping_policy,
            "geometry": {"type": "circle", **values},
        }

    relations = sample.get("relations")
    if not isinstance(relations, list):
        _contract_failure(
            failures,
            sample_index=sample_index,
            state=state,
            code="scene_contract_invalid_relations",
            expected={"relations": "array"},
            actual={"relations": relations},
        )
        return None
    relations_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for relation in relations:
        if not isinstance(relation, dict) or _unknown_fields(relation, _RELATION_FIELDS):
            _contract_failure(
                failures,
                sample_index=sample_index,
                state=state,
                code="scene_contract_invalid_relation",
                expected={"fields": sorted(_RELATION_FIELDS)},
                actual={"relation": relation},
            )
            continue
        pair_value = relation.get("objects")
        overlap_policy = relation.get("overlapPolicy", "forbid")
        contact_policy = relation.get("contactPolicy", "forbid")
        minimum_clearance = _finite_number(relation.get("minimumClearance", 0))
        if not isinstance(pair_value, list) or len(pair_value) != 2:
            pair: tuple[str, str] | None = None
        elif not all(isinstance(value, str) for value in pair_value):
            pair = None
        else:
            pair = tuple(sorted(pair_value))
        if (
            pair is None
            or pair[0] == pair[1]
            or pair in relations_by_pair
            or any(object_id not in objects_by_id for object_id in pair)
            or overlap_policy not in OVERLAP_POLICIES
            or contact_policy not in CONTACT_POLICIES
            or minimum_clearance is None
            or minimum_clearance < 0
            or (contact_policy == "required" and minimum_clearance != 0)
            or (overlap_policy != "forbid" and minimum_clearance != 0)
        ):
            _contract_failure(
                failures,
                sample_index=sample_index,
                state=state,
                code="scene_contract_invalid_relation",
                expected={
                    "objects": "two distinct existing object ids",
                    "overlapPolicy": sorted(OVERLAP_POLICIES),
                    "contactPolicy": sorted(CONTACT_POLICIES),
                    "minimumClearance": "finite nonnegative and policy-compatible",
                },
                actual={"relation": relation},
            )
            continue
        relations_by_pair[pair] = {
            "objects": list(pair),
            "overlapPolicy": overlap_policy,
            "contactPolicy": contact_policy,
            "minimumClearance": minimum_clearance,
        }

    if failures and any(failure["sample_index"] == sample_index for failure in failures):
        return None
    return (
        {
            **sample,
            "viewport": {"width": width, "height": height, "safeInset": safe_inset},
        },
        objects_by_id,
        relations_by_pair,
    )


def validate_scene_geometry(samples: object) -> GeometryValidationResult:
    """Validate closed scene samples without lesson-specific knowledge.

    Scientific circles and undeclared relations default to fail-safe policies.
    Unsupported scientific geometry never passes silently.
    """

    failures: list[dict[str, Any]] = []
    check_count = 0
    minimum_clearance = math.inf
    if not isinstance(samples, list) or not samples:
        return GeometryValidationResult(
            passed=False,
            check_count=1,
            failures=[
                _failure(
                    "scene_samples_missing",
                    {"samples": "nonempty_array"},
                    {"samples": samples},
                    sample_index=0,
                )
            ],
            minimum_clearance_px=None,
        )

    for sample_index, original_sample in enumerate(samples):
        check_count += 1
        validated = _validated_sample(
            original_sample,
            sample_index=sample_index,
            failures=failures,
        )
        if validated is None:
            continue
        sample, objects_by_id, relations_by_pair = validated
        state = sample["state"]
        viewport = sample["viewport"]
        for object_id, item in objects_by_id.items():
            check_count += 1
            geometry = item["geometry"]
            radius = geometry["radius"]
            inside = (
                geometry["cx"] - radius >= viewport["safeInset"]
                and geometry["cx"] + radius <= viewport["width"] - viewport["safeInset"]
                and geometry["cy"] - radius >= viewport["safeInset"]
                and geometry["cy"] + radius <= viewport["height"] - viewport["safeInset"]
            )
            if not inside and item["clippingPolicy"] == "forbid":
                failures.append(
                    _failure(
                        "undeclared_clipping",
                        {"clippingPolicy": "forbid", "insideSafeViewport": True},
                        {
                            "object": object_id,
                            "geometry": geometry,
                            "viewport": viewport,
                        },
                        sample_index=sample_index,
                        state=state,
                    )
                )

        for left_id, right_id in combinations(sorted(objects_by_id), 2):
            check_count += 1
            left = objects_by_id[left_id]["geometry"]
            right = objects_by_id[right_id]["geometry"]
            center_distance = math.hypot(left["cx"] - right["cx"], left["cy"] - right["cy"])
            clearance = center_distance - left["radius"] - right["radius"]
            minimum_clearance = min(minimum_clearance, clearance)
            relation = relations_by_pair.get(
                (left_id, right_id),
                {
                    "objects": [left_id, right_id],
                    "overlapPolicy": "forbid",
                    "contactPolicy": "forbid",
                    "minimumClearance": 0.0,
                },
            )
            actual = {
                "objects": [left_id, right_id],
                "clearancePx": round(clearance, 6),
                "overlapPx": round(max(0.0, -clearance), 6),
            }
            if clearance < -_CONTACT_TOLERANCE_PX:
                if relation["overlapPolicy"] == "forbid":
                    failures.append(
                        _failure(
                            "undeclared_overlap",
                            {"overlapPolicy": "forbid", "minimumClearance": 0},
                            actual,
                            sample_index=sample_index,
                            state=state,
                        )
                    )
                continue
            touching = abs(clearance) <= _CONTACT_TOLERANCE_PX
            if touching and relation["contactPolicy"] == "forbid":
                failures.append(
                    _failure(
                        "undeclared_contact",
                        {"contactPolicy": "forbid"},
                        actual,
                        sample_index=sample_index,
                        state=state,
                    )
                )
                continue
            if not touching and relation["contactPolicy"] == "required":
                failures.append(
                    _failure(
                        "required_contact_missing",
                        {"contactPolicy": "required", "clearancePx": 0},
                        actual,
                        sample_index=sample_index,
                        state=state,
                    )
                )
                continue
            required_clearance = relation["minimumClearance"]
            if clearance + _CONTACT_TOLERANCE_PX < required_clearance:
                failures.append(
                    _failure(
                        "minimum_clearance_violated",
                        {"minimumClearance": required_clearance},
                        actual,
                        sample_index=sample_index,
                        state=state,
                    )
                )

    return GeometryValidationResult(
        passed=not failures,
        check_count=check_count,
        failures=failures,
        minimum_clearance_px=(
            round(minimum_clearance, 6) if math.isfinite(minimum_clearance) else None
        ),
    )
