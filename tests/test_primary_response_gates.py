from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.golden_cases import VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]


SECONDARY_DRIVEN_PHYSICS = {
    "physics_expressions": [
        {
            "name": "readout",
            "expression": "secondary_value",
        }
    ],
    "output_names": ["readout"],
    "brief_summary": "Fixture whose readout follows only the secondary parameter.",
    "assumptions": ["The fixture intentionally ignores the primary parameter."],
}


VISIBLE_READOUT = {
    "representation": {
        "scene_pattern": "world_only",
        "actor_archetype": "body",
        "proof_channels": [
            {
                "output_name": "readout",
                "carrier": "actor",
                "channel": "opacity",
            }
        ],
        "motion_model": "parameter_driven",
    },
    "background": {
        "top_color": "#07111F",
        "bottom_color": "#10243A",
    },
    "commands": [
        {
            "kind": "circle",
            "id": "actor",
            "scientific": True,
            "clipping_policy": "forbid",
            "cx": "width / 2",
            "cy": "height / 2",
            "radius": "min(30, min_dim * 0.12)",
            "fill_color": "#F7E7A9",
            "fill_alt_color": "#D08A32",
            "stroke_color": "#FFFFFF",
            "line_width": "2",
            "opacity": "0.4 + output_readout * 0.1",
        }
    ],
    "relations": [],
    "causal_response": {
        "actor_id": "actor",
        "output_name": "readout",
        "channel": "opacity",
        "relation": "direct",
        "temporal_mode": "parameter_driven",
    },
}


def _secondary_driven_understanding() -> dict:
    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["key_formula"] = "y = s"
    understanding["primary_parameter"] = {
        "id": "primary_value",
        "label": "Primary",
        "unit": "u",
        "min": 0,
        "max": 10,
        "default": 5,
        "step": 1,
    }
    understanding["secondary_parameter"] = {
        "id": "secondary_value",
        "label": "Secondary",
        "unit": "u",
        "min": 1,
        "max": 3,
        "default": 2,
        "step": 1,
    }
    understanding["module_spec"] = {
        "outputs": ["readout"],
        "actor": "visible_body",
        "action": "phases",
    }
    understanding["checks"] = [
        {
            "id": "minimum_primary",
            "kind": "numeric",
            "inputs": [
                {"name": "primary_value", "value": 0},
                {"name": "secondary_value", "value": 1},
            ],
            "output": "readout",
            "expected": 1,
            "tolerance": 0,
            "unit": "u",
        },
        {
            "id": "default_parameters",
            "kind": "numeric",
            "inputs": [
                {"name": "primary_value", "value": 5},
                {"name": "secondary_value", "value": 2},
            ],
            "output": "readout",
            "expected": 2,
            "tolerance": 0,
            "unit": "u",
        },
        {
            "id": "maximum_primary",
            "kind": "numeric",
            "inputs": [
                {"name": "primary_value", "value": 10},
                {"name": "secondary_value", "value": 3},
            ],
            "output": "readout",
            "expected": 3,
            "tolerance": 0,
            "unit": "u",
        },
    ]
    return understanding


def test_deterministic_verification_rejects_first_output_that_ignores_primary():
    from server.fragment_generation import assemble_fragments
    from server.verify import verify_candidate

    understanding = _secondary_driven_understanding()
    module_output = assemble_fragments(
        deepcopy(SECONDARY_DRIVEN_PHYSICS),
        deepcopy(VISIBLE_READOUT),
        understanding,
    )

    result = verify_candidate(module_output, understanding)

    assert len(result.node_report["passing_numeric_fixtures"]) == 3
    assert result.passed is False
    failure = next(
        item
        for item in result.failures
        if item["gate"] == "readout_visibility"
        and item["code"] == "formatted_endpoints_indistinguishable"
    )
    assert failure["parameter"] == "primary_value"
    assert failure["output"] == "readout"
    assert failure["actual"]["minimum_input"] == 0
    assert failure["actual"]["maximum_input"] == 10
    assert failure["actual"]["minimum_formatted"] == "2.00"
    assert failure["actual"]["maximum_formatted"] == "2.00"


def _browser_result(monkeypatch: pytest.MonkeyPatch, before: int, after: int):
    from server.browser_verify import verify_artifact_in_browser

    evidence = {
        "ready": True,
        "controlChanged": True,
        "frameChanged": True,
        "canvasHashBefore": before,
        "canvasHashAfter": after,
        "runtimeError": False,
        "externalRequests": 0,
    }
    monkeypatch.setattr("server.browser_verify.shutil.which", lambda _: "/usr/bin/node")
    monkeypatch.setattr(
        "server.browser_verify.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(evidence),
            stderr="",
        ),
    )
    return verify_artifact_in_browser("<!doctype html><title>pixel evidence</title>")


@pytest.mark.parametrize(
    ("before", "after", "expected_passed"),
    [
        pytest.param(1_234, 1_234, False, id="unchanged-pixels"),
        pytest.param(1_234, 5_678, True, id="changed-pixels"),
    ],
)
def test_browser_gate_requires_canvas_pixel_change(
    monkeypatch: pytest.MonkeyPatch,
    before: int,
    after: int,
    expected_passed: bool,
):
    result = _browser_result(monkeypatch, before, after)

    assert result.passed is expected_passed
    if not expected_passed:
        assert result.failures == [
            {
                "gate": "browser_readiness",
                "code": "canvas_pixels_unchanged",
                "expected": {"canvas_pixels_changed": True},
                "actual": {
                    "canvas_hash_before": before,
                    "canvas_hash_after": after,
                },
            }
        ]


def test_browser_probe_collects_before_and_after_canvas_pixel_hashes():
    source = (ROOT / "scripts" / "check_artifact.mjs").read_text(encoding="utf-8")

    assert "getImageData" in source
    assert "canvasHashBefore" in source
    assert "canvasHashAfter" in source


def _fragment_prompt_instructions(name: str, understanding: dict) -> str:
    from server.codex_backend import CodexBackend

    prompt = CodexBackend._render_prompt(name, understanding)
    instructions = prompt.split("UNDERSTANDING_JSON:\n", 1)[0]
    return " ".join(instructions.split())


def test_physics_prompt_requires_primary_driven_first_readout_at_other_defaults():
    prompt = _fragment_prompt_instructions(
        "generate_physics.md",
        _secondary_driven_understanding(),
    )

    assert (
        "Treat the first ordered `module_spec.outputs` entry as the learner-facing readout."
        in prompt
    )
    assert (
        "It must respond to changes in the parameter named by `primary_parameter.id` "
        "while every other declared parameter is held at its declared default."
        in prompt
    )
    assert "write scientific constants as finite numeric literals" in prompt
    assert "never invent a symbolic alias" in prompt


def test_visual_prompt_requires_visible_primary_response_and_idle_phase():
    prompt = _fragment_prompt_instructions(
        "generate_visual.md",
        _secondary_driven_understanding(),
    )

    assert (
        "Changes to the parameter named by `primary_parameter.id` must visibly alter "
        "at least one salient non-text scene property"
        in prompt
    )
    assert "Use `phase` in at least one visible numeric field for subtle idle motion." in prompt


def test_visual_prompt_keeps_dynamic_numbers_out_of_the_scientific_scene():
    prompt = _fragment_prompt_instructions(
        "generate_visual.md",
        _secondary_driven_understanding(),
    )

    assert (
        "Do not draw changing numbers, percentages, or live readout values on the canvas."
        in prompt
    )
    assert "The trusted shell owns the live numeric readout below the scene." in prompt
    assert "Keep narrow mobile canvases free of overlays that cover the scientific actor." in prompt


def test_visual_prompt_requires_cohesive_recognizable_actor_motion_and_correct_axes():
    prompt = _fragment_prompt_instructions(
        "generate_visual.md",
        _secondary_driven_understanding(),
    )

    assert "recognizable silhouette" in prompt
    assert "same center, output, and phase expressions" in prompt
    assert "Canvas y increases downward" in prompt
    assert "one scientific ellipse" in prompt


@pytest.mark.parametrize(
    "prompt_name",
    ["generate_module.md", "heal_module.md", "qa.md"],
)
def test_all_module_routes_keep_live_numeric_readouts_in_the_trusted_shell(
    prompt_name: str,
):
    prompt = _fragment_prompt_instructions(
        prompt_name,
        _secondary_driven_understanding(),
    )

    assert (
        "Never draw changing numbers, percentages, or live readout values on the canvas."
        in prompt
    )
    assert "The trusted shell owns the live numeric readout below the scene." in prompt
    assert "especially on narrow mobile viewports" in prompt
