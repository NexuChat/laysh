from __future__ import annotations

import re
from copy import deepcopy

import pytest
from jsonschema import ValidationError

from tests.golden_cases import VALID_UNDERSTANDING
from tests.test_parallel_fragment_generation import PHYSICS_FRAGMENT


def _scientific_actor(*, opacity: str = "0.5 + output_lit_fraction * 0.5") -> dict:
    return {
        "kind": "circle",
        "id": "primary_actor",
        "scientific": True,
        "clipping_policy": "forbid",
        "cx": "width * (0.25 + output_lit_fraction * 0.5)",
        "cy": "height / 2",
        "radius": "min_dim * 0.12",
        "fill_color": "#F7E7A9",
        "fill_alt_color": "#D08A32",
        "stroke_color": "#FFFFFF",
        "line_width": "2",
        "opacity": opacity,
    }


def _visual_fragment() -> dict:
    return {
        "representation": {
            "scene_pattern": "world_only",
            "actor_archetype": "body",
            "proof_channels": [
                {
                    "output_name": "lit_fraction",
                    "carrier": "actor",
                    "channel": "x",
                }
            ],
            "motion_model": "parameter_driven",
        },
        "background": {
            "top_color": "#07111F",
            "bottom_color": "#10243A",
        },
        "commands": [_scientific_actor()],
        "relations": [],
        "causal_response": {
            "actor_id": "primary_actor",
            "output_name": "lit_fraction",
            "channel": "x",
            "relation": "direct",
            "temporal_mode": "parameter_driven",
        },
    }


def _signed_understanding() -> dict:
    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["primary_parameter"] = {
        "id": "signed_input",
        "label": "Signed input",
        "unit": "u",
        "min": -1,
        "max": 1,
        "default": 0,
        "step": 0.1,
    }
    understanding["module_spec"]["outputs"] = ["signed_response"]
    understanding["checks"] = [
        {
            "id": "negative_response",
            "kind": "numeric",
            "inputs": [{"name": "signed_input", "value": -1}],
            "output": "signed_response",
            "expected": -1,
            "tolerance": 0.01,
            "unit": "u",
        },
        {
            "id": "zero_response",
            "kind": "numeric",
            "inputs": [{"name": "signed_input", "value": 0}],
            "output": "signed_response",
            "expected": 0,
            "tolerance": 0.01,
            "unit": "u",
        },
        {
            "id": "positive_response",
            "kind": "numeric",
            "inputs": [{"name": "signed_input", "value": 1}],
            "output": "signed_response",
            "expected": 1,
            "tolerance": 0.01,
            "unit": "u",
        },
    ]
    return understanding


def _signed_visual_fragment() -> dict:
    document = _visual_fragment()
    document["commands"][0]["cx"] = "width / 2 + output_signed_response * 20"
    document["commands"][0]["opacity"] = "1"
    document["causal_response"]["output_name"] = "signed_response"
    document["representation"]["proof_channels"][0]["output_name"] = "signed_response"
    return document


def test_visual_fragment_requires_a_closed_causal_response_contract():
    from server.fragment_generation import validate_visual_fragment

    document = _visual_fragment()

    assert validate_visual_fragment(document, deepcopy(VALID_UNDERSTANDING)) == document

    missing = deepcopy(document)
    missing.pop("causal_response")
    with pytest.raises(ValidationError):
        validate_visual_fragment(missing, deepcopy(VALID_UNDERSTANDING))

    unexpected = deepcopy(document)
    unexpected["causal_response"]["raw_javascript"] = "fetch('/')"
    with pytest.raises(ValidationError):
        validate_visual_fragment(unexpected, deepcopy(VALID_UNDERSTANDING))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        pytest.param(
            lambda document: document["causal_response"].update(actor_id="missing"),
            "scientific actor",
            id="missing-actor",
        ),
        pytest.param(
            lambda document: document["commands"][0].update(scientific=False),
            "scientific actor",
            id="decorative-actor",
        ),
        pytest.param(
            lambda document: document["causal_response"].update(output_name="invented"),
            "declared output",
            id="undeclared-output",
        ),
    ],
)
def test_causal_response_references_a_scientific_actor_and_declared_output(
    mutation,
    message: str,
):
    from server.fragment_generation import validate_visual_fragment
    from server.schemas import ContractError

    document = _visual_fragment()
    mutation(document)

    with pytest.raises(ContractError, match=message):
        validate_visual_fragment(document, deepcopy(VALID_UNDERSTANDING))


def test_causal_output_must_be_covered_by_an_understanding_fixture():
    from server.fragment_generation import validate_visual_fragment
    from server.schemas import ContractError

    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["module_spec"]["outputs"] = ["lit_fraction", "other_output"]
    understanding["checks"] = [
        {**check, "output": "other_output"} for check in understanding["checks"]
    ]

    with pytest.raises(ContractError, match="fixture"):
        validate_visual_fragment(_visual_fragment(), understanding)


def test_causal_channel_field_must_directly_consume_the_declared_output():
    from server.fragment_generation import validate_visual_fragment
    from server.schemas import ContractError

    wrong_channel = _visual_fragment()
    wrong_channel["commands"][0]["cx"] = "width * (0.25 + normalized * 0.5)"
    with pytest.raises(ContractError, match="causal channel field"):
        validate_visual_fragment(wrong_channel, deepcopy(VALID_UNDERSTANDING))

    output_only_in_another_field = deepcopy(wrong_channel)
    output_only_in_another_field["commands"][0]["opacity"] = (
        "0.5 + output_lit_fraction * 0.5"
    )
    with pytest.raises(ContractError, match="causal channel field"):
        validate_visual_fragment(output_only_in_another_field, deepcopy(VALID_UNDERSTANDING))


@pytest.mark.parametrize(
    "flat_expression",
    [
        pytest.param(
            "width / 2 + output_lit_fraction * 0",
            id="cancelled-output",
        ),
        pytest.param(
            "clamp(output_lit_fraction, 0, 0)",
            id="flat-clamp",
        ),
    ],
)
def test_causal_channel_must_vary_across_fixture_covered_output_states(
    flat_expression: str,
):
    from server.fragment_generation import (
        fragment_failure_diagnostic,
        validate_visual_fragment,
    )
    from server.schemas import ContractError

    document = _visual_fragment()
    document["commands"][0]["cx"] = flat_expression

    with pytest.raises(ContractError) as captured:
        validate_visual_fragment(document, deepcopy(VALID_UNDERSTANDING))

    diagnostic = fragment_failure_diagnostic(
        captured.value,
        role="visual",
        understanding=deepcopy(VALID_UNDERSTANDING),
    )
    assert diagnostic == {
        "gate": "fragment_contract",
        "code": "causal_channel_fixture_response_required",
        "expected": {
            "fragment_contract_valid": True,
            "channel": "x",
            "minimum_distinct_states": 3,
            "minimum_range": 32.0,
            "monotonic_relation": "direct",
        },
        "actual": {
            "fragment_contract_valid": False,
            "failure_code": "causal_channel_fixture_response_required",
            "channel": "x",
            "distinct_states": 1,
            "observed_range": 0.0,
            "monotonic_relation": False,
            "output_name": "lit_fraction",
        },
    }


def test_flat_causal_channel_can_be_repaired_from_fixed_numeric_fixtures():
    from server.fragment_generation import (
        repair_visual_causal_response,
        validate_visual_fragment,
    )

    document = _visual_fragment()
    document["commands"][0]["cx"] = "width / 2 + output_lit_fraction * 0"

    repaired = repair_visual_causal_response(
        document,
        deepcopy(VALID_UNDERSTANDING),
    )

    assert repaired is not None
    assert document["commands"][0]["cx"] == (
        "width / 2 + output_lit_fraction * 0"
    )
    assert repaired["commands"][0]["cx"] != document["commands"][0]["cx"]
    assert "output_lit_fraction" in repaired["commands"][0]["cx"]
    assert (
        validate_visual_fragment(repaired, deepcopy(VALID_UNDERSTANDING))
        == repaired
    )


def test_causal_repair_fails_closed_without_three_numeric_fixture_states():
    from server.fragment_generation import repair_visual_causal_response

    document = _visual_fragment()
    document["commands"][0]["cx"] = "width / 2 + output_lit_fraction * 0"
    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["checks"] = understanding["checks"][:2]

    assert repair_visual_causal_response(document, understanding) is None


def test_actor_proof_channel_must_vary_across_fixture_covered_output_states():
    from server.fragment_generation import validate_visual_fragment
    from server.schemas import ContractError

    document = _visual_fragment()
    document["representation"]["proof_channels"].append(
        {
            "output_name": "lit_fraction",
            "carrier": "actor",
            "channel": "opacity",
        }
    )
    document["commands"][0]["opacity"] = "0.65 + output_lit_fraction * 0"

    with pytest.raises(
        ContractError,
        match="representation actor proof channel must vary",
    ):
        validate_visual_fragment(document, deepcopy(VALID_UNDERSTANDING))


def test_signed_output_crossing_zero_requires_negative_zero_positive_fixtures():
    from server.fragment_generation import validate_visual_fragment
    from server.schemas import ContractError

    understanding = _signed_understanding()
    missing_zero = deepcopy(understanding)
    missing_zero["checks"] = [
        check for check in missing_zero["checks"] if check["expected"] != 0
    ]

    with pytest.raises(ContractError, match="negative, zero, and positive"):
        validate_visual_fragment(_signed_visual_fragment(), missing_zero)

    assert (
        validate_visual_fragment(_signed_visual_fragment(), understanding)
        == _signed_visual_fragment()
    )


def test_trusted_assembler_emits_fitted_causal_actor_evidence():
    from server.fragment_generation import assemble_fragments

    module_output = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT),
        _visual_fragment(),
        deepcopy(VALID_UNDERSTANDING),
    )
    source = module_output["module_js"]

    assert "/* LAYSH_CAUSAL_RESPONSE_V1 */" in source
    assert "canvas.__layshActorResponse" in source
    for field in (
        "schemaVersion",
        "actorId",
        "outputName",
        "channel",
        "relation",
        "temporalMode",
        "parameterValue",
        "outputValue",
        "visualValue",
        "fittedBounds",
        "timeMs",
    ):
        assert field in source


def test_ellipse_rotation_is_compiled_as_safely_bounded_radians():
    from server.fragment_generation import assemble_fragments

    document = _visual_fragment()
    document["commands"] = [
        {
            "kind": "ellipse",
            "id": "primary_actor",
            "scientific": True,
            "clipping_policy": "forbid",
            "cx": "width / 2",
            "cy": "height / 2",
            "radius_x": "min_dim * 0.18",
            "radius_y": "min_dim * 0.08",
            "rotation": "output_lit_fraction * pi",
            "fill_color": "#58B7FF",
            "fill_alt_color": "#B8E3FF",
            "stroke_color": "#FFFFFF",
            "line_width": "2",
            "opacity": "1",
        }
    ]
    document["causal_response"]["channel"] = "rotation"
    document["representation"]["proof_channels"][0]["channel"] = "rotation"

    source = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT),
        document,
        deepcopy(VALID_UNDERSTANDING),
    )["module_js"]

    assert "const rotation = clampFinite(" in source
    assert "-Math.PI * 2,Math.PI * 2" in source


def test_fragment_contract_rejects_a_causal_relation_lie_before_assembly():
    from server.fragment_generation import (
        fragment_failure_diagnostic,
        validate_visual_fragment,
    )
    from server.schemas import ContractError

    document = _visual_fragment()
    document["commands"][0]["cx"] = (
        "width / 2 - output_lit_fraction * min_dim * 0.25"
    )
    with pytest.raises(ContractError) as captured:
        validate_visual_fragment(document, deepcopy(VALID_UNDERSTANDING))

    diagnostic = fragment_failure_diagnostic(
        captured.value,
        role="visual",
        understanding=deepcopy(VALID_UNDERSTANDING),
    )
    assert diagnostic["code"] == "causal_channel_fixture_response_required"
    assert diagnostic["expected"]["monotonic_relation"] == "direct"
    assert diagnostic["actual"]["monotonic_relation"] is False


def test_fragment_preflight_samples_the_fixture_defined_zero_crossing():
    from server.fragment_generation import assemble_fragments
    from server.verify import verify_candidate

    understanding = _signed_understanding()
    understanding["primary_parameter"].update(min=0, max=10, default=3, step=0.5)
    for check, parameter_value, expected in zip(
        understanding["checks"],
        (0, 3, 10),
        (-3, 0, 7),
        strict=True,
    ):
        check["inputs"] = [{"name": "signed_input", "value": parameter_value}]
        check["expected"] = expected
    physics = {
        "physics_expressions": [
            {"name": "signed_response", "expression": "signed_input - 3"}
        ],
        "output_names": ["signed_response"],
        "brief_summary": "Signed response with a fixture-defined neutral point.",
        "assumptions": ["The response is linear over the declared range."],
    }

    result = verify_candidate(
        assemble_fragments(physics, _signed_visual_fragment(), understanding),
        understanding,
    )

    assert result.passed is True, result.failures
    causal = result.node_report["causal_response"]
    assert any(
        abs(sample["parameterValue"] - 3) < 1e-9
        and abs(sample["outputValue"]) < 1e-9
        for sample in causal["samples"]
    )


def test_fragment_preflight_samples_relation_fixtures_without_crashing_node():
    from server.fragment_generation import assemble_fragments
    from server.verify import verify_candidate

    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["checks"].append(
        {
            "id": "larger_angle_more_light",
            "kind": "relation",
            "left_inputs": [{"name": "angle_deg", "value": 45}],
            "right_inputs": [{"name": "angle_deg", "value": 90}],
            "output": "lit_fraction",
            "relation": "right_gt_left",
            "minimum_ratio": 2,
        }
    )

    result = verify_candidate(
        assemble_fragments(PHYSICS_FRAGMENT, _visual_fragment(), understanding),
        understanding,
    )

    assert result.passed is True, result.failures
    assert not any(
        failure["code"] == "node_verifier_failed" for failure in result.failures
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_code", "actionable_phrase"),
    [
        ("causal_scientific_actor_required", "scientific actor"),
        ("causal_output_undeclared", "module spec"),
        ("causal_fixture_required", "fixture-covered"),
        ("causal_channel_output_required", "directly use"),
        (
            "signed_causal_fixture_coverage_required",
            "negative, zero, and positive",
        ),
    ],
)
async def test_causal_fragment_retry_codes_receive_topic_agnostic_guidance(
    failure_code: str,
    actionable_phrase: str,
):
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.codex_runtime import StageExecution
    from server.settings import Settings

    class RecordingExecutor:
        def __init__(self) -> None:
            self.prompt = ""

        async def execute_stage(self, **kwargs) -> StageExecution:
            self.prompt = kwargs["prompt"]
            return StageExecution(
                data=_visual_fragment(),
                thread_id="private-causal-contract-retry",
                model=kwargs["model"],
                elapsed_ms=1,
            )

    executor = RecordingExecutor()
    backend = CodexBackend(executor=executor, settings=Settings())

    await backend.regenerate_fragment(
        "visual",
        deepcopy(VALID_UNDERSTANDING),
        failure_code,
        runtime_context=RuntimeContext(public=True),
    )

    retry_guidance = executor.prompt.split("DETERMINISTIC_RETRY:", 1)[1]
    assert actionable_phrase in retry_guidance
    assert re.search(r"\b(?:car|plane)\b", executor.prompt.casefold()) is None
