from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


def _circle(
    object_id: str,
    x: float,
    y: float,
    radius: float,
    **overrides: object,
) -> dict[str, object]:
    return {
        "id": object_id,
        "scientific": True,
        "geometry": {"type": "circle", "cx": x, "cy": y, "radius": radius},
        **overrides,
    }


def _sample(
    objects: list[dict[str, object]],
    relations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "phase": "post_fit",
        "viewport": {"width": 320, "height": 180, "safeInset": 4},
        "state": {"id": "initial", "timeMs": 0},
        "objects": objects,
        "relations": relations or [],
    }


def test_missing_pair_policy_defaults_to_forbid_overlap():
    from server.scene_geometry import validate_scene_geometry

    report = validate_scene_geometry(
        [_sample([_circle("source", 80, 90, 30), _circle("body", 105, 90, 20)])]
    )

    assert report.passed is False
    failure = next(item for item in report.failures if item["code"] == "undeclared_overlap")
    assert failure["actual"]["objects"] == ["body", "source"]
    assert failure["expected"]["overlapPolicy"] == "forbid"


def test_explicit_scientific_occlusion_and_required_contact_are_supported():
    from server.scene_geometry import validate_scene_geometry

    occlusion = _sample(
        [_circle("observer", 80, 90, 30), _circle("occluder", 105, 90, 20)],
        [
            {
                "objects": ["observer", "occluder"],
                "overlapPolicy": "scientific_occlusion",
                "contactPolicy": "allow",
                "minimumClearance": 0,
            }
        ],
    )
    contact = _sample(
        [_circle("surface", 80, 90, 20), _circle("body", 120, 90, 20)],
        [
            {
                "objects": ["surface", "body"],
                "overlapPolicy": "forbid",
                "contactPolicy": "required",
                "minimumClearance": 0,
            }
        ],
    )

    report = validate_scene_geometry([occlusion, contact])

    assert report.passed is True
    assert report.failures == []
    assert report.minimum_clearance_px == -25.0


def test_clipping_is_forbidden_by_default_but_can_be_declared():
    from server.scene_geometry import validate_scene_geometry

    clipped = _circle("body", 10, 90, 20)
    forbidden = validate_scene_geometry([_sample([clipped])])
    allowed = validate_scene_geometry(
        [_sample([{**clipped, "clippingPolicy": "allow"}])]
    )

    assert forbidden.passed is False
    assert forbidden.failures[0]["code"] == "undeclared_clipping"
    assert allowed.passed is True


def test_unknown_fields_and_unsupported_scientific_geometry_fail_closed():
    from server.scene_geometry import validate_scene_geometry

    unknown = _sample([_circle("body", 80, 90, 20)])
    unknown["lessonId"] = "reference_name"
    unsupported = _sample(
        [
            {
                "id": "body",
                "scientific": True,
                "geometry": {"type": "freeform_path", "points": [[0, 0], [1, 1]]},
            }
        ]
    )

    unknown_report = validate_scene_geometry([unknown])
    unsupported_report = validate_scene_geometry([unsupported])

    assert unknown_report.passed is False
    assert unknown_report.failures[0]["code"] == "scene_contract_unknown_field"
    assert unknown_report.failures[0]["actual"]["fields"] == ["lessonId"]
    assert unsupported_report.passed is False
    assert unsupported_report.failures[0]["code"] == "unsupported_scientific_geometry"


def test_minimum_clearance_and_contact_policies_are_independent():
    from server.scene_geometry import validate_scene_geometry

    sample = _sample(
        [_circle("left", 80, 90, 20), _circle("right", 123, 90, 20)],
        [
            {
                "objects": ["left", "right"],
                "overlapPolicy": "forbid",
                "contactPolicy": "forbid",
                "minimumClearance": 8,
            }
        ],
    )

    report = validate_scene_geometry([sample])

    assert report.passed is False
    failure = report.failures[0]
    assert failure["code"] == "minimum_clearance_violated"
    assert failure["expected"]["minimumClearance"] == 8
    assert failure["actual"]["clearancePx"] == 3.0


def test_scene_geometry_schema_is_versioned_and_closed_at_every_object():
    schema_path = Path(__file__).parents[1] / "server" / "schemas" / "scene_geometry.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    assert schema["$id"].endswith("scene-geometry-1.0.json")
    Draft202012Validator(schema).validate(
        [_sample([_circle("left", 80, 90, 20), _circle("right", 140, 90, 20)])]
    )
