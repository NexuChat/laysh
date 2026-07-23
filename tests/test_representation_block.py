from __future__ import annotations

import json
import re
from copy import deepcopy

import pytest
from jsonschema import ValidationError

UNDERSTANDING = {
    "safe": True,
    "unsafe_category": None,
    "simulatable": True,
    "reason_code": "ok",
    "lang": "en",
    "canonical_intent": "synthetic_response",
    "domain": "synthetic",
    "title": "Synthetic response",
    "tldr": "A generic output changes with a generic input.",
    "key_formula": "r = p",
    "learning_objective": "Connect a declared output to visible evidence.",
    "primary_parameter": {
        "id": "input_value",
        "label": "Input",
        "unit": "u",
        "min": 0,
        "max": 1,
        "default": 0.5,
        "step": 0.1,
    },
    "secondary_parameter": None,
    "prediction": {
        "prompt": "What changes as the input increases?",
        "choices": ["The response increases", "The response decreases"],
    },
    "misconception": (
        "Correction: the visible response is not independent of the declared output."
    ),
    "explanation_prompt": "Explain the visible response.",
    "transfer_prompt": "Predict the response at another input.",
    "module_spec": {
        "outputs": ["response"],
        "actor": "visible_body",
        "action": "rotates",
    },
    "checks": [
        {
            "id": "minimum_response",
            "kind": "numeric",
            "inputs": [{"name": "input_value", "value": 0}],
            "output": "response",
            "expected": 0,
            "tolerance": 0.001,
            "unit": "u",
        },
        {
            "id": "maximum_response",
            "kind": "numeric",
            "inputs": [{"name": "input_value", "value": 1}],
            "output": "response",
            "expected": 1,
            "tolerance": 0.001,
            "unit": "u",
        },
    ],
    "suggestions": [],
}

PHYSICS_FRAGMENT = {
    "physics_expressions": [{"name": "response", "expression": "input_value"}],
    "output_names": ["response"],
    "brief_summary": "Maps a generic input to a generic output.",
    "assumptions": ["The synthetic relation is linear."],
}

SCIENTIFIC_CIRCLE = {
    "kind": "circle",
    "id": "response_actor",
    "scientific": True,
    "clipping_policy": "forbid",
    "cx": "width * (0.25 + output_response * 0.5)",
    "cy": "height / 2",
    "radius": "min_dim * 0.12",
    "fill_color": "#1A2B3C",
    "fill_alt_color": "#4D5E6F",
    "stroke_color": "#FFFFFF",
    "line_width": "2",
    "opacity": "1",
}

REPRESENTATION = {
    "scene_pattern": "world_only",
    "actor_archetype": "body",
    "proof_channels": [
        {
            "output_name": "response",
            "carrier": "actor",
            "channel": "x",
        }
    ],
    "motion_model": "parameter_driven",
}


def _visual_fragment() -> dict:
    return {
        "representation": deepcopy(REPRESENTATION),
        "background": {
            "top_color": "#07111F",
            "bottom_color": "#10243A",
        },
        "commands": [deepcopy(SCIENTIFIC_CIRCLE)],
        "relations": [],
        "causal_response": {
            "actor_id": "response_actor",
            "output_name": "response",
            "channel": "x",
            "relation": "direct",
            "temporal_mode": "parameter_driven",
        },
    }


def test_valid_representation_is_accepted_and_embedded_in_artifact_spec() -> None:
    from server.fragment_generation import assemble_fragments, validate_visual_fragment
    from server.verify import verify_module_with_node

    visual = _visual_fragment()

    assert validate_visual_fragment(visual, deepcopy(UNDERSTANDING)) == visual
    module_output = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT),
        visual,
        deepcopy(UNDERSTANDING),
    )

    source = module_output["module_js"]
    embedded_match = re.search(
        r"const spec = Object\.freeze\((\{.*?\})\);",
        source,
    )
    assert embedded_match is not None
    assert json.loads(embedded_match.group(1)) == {
        "representation": REPRESENTATION,
    }
    assert 'Object.defineProperty(simulation,"spec"' in source
    assert verify_module_with_node(source, deepcopy(UNDERSTANDING))["passed"] is True


@pytest.mark.parametrize(
    ("path", "value"),
    [
        pytest.param(("scene_pattern",), "invented_scene", id="scene-pattern"),
        pytest.param(("actor_archetype",), "invented_actor", id="actor-archetype"),
        pytest.param(
            ("proof_channels", 0, "carrier"),
            "invented_carrier",
            id="proof-carrier",
        ),
        pytest.param(
            ("proof_channels", 0, "channel"),
            "invented_channel",
            id="proof-channel",
        ),
        pytest.param(("motion_model",), "invented_motion", id="motion-model"),
    ],
)
def test_representation_enum_violations_are_rejected(
    path: tuple[str | int, ...],
    value: str,
) -> None:
    from server.fragment_generation import validate_visual_fragment

    visual = _visual_fragment()
    target: dict | list = visual["representation"]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        validate_visual_fragment(visual, deepcopy(UNDERSTANDING))


def test_time_driven_is_rejected_with_phase_a2_failure_code() -> None:
    from server.fragment_generation import fragment_failure_code, validate_visual_fragment
    from server.schemas import ContractError

    visual = _visual_fragment()
    visual["representation"]["motion_model"] = "time_driven"

    with pytest.raises(ContractError) as captured:
        validate_visual_fragment(visual, deepcopy(UNDERSTANDING))

    assert fragment_failure_code(captured.value) == "representation_time_driven_deferred"


def test_archetype_must_match_emitted_scientific_command_types() -> None:
    from server.fragment_generation import fragment_failure_code, validate_visual_fragment
    from server.schemas import ContractError

    visual = _visual_fragment()
    visual["representation"]["actor_archetype"] = "elongated_body"

    with pytest.raises(ContractError) as captured:
        validate_visual_fragment(visual, deepcopy(UNDERSTANDING))

    assert (
        fragment_failure_code(captured.value)
        == "representation_archetype_command_mismatch"
    )


@pytest.mark.parametrize(
    "actor_archetype",
    ["ray_bundle", "wave_medium", "particle_flow"],
)
def test_phase_a2_archetypes_are_rejected_until_their_primitives_exist(
    actor_archetype: str,
) -> None:
    from server.fragment_generation import fragment_failure_code, validate_visual_fragment
    from server.schemas import ContractError

    visual = _visual_fragment()
    visual["representation"]["actor_archetype"] = actor_archetype

    with pytest.raises(ContractError) as captured:
        validate_visual_fragment(visual, deepcopy(UNDERSTANDING))

    assert (
        fragment_failure_code(captured.value)
        == "representation_archetype_not_emittable"
    )


def test_actor_proof_channel_requires_matching_scientific_output_binding() -> None:
    from server.fragment_generation import fragment_failure_code, validate_visual_fragment
    from server.schemas import ContractError

    visual = _visual_fragment()
    visual["representation"]["proof_channels"][0]["channel"] = "opacity"

    with pytest.raises(ContractError) as captured:
        validate_visual_fragment(visual, deepcopy(UNDERSTANDING))

    assert (
        fragment_failure_code(captured.value)
        == "representation_actor_proof_unbacked"
    )


def test_graph_proof_channel_requires_world_plus_graph_scene() -> None:
    from server.fragment_generation import fragment_failure_code, validate_visual_fragment
    from server.schemas import ContractError

    visual = _visual_fragment()
    visual["representation"]["proof_channels"][0]["carrier"] = "graph"

    with pytest.raises(ContractError) as captured:
        validate_visual_fragment(visual, deepcopy(UNDERSTANDING))

    assert (
        fragment_failure_code(captured.value)
        == "representation_graph_scene_required"
    )


def test_proof_channel_output_must_be_declared() -> None:
    from server.fragment_generation import fragment_failure_code, validate_visual_fragment
    from server.schemas import ContractError

    visual = _visual_fragment()
    visual["representation"]["proof_channels"][0]["carrier"] = "readout"
    visual["representation"]["proof_channels"][0]["output_name"] = "invented_response"

    with pytest.raises(ContractError) as captured:
        validate_visual_fragment(visual, deepcopy(UNDERSTANDING))

    assert (
        fragment_failure_code(captured.value)
        == "representation_output_undeclared"
    )


def test_every_representation_failure_code_has_actionable_retry_guidance() -> None:
    from server.codex_backend import FRAGMENT_RETRY_HINTS

    expected_codes = {
        "representation_time_driven_deferred",
        "representation_archetype_not_emittable",
        "representation_archetype_command_mismatch",
        "representation_actor_proof_unbacked",
        "representation_graph_scene_required",
        "representation_output_undeclared",
    }

    assert expected_codes <= set(FRAGMENT_RETRY_HINTS)
    for code in expected_codes:
        assert len(FRAGMENT_RETRY_HINTS[code].split()) >= 6
