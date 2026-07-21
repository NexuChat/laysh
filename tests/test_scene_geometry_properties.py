from __future__ import annotations

from server.scene_geometry import validate_scene_geometry


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
        "clippingPolicy": "forbid",
        "geometry": {"type": "circle", "cx": x, "cy": y, "radius": radius},
        **overrides,
    }


def _relation(
    left: str,
    right: str,
    *,
    overlap: str = "forbid",
    contact: str = "forbid",
    clearance: float = 0,
) -> dict[str, object]:
    return {
        "objects": [left, right],
        "overlapPolicy": overlap,
        "contactPolicy": contact,
        "minimumClearance": clearance,
    }


def _sample(
    objects: list[dict[str, object]],
    relations: list[dict[str, object]] | None = None,
    *,
    phase: str = "post_fit",
    width: float = 320,
    height: float = 180,
    safe_inset: float = 4,
    state_id: str = "steady",
    time_ms: float = 0,
) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "phase": phase,
        "viewport": {
            "width": width,
            "height": height,
            "safeInset": safe_inset,
        },
        "state": {"id": state_id, "timeMs": time_ms},
        "objects": objects,
        "relations": relations or [],
    }


def _clear_pair() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    objects = [_circle("actor", 80, 90, 20), _circle("source", 240, 90, 20)]
    return objects, [_relation("actor", "source", clearance=8)]


def test_clamp_alone_cannot_replace_recomputed_post_fit_evidence():
    objects, relations = _clear_pair()

    report = validate_scene_geometry(
        [
            _sample(objects, relations, phase="candidate"),
            _sample(objects, relations, phase="clamped"),
        ]
    )

    assert report.passed is False
    failure = next(
        item for item in report.failures if item["code"] == "post_fit_scene_sample_missing"
    )
    assert failure["expected"] == {"phase": "post_fit"}
    assert failure["actual"]["phases"] == ["candidate", "clamped"]
    assert failure["actual"]["group"] == {
        "viewport": {"width": 320.0, "height": 180.0, "safeInset": 4.0},
        "state": {"id": "steady", "timeMs": 0},
    }


def test_post_fit_evidence_must_follow_the_last_fit_or_clamp():
    objects, relations = _clear_pair()

    report = validate_scene_geometry(
        [
            _sample(objects, relations, phase="post_fit"),
            _sample(objects, relations, phase="clamped"),
        ]
    )

    assert report.passed is False
    failure = next(
        item for item in report.failures if item["code"] == "post_fit_scene_sample_out_of_order"
    )
    assert failure["expected"] == {"post_fit_after_last_layout_sample": True}
    assert failure["actual"] == {
        "phases": ["post_fit", "clamped"],
        "last_layout_sample_index": 1,
        "last_post_fit_sample_index": 0,
    }


def test_phase_group_identity_requires_a_closed_finite_state():
    objects, relations = _clear_pair()
    invalid_states = (
        {"id": "", "timeMs": 0},
        {"id": "steady", "timeMs": -1},
        {"id": "steady", "timeMs": float("inf")},
    )

    for invalid_state in invalid_states:
        sample = _sample(objects, relations)
        sample["state"] = invalid_state

        report = validate_scene_geometry([sample])

        assert report.passed is False
        assert report.failures[0]["code"] == "scene_contract_invalid_state"
        assert report.failures[0]["expected"] == {
            "id": "nonempty_string",
            "timeMs": "finite_nonnegative",
        }


def test_empty_scene_sample_collection_fails_closed():
    report = validate_scene_geometry([])

    assert report.passed is False
    assert report.check_count == 1
    assert report.failures[0]["code"] == "scene_samples_missing"


def test_non_object_scene_sample_fails_closed_with_its_actual_type():
    report = validate_scene_geometry(["not-a-scene"])

    assert report.passed is False
    assert report.failures[0]["code"] == "scene_contract_invalid_type"
    assert report.failures[0]["expected"] == {"sample": "object"}
    assert report.failures[0]["actual"] == {"sample_type": "str"}


def test_post_fit_recompute_can_replace_an_invalid_candidate_with_a_safe_alternative():
    colliding = [_circle("actor", 140, 90, 24), _circle("source", 160, 90, 24)]
    clear, relations = _clear_pair()

    report = validate_scene_geometry(
        [
            _sample(colliding, relations, phase="candidate"),
            _sample(colliding, relations, phase="clamped"),
            _sample(clear, relations, phase="post_fit"),
        ]
    )

    assert report.passed is True
    assert report.failures == []
    assert report.minimum_clearance_px == 120.0


def test_post_fit_recompute_is_rejected_when_clamping_introduces_a_collision():
    clear, relations = _clear_pair()
    colliding = [_circle("actor", 140, 90, 24), _circle("source", 160, 90, 24)]

    report = validate_scene_geometry(
        [
            _sample(clear, relations, phase="candidate"),
            _sample(colliding, relations, phase="clamped"),
            _sample(colliding, relations, phase="post_fit"),
        ]
    )

    assert report.passed is False
    collision = next(item for item in report.failures if item["code"] == "undeclared_overlap")
    assert collision["sample_index"] == 2
    assert collision["actual"]["overlapPx"] == 28.0


def _responsive_viewports() -> list[tuple[int, int]]:
    critical = [
        (240, 600),
        (320, 568),
        (390, 844),
        (844, 390),
        (768, 1024),
        (1440, 900),
        (1920, 1080),
    ]
    generated = [
        (240 + (sample_index * 137) % 1681, 180 + (sample_index * 211) % 1021)
        for sample_index in range(32)
    ]
    return critical + generated


def _responsive_sample(width: int, height: int, sample_index: int) -> dict[str, object]:
    radius = max(6.0, min(width, height) * 0.04)
    left_x = max(8 + radius, width * 0.24)
    right_x = min(width - 8 - radius, width * 0.76)
    objects = [
        _circle("actor", left_x, height * 0.5, radius),
        _circle("source", right_x, height * 0.5, radius),
    ]
    return _sample(
        objects,
        [_relation("actor", "source", clearance=4)],
        width=width,
        height=height,
        safe_inset=8,
        state_id=f"viewport-{sample_index}",
    )


def test_responsive_generated_viewport_matrix_passes_all_post_fit_constraints():
    samples = [
        _responsive_sample(width, height, sample_index)
        for sample_index, (width, height) in enumerate(_responsive_viewports())
    ]

    report = validate_scene_geometry(samples)

    assert report.passed is True
    assert report.failures == []
    assert report.check_count == len(samples) * 4
    assert report.minimum_clearance_px is not None
    assert report.minimum_clearance_px >= 4


def test_responsive_matrix_rejects_one_generated_breakpoint_collision():
    viewports = _responsive_viewports()
    samples = [
        _responsive_sample(width, height, sample_index)
        for sample_index, (width, height) in enumerate(viewports)
    ]
    defect_index = len(samples) // 2
    defective = samples[defect_index]
    geometry = defective["objects"][1]["geometry"]
    geometry["cx"] = defective["objects"][0]["geometry"]["cx"]

    report = validate_scene_geometry(samples)

    assert report.passed is False
    collision = next(item for item in report.failures if item["code"] == "undeclared_overlap")
    assert collision["sample_index"] == defect_index
    assert collision["state"]["id"] == f"viewport-{defect_index}"


def test_dynamic_collision_is_detected_at_the_exact_temporal_sample():
    samples = []
    for step in range(11):
        actor_x = 48 + step * 22
        samples.append(
            _sample(
                [_circle("actor", actor_x, 90, 12), _circle("source", 158, 90, 12)],
                [_relation("actor", "source")],
                state_id="trajectory",
                time_ms=step * 80,
            )
        )

    report = validate_scene_geometry(samples)

    assert report.passed is False
    collisions = [failure for failure in report.failures if failure["code"] == "undeclared_overlap"]
    assert [failure["sample_index"] for failure in collisions] == [4, 5, 6]
    assert [failure["state"]["timeMs"] for failure in collisions] == [320, 400, 480]


def test_unsupported_scientific_geometry_fails_closed_even_before_post_fit():
    unsupported = {
        "id": "actor",
        "scientific": True,
        "clippingPolicy": "forbid",
        "geometry": {"type": "implicit_surface", "radius": 20},
    }
    safe = [_circle("actor", 80, 90, 20), _circle("source", 240, 90, 20)]

    report = validate_scene_geometry(
        [
            _sample([unsupported], phase="candidate"),
            _sample(safe, [_relation("actor", "source")], phase="post_fit"),
        ]
    )

    assert report.passed is False
    failure = next(
        item for item in report.failures if item["code"] == "unsupported_scientific_geometry"
    )
    assert failure["sample_index"] == 0
    assert failure["actual"] == {
        "object": "actor",
        "geometryType": "implicit_surface",
    }


def test_declared_scientific_occlusion_and_required_contact_remain_valid():
    report = validate_scene_geometry(
        [
            _sample(
                [
                    _circle("actor", 100, 90, 30),
                    _circle("occluder", 120, 90, 20),
                    _circle("surface", 220, 90, 20),
                    _circle("probe", 260, 90, 20),
                ],
                [
                    _relation(
                        "actor",
                        "occluder",
                        overlap="scientific_occlusion",
                        contact="allow",
                    ),
                    _relation("surface", "probe", contact="required"),
                    _relation("actor", "surface"),
                    _relation("actor", "probe"),
                    _relation("occluder", "surface"),
                    _relation("occluder", "probe"),
                ],
            )
        ]
    )

    assert report.passed is True
    assert report.failures == []
    assert report.minimum_clearance_px == -30.0
