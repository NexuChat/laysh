from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

UNDERSTANDING = {
    "safe": True,
    "unsafe_category": None,
    "simulatable": True,
    "reason_code": "ok",
    "lang": "en",
    "canonical_intent": "synthetic_temporal_response",
    "domain": "physics",
    "title": "Synthetic response",
    "tldr": "The visible actor follows the declared response.",
    "key_formula": "r = 2p + 1",
    "learning_objective": "Connect a control to a visible response.",
    "primary_parameter": {
        "id": "control_value",
        "label": "Control",
        "unit": "",
        "min": 0,
        "max": 10,
        "default": 5,
        "step": 1,
    },
    "secondary_parameter": None,
    "prediction": {
        "prompt": "What changes?",
        "choices": ["The response rises", "The response falls"],
    },
    "misconception": "Correction: the response is not constant.",
    "explanation_prompt": "The response changed because…",
    "transfer_prompt": "Predict another control value.",
    "module_spec": {
        "outputs": ["response", "period_ms"],
        "actor": "visible_body",
        "action": "rotates",
    },
    "checks": [
        {
            "id": "low",
            "kind": "numeric",
            "inputs": [{"name": "control_value", "value": 0}],
            "output": "response",
            "expected": 1,
            "tolerance": 0.001,
            "unit": "",
        },
        {
            "id": "middle",
            "kind": "numeric",
            "inputs": [{"name": "control_value", "value": 5}],
            "output": "response",
            "expected": 11,
            "tolerance": 0.001,
            "unit": "",
        },
        {
            "id": "high",
            "kind": "numeric",
            "inputs": [{"name": "control_value", "value": 10}],
            "output": "response",
            "expected": 21,
            "tolerance": 0.001,
            "unit": "",
        },
        {
            "id": "period",
            "kind": "numeric",
            "inputs": [{"name": "control_value", "value": 5}],
            "output": "period_ms",
            "expected": 400,
            "tolerance": 0.001,
            "unit": "ms",
        },
    ],
    "suggestions": [],
}


def _module_source(
    *,
    motion_model: str = "parameter_driven",
    parameter_expression: str = "value * 8",
    temporal_expression: str = "0",
    relation: str = "direct",
    scene_actor_id: str = "response_actor",
    scene_x_expression: str = "visualValue",
) -> str:
    temporal_mode = "cyclic" if motion_model == "cyclic" else "parameter_driven"
    return f"""
/* LAYSH_CAUSAL_RESPONSE_V1 */
window.LayshSimulation = Object.freeze((() => {{
  "use strict";
  let canvas, context, width, height, emitFrame = () => {{}};
  let value = 5;
  let timeMs = 0;
  const simulation = {{
    version: 1,
    init(options) {{
      ({{ canvas, context, width, height, emitFrame }} = options);
      value = 5;
      timeMs = 0;
      draw();
    }},
    setParameter(name, next, elapsedMs) {{
      if (name !== "control_value") return;
      value = Number(next);
      if (Number.isFinite(Number(elapsedMs))) timeMs += Number(elapsedMs);
      draw();
    }},
    test(inputs) {{
      return {{ response: Number(inputs.control_value) * 2 + 1, period_ms: 400 }};
    }},
    resize(nextWidth, nextHeight) {{
      width = nextWidth;
      height = nextHeight;
      canvas.width = width;
      canvas.height = height;
      draw();
    }},
    destroy() {{
      canvas = null;
      context = null;
    }},
  }};
  Object.defineProperty(simulation, "spec", {{
    value: Object.freeze({{
      representation: {{
        scene_pattern: "world_only",
        actor_archetype: "body",
        proof_channels: [{{ output_name: "response", carrier: "actor", channel: "x" }}],
        motion_model: {json.dumps(motion_model)},
      }},
    }}),
    enumerable: false,
  }});
  function draw() {{
    const outputValue = value * 2 + 1;
    const visualValue = 100 + ({parameter_expression}) + ({temporal_expression});
    const actorX = {scene_x_expression};
    context.clearRect(0, 0, width, height);
    context.beginPath();
    context.arc(actorX, 180, 18, 0, Math.PI * 2);
    context.fill();
    canvas.__layshSceneGeometry = [{{
      schemaVersion: "1.0",
      phase: "post_fit",
      viewport: {{ width, height, safeInset: 0 }},
      state: {{ id: "rendered", timeMs }},
      objects: [{{
        id: {json.dumps(scene_actor_id)},
        scientific: true,
        clippingPolicy: "forbid",
        geometry: {{ type: "circle", cx: actorX, cy: 180, radius: 18 }},
      }}],
      relations: [],
    }}];
    canvas.__layshActorResponse = {{
      schemaVersion: "1.0",
      actorId: "response_actor",
      outputName: "response",
      channel: "x",
      relation: {json.dumps(relation)},
      temporalMode: {json.dumps(temporal_mode)},
      parameterValue: value,
      outputValue,
      visualValue,
      fittedBounds: {{
        left: visualValue - 18,
        top: 162,
        right: visualValue + 18,
        bottom: 198,
        width: 36,
        height: 36,
      }},
      timeMs,
    }};
    emitFrame();
  }}
  return simulation;
}})());
"""


def _run_verifier(source: str, tmp_path: Path) -> dict:
    source_path = tmp_path / "candidate.js"
    understanding_path = tmp_path / "understanding.json"
    source_path.write_text(source, encoding="utf-8")
    understanding_path.write_text(
        json.dumps(UNDERSTANDING, ensure_ascii=False),
        encoding="utf-8",
    )
    completed = subprocess.run(  # noqa: S603 - fixed local verifier
        [
            "node",
            str(ROOT / "scripts" / "verify_module.mjs"),
            str(source_path),
            str(understanding_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _failure_codes(report: dict) -> set[str]:
    return {failure["code"] for failure in report["failures"]}


def test_temporal_causal_matrix_passes_all_twelve_samples_and_adds_checks(
    tmp_path: Path,
) -> None:
    baseline = _run_verifier(
        _module_source().replace(
            'Object.defineProperty(simulation, "spec", {',
            'Object.defineProperty(simulation, "legacySpec", {',
        ),
        tmp_path,
    )
    compliant = _run_verifier(_module_source(), tmp_path)

    assert compliant["passed"] is True, compliant["failures"]
    assert compliant["check_count"] == baseline["check_count"] + 5
    assert compliant["temporal_causal_matrix"]["sample_count"] == 12
    assert compliant["temporal_causal_matrix"]["parameter_values"] == [0, 5, 10]
    assert compliant["temporal_causal_matrix"]["time_samples_ms"] == [
        0,
        100,
        200,
        300,
    ]


@pytest.mark.parametrize(
    ("source", "expected_code"),
    [
        (
            _module_source(parameter_expression="0"),
            "actor_parameter_response_missing",
        ),
        (
            _module_source(relation="inverse"),
            "causal_direction_mismatch",
        ),
        (
            _module_source(
                motion_model="cyclic",
                temporal_expression="0",
            ),
            "actor_motion_missing",
        ),
        (
            _module_source(scene_actor_id="different_actor"),
            "declared_actor_command_missing",
        ),
        (
            _module_source(scene_x_expression="100"),
            "declared_actor_command_static",
        ),
    ],
)
def test_temporal_causal_matrix_rejects_structured_negative(
    tmp_path: Path,
    source: str,
    expected_code: str,
) -> None:
    report = _run_verifier(source, tmp_path)

    assert report["passed"] is False
    assert expected_code in _failure_codes(report)
    failure = next(item for item in report["failures"] if item["code"] == expected_code)
    assert failure["gate"] == "temporal_causal_matrix"
    assert set(failure) >= {"gate", "code", "expected", "actual"}


def test_cyclic_actor_passes_real_quarter_period_motion(tmp_path: Path) -> None:
    report = _run_verifier(
        _module_source(
            motion_model="cyclic",
            temporal_expression="Math.sin(timeMs / 400 * Math.PI * 2) * 40",
        ),
        tmp_path,
    )

    assert report["passed"] is True, report["failures"]
    assert report["temporal_causal_matrix"]["period_source"] == "period_ms"
    assert report["temporal_causal_matrix"]["time_distinct_actor_states"] >= 3


@pytest.mark.browser
def test_compliant_synthetic_artifact_passes_graph_and_archetype_browser_matrix() -> (
    None
):
    from server.assemble import assemble_artifact
    from server.browser_verify import verify_artifact_in_browser

    source = _module_source().replace(
        'scene_pattern: "world_only"',
        'scene_pattern: "world_plus_graph"',
    )
    artifact = assemble_artifact(
        deepcopy(UNDERSTANDING),
        {
            "module_js": source,
            "output_names": ["response", "period_ms"],
            "brief_summary": "A synthetic visible response.",
            "assumptions": ["The response is linear."],
        },
    )

    result = verify_artifact_in_browser(artifact)

    assert result.passed is True, result.failures
    assert result.check_count > 6
    representation = result.evidence["representationConsistency"]
    assert len(representation["graph"]["samples"]) == 5
    assert len(representation["graph"]["markers"]) == 3
    assert representation["archetype"]["matchingPrimitiveCount"] >= 1
