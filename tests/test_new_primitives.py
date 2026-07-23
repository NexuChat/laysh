from __future__ import annotations

import json
import subprocess
from copy import deepcopy

import pytest
from jsonschema import ValidationError

UNDERSTANDING = {
    "safe": True,
    "unsafe_category": None,
    "simulatable": True,
    "reason_code": "ok",
    "lang": "en",
    "canonical_intent": "synthetic_motion",
    "domain": "synthetic",
    "title": "Synthetic motion",
    "tldr": "A declared response changes with a controlled input.",
    "key_formula": "r = p²",
    "learning_objective": "Connect compiled physics to visible geometry.",
    "primary_parameter": {
        "id": "input_value",
        "label": "Input",
        "unit": "u",
        "min": 0,
        "max": 1,
        "default": 0.5,
        "step": 0.125,
    },
    "secondary_parameter": None,
    "prediction": {
        "prompt": "What changes as the input increases?",
        "choices": ["The response increases", "The response decreases"],
    },
    "misconception": None,
    "explanation_prompt": "Explain the visible response.",
    "transfer_prompt": "Predict the response at another input.",
    "module_spec": {
        "outputs": ["response"],
        "actor": "visible_body",
        "action": "propagates",
    },
    "checks": [
        {
            "id": "response_minimum",
            "kind": "numeric",
            "inputs": [{"name": "input_value", "value": 0}],
            "output": "response",
            "expected": 0,
            "tolerance": 0.001,
            "unit": "u",
        },
        {
            "id": "response_midpoint",
            "kind": "numeric",
            "inputs": [{"name": "input_value", "value": 0.5}],
            "output": "response",
            "expected": 0.25,
            "tolerance": 0.001,
            "unit": "u",
        },
        {
            "id": "response_maximum",
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
    "physics_expressions": [
        {"name": "response", "expression": "input_value * input_value"}
    ],
    "output_names": ["response"],
    "brief_summary": "Computes a synthetic quadratic response.",
    "assumptions": ["The response is deterministic."],
}

BACKGROUND = {"top_color": "#07111F", "bottom_color": "#10243A"}

CIRCLE = {
    "kind": "circle",
    "id": "reference_actor",
    "scientific": True,
    "clipping_policy": "forbid",
    "cx": "width * (0.2 + output_response * 0.2)",
    "cy": "height * 0.5",
    "radius": "min_dim * 0.06",
    "fill_color": "#F4C95D",
    "fill_alt_color": "#FFF2B2",
    "stroke_color": "#FFFFFF",
    "line_width": "2",
    "opacity": "1",
}

BODY_GROUP = {
    "kind": "body_group",
    "id": "group_actor",
    "scientific": True,
    "clipping_policy": "forbid",
    "cx": "width * (0.25 + output_response * 0.4)",
    "cy": "height * 0.5",
    "rotation": "output_response * 0.2",
    "opacity": "1",
    "parts": [
        {
            "kind": "ellipse",
            "dx": "0",
            "dy": "0",
            "radius_x": "min_dim * 0.12",
            "radius_y": "min_dim * 0.05",
            "rotation": "0",
            "fill_color": "#46B3A9",
            "stroke_color": "#D9FFFB",
            "line_width": "2",
        },
        {
            "kind": "circle",
            "dx": "min_dim * 0.1",
            "dy": "0",
            "radius": "min_dim * 0.035",
            "fill_color": "#FFCF70",
            "stroke_color": "#FFFFFF",
            "line_width": "1",
        },
        {
            "kind": "rect",
            "dx": "-min_dim * 0.04",
            "dy": "min_dim * 0.045",
            "width": "min_dim * 0.08",
            "height": "min_dim * 0.025",
            "corner_radius": "min_dim * 0.01",
            "fill_color": "#237A73",
            "stroke_color": "#D9FFFB",
            "line_width": "1",
        },
        {
            "kind": "line",
            "dx1": "-min_dim * 0.1",
            "dy1": "0",
            "dx2": "-min_dim * 0.16",
            "dy2": "min_dim * 0.04",
            "stroke_color": "#D9FFFB",
            "line_width": "2",
        },
    ],
}

VECTOR_ARROW = {
    "kind": "vector_arrow",
    "id": "vector_actor",
    "scientific": True,
    "clipping_policy": "forbid",
    "x1": "width * 0.25",
    "y1": "height * 0.5",
    "angle": "-pi / 4 + output_response * 0.2",
    "length": "min_dim * (0.1 + output_response * 0.2)",
    "head_size": "min_dim * 0.035",
    "stroke_color": "#FFCF70",
    "line_width": "3",
    "opacity": "1",
}

RAY = {
    "kind": "ray",
    "id": "ray_actor",
    "scientific": True,
    "clipping_policy": "forbid",
    "x1": "width * 0.18",
    "y1": "height * 0.6",
    "segments": [
        {"angle": "-0.3", "length": "min_dim * (0.15 + output_response * 0.1)"},
        {"angle": "0.2", "length": "min_dim * 0.18"},
    ],
    "stroke_color": "#FFD46A",
    "line_width": "3",
    "opacity": "1",
}

TRAJECTORY = {
    "kind": "trajectory",
    "id": "trajectory_actor",
    "scientific": True,
    "clipping_policy": "forbid",
    "output_name": "response",
    "sweep": "primary_parameter",
    "samples": 9,
    "stroke_color": "#76D6C8",
    "line_width": "3",
    "opacity": "0.9",
}


def _representation(
    *,
    archetype: str = "body",
    actor_id: str = "reference_actor",
    channel: str = "x",
    motion_model: str = "parameter_driven",
) -> dict:
    del actor_id
    return {
        "scene_pattern": "world_only",
        "actor_archetype": archetype,
        "proof_channels": [
            {"output_name": "response", "carrier": "actor", "channel": channel}
        ],
        "motion_model": motion_model,
    }


def _visual(
    command: dict,
    *,
    archetype: str = "body",
    channel: str = "x",
    temporal_mode: str = "parameter_driven",
    motion_model: str = "parameter_driven",
) -> dict:
    return {
        "representation": _representation(
            archetype=archetype,
            actor_id=command["id"],
            channel=channel,
            motion_model=motion_model,
        ),
        "background": deepcopy(BACKGROUND),
        "commands": [deepcopy(command)],
        "relations": [],
        "causal_response": {
            "actor_id": command["id"],
            "output_name": "response",
            "channel": channel,
            "relation": "direct",
            "temporal_mode": temporal_mode,
        },
    }


@pytest.mark.parametrize(
    ("command", "archetype", "channel"),
    [
        pytest.param(BODY_GROUP, "body", "x", id="body-group"),
        pytest.param(VECTOR_ARROW, "body", "size", id="vector-arrow"),
        pytest.param(RAY, "ray_bundle", "size", id="ray"),
        pytest.param(TRAJECTORY, "body", "y", id="trajectory"),
    ],
)
def test_new_primitive_branches_accept_closed_valid_documents(
    command: dict,
    archetype: str,
    channel: str,
) -> None:
    from server.fragment_generation import validate_visual_fragment

    visual = _visual(command, archetype=archetype, channel=channel)

    assert validate_visual_fragment(visual, deepcopy(UNDERSTANDING)) == visual


@pytest.mark.parametrize(
    ("command", "archetype", "channel"),
    [
        pytest.param(BODY_GROUP, "body", "x", id="body-group"),
        pytest.param(VECTOR_ARROW, "body", "size", id="vector-arrow"),
        pytest.param(RAY, "ray_bundle", "size", id="ray"),
        pytest.param(TRAJECTORY, "body", "y", id="trajectory"),
    ],
)
def test_new_primitive_branches_reject_unknown_fields(
    command: dict,
    archetype: str,
    channel: str,
) -> None:
    from server.fragment_generation import validate_visual_fragment

    malformed = {**deepcopy(command), "model_points": [[0, 0], [1, 1]]}

    with pytest.raises(ValidationError):
        validate_visual_fragment(
            _visual(malformed, archetype=archetype, channel=channel),
            deepcopy(UNDERSTANDING),
        )


@pytest.mark.parametrize(
    ("command", "archetype", "channel", "mutate"),
    [
        pytest.param(
            BODY_GROUP,
            "body",
            "x",
            lambda item: item["parts"][0].update(radius_x=2),
            id="body-group-part-number",
        ),
        pytest.param(
            VECTOR_ARROW,
            "body",
            "size",
            lambda item: item.update(length=2),
            id="vector-arrow-number",
        ),
        pytest.param(
            RAY,
            "ray_bundle",
            "size",
            lambda item: item["segments"][0].update(angle=None),
            id="ray-segment-number",
        ),
        pytest.param(
            TRAJECTORY,
            "body",
            "y",
            lambda item: item.update(samples=7),
            id="trajectory-sample-floor",
        ),
    ],
)
def test_new_primitive_numeric_contracts_are_closed_and_bounded(
    command: dict,
    archetype: str,
    channel: str,
    mutate,
) -> None:
    from server.fragment_generation import validate_visual_fragment

    malformed = deepcopy(command)
    mutate(malformed)

    with pytest.raises(ValidationError):
        validate_visual_fragment(
            _visual(malformed, archetype=archetype, channel=channel),
            deepcopy(UNDERSTANDING),
        )


@pytest.mark.parametrize(
    ("command", "archetype", "channel", "remove_output"),
    [
        pytest.param(
            BODY_GROUP,
            "body",
            "x",
            lambda item: item.update(cx="width / 2", rotation="0"),
            id="body-group",
        ),
        pytest.param(
            VECTOR_ARROW,
            "body",
            "size",
            lambda item: item.update(angle="0", length="min_dim * 0.2"),
            id="vector-arrow",
        ),
        pytest.param(
            RAY,
            "ray_bundle",
            "size",
            lambda item: item["segments"][0].update(length="min_dim * 0.2"),
            id="ray",
        ),
    ],
)
def test_scientific_new_primitives_must_consume_a_declared_output(
    command: dict,
    archetype: str,
    channel: str,
    remove_output,
) -> None:
    from server.fragment_generation import fragment_failure_code, validate_visual_fragment
    from server.schemas import ContractError

    no_output = deepcopy(command)
    remove_output(no_output)

    with pytest.raises(ContractError) as captured:
        validate_visual_fragment(
            _visual(no_output, archetype=archetype, channel=channel),
            deepcopy(UNDERSTANDING),
        )

    assert fragment_failure_code(captured.value) == "scientific_output_reference_required"


@pytest.mark.parametrize(
    ("command", "archetype", "channel", "source_markers"),
    [
        pytest.param(
            BODY_GROUP,
            "body",
            "x",
            (
                "context.translate(cx,cy); context.rotate(rotation);",
                'if (part.kind === "ellipse")',
                'if (part.kind === "line")',
            ),
            id="body-group",
        ),
        pytest.param(
            VECTOR_ARROW,
            "body",
            "size",
            (
                "const x2 = x1 + length * Math.cos(angle);",
                "const headAngle = 0.45;",
            ),
            id="vector-arrow",
        ),
        pytest.param(
            RAY,
            "ray_bundle",
            "size",
            (
                "for (const segment of segments)",
                "rayPoints.push({x:rayX,y:rayY});",
            ),
            id="ray",
        ),
        pytest.param(
            TRAJECTORY,
            "body",
            "y",
            (
                "Array.from({length:sampleCount}",
                "modelState(trajectorySweep,trajectoryInputs,trajectoryTime)",
            ),
            id="trajectory",
        ),
    ],
)
def test_new_primitive_renderers_emit_deterministic_assembler_owned_drawing(
    command: dict,
    archetype: str,
    channel: str,
    source_markers: tuple[str, ...],
) -> None:
    from server.fragment_generation import assemble_fragments

    visual = _visual(command, archetype=archetype, channel=channel)
    first = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT), visual, deepcopy(UNDERSTANDING)
    )
    second = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT), deepcopy(visual), deepcopy(UNDERSTANDING)
    )

    assert first == second
    for marker in source_markers:
        assert marker in first["module_js"]


def _trajectory_operations(module_source: str) -> list[list[float | str]]:
    node_source = f"""
const operations = [];
const context = new Proxy({{
  createLinearGradient() {{ return {{ addColorStop() {{}} }}; }},
}}, {{
  get(target, property) {{
    if (property in target) return target[property];
    if (property === "moveTo" || property === "lineTo") {{
      return (x, y) => operations.push([property, x, y]);
    }}
    return () => {{}};
  }},
  set(target, property, value) {{ target[property] = value; return true; }},
}});
const canvas = {{ width: 200, height: 100 }};
{module_source}
window.LayshSimulation.init({{
  canvas,
  context,
  width: 200,
  height: 100,
  locale: "en",
  reducedMotion: true,
  emitFrame() {{}},
}});
process.stdout.write(JSON.stringify(operations));
"""
    completed = subprocess.run(
        ["node", "-e", f"global.window = {{}};\n{node_source}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_trajectory_samples_compiled_physics_at_endpoints_and_midpoint() -> None:
    from server.fragment_generation import assemble_fragments

    module_output = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT),
        _visual(TRAJECTORY, channel="y"),
        deepcopy(UNDERSTANDING),
    )

    operations = _trajectory_operations(module_output["module_js"])

    assert operations[0] == pytest.approx(["moveTo", 16, 88])
    assert operations[4] == pytest.approx(["lineTo", 100, 69])
    assert operations[8] == pytest.approx(["lineTo", 184, 12])


def test_time_driven_accepts_output_bound_time_motion_and_compiles_time() -> None:
    from server.fragment_generation import assemble_fragments, validate_visual_fragment

    actor = {
        **deepcopy(CIRCLE),
        "cx": "width / 2 + output_response * cos(time) * min_dim * 0.2",
    }
    visual = _visual(
        actor,
        channel="x",
        temporal_mode="cyclic",
        motion_model="time_driven",
    )

    assert validate_visual_fragment(visual, deepcopy(UNDERSTANDING)) == visual
    source = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT), visual, deepcopy(UNDERSTANDING)
    )["module_js"]
    assert "finiteNumber(visualPhase * 0.08)" in source
    assert "Math.cos(finiteNumber(time))" in source


@pytest.mark.parametrize(
    "cx",
    [
        pytest.param(
            "width / 2 + output_response * min_dim * 0.2",
            id="output-without-time",
        ),
        pytest.param(
            "width / 2 + cos(time) * min_dim * 0.2",
            id="time-without-output",
        ),
        pytest.param(
            "width / 2 + sin(phase) * min_dim * 0.2",
            id="decorative-phase-only",
        ),
    ],
)
def test_time_driven_rejects_motion_not_bound_to_time_and_output(cx: str) -> None:
    from server.fragment_generation import fragment_failure_code, validate_visual_fragment
    from server.schemas import ContractError

    actor = {**deepcopy(CIRCLE), "cx": cx}
    if "output_response" not in cx:
        actor["opacity"] = "0.5 + output_response * 0.5"
    visual = _visual(
        actor,
        channel="x",
        temporal_mode="cyclic",
        motion_model="time_driven",
    )

    with pytest.raises(ContractError) as captured:
        validate_visual_fragment(visual, deepcopy(UNDERSTANDING))

    assert (
        fragment_failure_code(captured.value)
        == "time_driven_scientific_motion_required"
    )


def test_physics_and_time_trajectory_use_one_declared_period() -> None:
    from server.fragment_generation import assemble_fragments

    understanding = deepcopy(UNDERSTANDING)
    understanding["module_spec"]["outputs"] = ["response", "period_s"]
    understanding["checks"].append(
        {
            "id": "period",
            "kind": "numeric",
            "inputs": [{"name": "input_value", "value": 0.5}],
            "output": "period_s",
            "expected": 2,
            "tolerance": 0.001,
            "unit": "s",
        }
    )
    physics = {
        **deepcopy(PHYSICS_FRAGMENT),
        "physics_expressions": [
            {"name": "response", "expression": "cos(time * pi)"},
            {"name": "period_s", "expression": "2"},
        ],
        "output_names": ["response", "period_s"],
    }
    trajectory = {**deepcopy(TRAJECTORY), "sweep": "time"}
    visual = _visual(trajectory, channel="y")

    source = assemble_fragments(physics, visual, understanding)["module_js"]
    operations = _trajectory_operations(source)

    assert operations[0] == pytest.approx(["moveTo", 16, 12])
    assert operations[4] == pytest.approx(["lineTo", 100, 88])
    assert operations[8] == pytest.approx(["lineTo", 184, 12])
    assert 'state.outputs["period_s"]' in source


def test_ray_bundle_requires_at_least_one_scientific_ray() -> None:
    from server.fragment_generation import fragment_failure_code, validate_visual_fragment
    from server.schemas import ContractError

    valid = _visual(RAY, archetype="ray_bundle", channel="size")
    invalid = _visual(CIRCLE, archetype="ray_bundle", channel="x")

    assert validate_visual_fragment(valid, deepcopy(UNDERSTANDING)) == valid
    with pytest.raises(ContractError) as captured:
        validate_visual_fragment(invalid, deepcopy(UNDERSTANDING))
    assert (
        fragment_failure_code(captured.value)
        == "representation_archetype_command_mismatch"
    )


@pytest.mark.parametrize(
    ("command", "archetype", "channel"),
    [
        pytest.param(BODY_GROUP, "body", "x", id="body-group"),
        pytest.param(VECTOR_ARROW, "body", "size", id="vector-arrow"),
        pytest.param(RAY, "ray_bundle", "size", id="ray"),
        pytest.param(TRAJECTORY, "body", "y", id="trajectory"),
    ],
)
def test_new_scientific_primitives_emit_conservative_relation_envelopes(
    command: dict,
    archetype: str,
    channel: str,
) -> None:
    from server.fragment_generation import assemble_fragments, validate_visual_fragment

    actor = deepcopy(command)
    actor["id"] = "new_actor"
    reference = {
        **deepcopy(CIRCLE),
        "cx": "width * 0.82",
        "opacity": "0.5 + output_response * 0.5",
    }
    visual = _visual(actor, archetype=archetype, channel=channel)
    visual["commands"].append(reference)
    visual["relations"] = [
        {
            "objects": ["new_actor", "reference_actor"],
            "overlap_policy": "forbid",
            "contact_policy": "forbid",
            "minimum_clearance": "8",
        }
    ]

    assert validate_visual_fragment(visual, deepcopy(UNDERSTANDING)) == visual
    source = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT), visual, deepcopy(UNDERSTANDING)
    )["module_js"]
    assert (
        'id:"new_actor",scientific:true,clippingPolicy:"forbid",'
        'geometry:{type:"circle"' in source
    )


def test_safety_envelopes_cannot_claim_exact_contact_or_occlusion() -> None:
    from server.fragment_generation import fragment_failure_code, validate_visual_fragment
    from server.schemas import ContractError

    actor = {**deepcopy(VECTOR_ARROW), "id": "new_actor"}
    visual = _visual(actor, channel="size")
    visual["commands"].append(deepcopy(CIRCLE))
    visual["relations"] = [
        {
            "objects": ["new_actor", "reference_actor"],
            "overlap_policy": "allow",
            "contact_policy": "required",
            "minimum_clearance": "0",
        }
    ]

    with pytest.raises(ContractError) as captured:
        validate_visual_fragment(visual, deepcopy(UNDERSTANDING))

    assert fragment_failure_code(captured.value) == "unsupported_safety_envelope_relation"


def test_every_new_failure_code_has_actionable_retry_guidance() -> None:
    from server.codex_backend import FRAGMENT_RETRY_HINTS

    expected_codes = {
        "time_driven_scientific_motion_required",
        "trajectory_output_undeclared",
        "unsupported_safety_envelope_relation",
    }

    assert expected_codes <= set(FRAGMENT_RETRY_HINTS)
    for code in expected_codes:
        assert len(FRAGMENT_RETRY_HINTS[code].split()) >= 6
