import json
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]


def _causal_sample(
    parameter_value: float,
    output_value: float,
    visual_value: float,
    *,
    actor_id: str = "primary-actor",
    channel: str = "x",
    relation: str = "direct",
    temporal_mode: str = "parameter_driven",
    time_ms: float = 0,
) -> dict:
    center_x = 100 + visual_value
    return {
        "schemaVersion": "1.0",
        "actorId": actor_id,
        "outputName": "primary_output",
        "channel": channel,
        "relation": relation,
        "temporalMode": temporal_mode,
        "parameterValue": parameter_value,
        "outputValue": output_value,
        "visualValue": visual_value,
        "fittedBounds": {
            "left": center_x - 10,
            "top": 90,
            "right": center_x + 10,
            "bottom": 110,
            "width": 20,
            "height": 20,
        },
        "timeMs": time_ms,
    }


def _passing_evidence() -> dict:
    return {
        "ready": True,
        "controlChanged": True,
        "frameChanged": True,
        "canvasHashBefore": 1234,
        "canvasHashAfter": 5678,
        "runtimeError": False,
        "externalRequests": 0,
        "causalResponse": {
            "required": True,
            "canvasWidth": 720,
            "canvasHeight": 400,
            "samples": [
                _causal_sample(-10, -10, 100),
                _causal_sample(-5, -5, 120),
                _causal_sample(0, 0, 140),
                _causal_sample(5, 5, 160),
                _causal_sample(10, 10, 180),
            ],
            "temporalSamples": [],
        },
    }


def _evaluate_with_causal_report(evidence: dict):
    from server.browser_verify import _evaluate

    causal = evidence["causalResponse"]
    module_uri = (ROOT / "scripts" / "causal_response.mjs").as_uri()
    completed = subprocess.run(  # noqa: S603 - fixed local evaluator and JSON input
        [
            "node",
            "--input-type=module",
            "--eval",
            (
                f"import {{evaluateCausalResponse}} from {json.dumps(module_uri)};"
                "let data='';process.stdin.setEncoding('utf8');"
                "process.stdin.on('data',chunk=>data+=chunk);"
                "process.stdin.on('end',()=>process.stdout.write("
                "JSON.stringify(evaluateCausalResponse(JSON.parse(data)))));"
            ),
        ],
        input=json.dumps(causal),
        check=True,
        capture_output=True,
        text=True,
    )
    causal["report"] = json.loads(completed.stdout)
    return _evaluate(evidence)


def test_browser_gate_returns_actionable_structured_failures(monkeypatch):
    from server.browser_verify import verify_artifact_in_browser

    observed = {
        "ready": True,
        "controlChanged": False,
        "frameChanged": True,
        "canvasHashBefore": 1234,
        "canvasHashAfter": 5678,
        "runtimeError": False,
        "externalRequests": 0,
    }
    monkeypatch.setattr("server.browser_verify.shutil.which", lambda _: "/usr/bin/node")
    monkeypatch.setattr(
        "server.browser_verify.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(observed),
            stderr="",
        ),
    )

    result = verify_artifact_in_browser("<!doctype html><title>fixture</title>")

    assert result.passed is False
    assert result.check_count == 6
    assert result.evidence == observed
    assert result.failures == [
        {
            "gate": "browser_readiness",
            "code": "primary_control_unchanged",
            "expected": {"control_changed": True},
            "actual": {"control_changed": False},
        }
    ]


def test_causal_browser_gate_accepts_salient_absolute_x_response_with_nonzero_neutral():
    result = _evaluate_with_causal_report(_passing_evidence())

    assert result.passed is True
    assert result.check_count > 6
    assert result.failures == []


def test_causal_browser_gate_accepts_inverse_actor_relation():
    evidence = _passing_evidence()
    for sample, visual_value in zip(
        evidence["causalResponse"]["samples"],
        [180, 160, 140, 120, 100],
        strict=True,
    ):
        sample.update(relation="inverse", visualValue=visual_value)

    result = _evaluate_with_causal_report(evidence)

    assert result.passed is True
    assert result.failures == []


def test_causal_browser_gate_requires_a_measured_neutral_when_outputs_cross_zero():
    evidence = _passing_evidence()
    for sample, output_value, visual_value in zip(
        evidence["causalResponse"]["samples"],
        (-2, -1, -0.1, 1, 2),
        (80, 105, 135, 160, 185),
        strict=True,
    ):
        sample.update(outputValue=output_value, visualValue=visual_value)

    result = _evaluate_with_causal_report(evidence)

    assert result.passed is False
    assert "causal_neutral_crossing_missing" in {
        failure["code"] for failure in result.failures
    }


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda evidence: evidence["causalResponse"]["samples"][3].update(
                actorId="replacement-actor"
            ),
            "causal_actor_id_unstable",
        ),
        (
            lambda evidence: evidence["causalResponse"]["samples"][2][
                "fittedBounds"
            ].update(left=-50, right=-30),
            "causal_actor_not_visible",
        ),
        (
            lambda evidence: [
                sample.update(visualValue=0)
                for sample in evidence["causalResponse"]["samples"]
            ],
            "causal_response_static",
        ),
        (
            lambda evidence: evidence["causalResponse"]["samples"][3].update(
                visualValue=-20
            ),
            "causal_relation_mismatch",
        ),
        (
            lambda evidence: evidence["causalResponse"]["samples"][2].update(
                visualValue=20
            ),
            "causal_neutral_crossing_missing",
        ),
    ],
)
def test_causal_browser_gate_rejects_non_causal_actor_evidence(mutate, expected_code):
    evidence = _passing_evidence()
    mutate(evidence)

    result = _evaluate_with_causal_report(evidence)

    assert result.passed is False
    failure = next(item for item in result.failures if item["code"] == expected_code)
    assert failure["gate"] == "causal_response"
    assert set(failure) == {"gate", "code", "expected", "actual"}


@pytest.mark.parametrize(
    ("channel", "visual_values", "expected_passed"),
    [
        ("x", [-10, -5, 0, 5, 10], False),
        ("x", [-40, -20, 0, 20, 40], True),
        ("rotation", [-0.05, -0.025, 0, 0.025, 0.05], False),
        ("rotation", [-0.1, -0.05, 0, 0.05, 0.1], True),
        ("size", [100, 104, 108, 112, 114], False),
        ("size", [100, 105, 110, 115, 120], True),
        ("opacity", [0.4, 0.44, 0.48, 0.52, 0.59], False),
        ("opacity", [0.3, 0.4, 0.5, 0.6, 0.7], True),
    ],
)
def test_causal_browser_gate_enforces_channel_salience(
    channel, visual_values, expected_passed
):
    evidence = _passing_evidence()
    for sample, visual_value in zip(
        evidence["causalResponse"]["samples"], visual_values, strict=True
    ):
        sample.update(
            channel=channel,
            visualValue=visual_value,
            outputValue=sample["parameterValue"],
        )

    result = _evaluate_with_causal_report(evidence)

    assert result.passed is expected_passed
    if not expected_passed:
        assert "causal_response_not_salient" in {
            failure["code"] for failure in result.failures
        }


def test_cyclic_actor_requires_four_temporal_states_from_the_same_actor():
    evidence = _passing_evidence()
    for sample in evidence["causalResponse"]["samples"]:
        sample["temporalMode"] = "cyclic"
    evidence["causalResponse"]["temporalSamples"] = [
        _causal_sample(
            0,
            0,
            40,
            temporal_mode="cyclic",
            time_ms=time_ms,
        )
        for time_ms in (0, 80, 160, 240)
    ]

    result = _evaluate_with_causal_report(evidence)

    assert result.passed is False
    assert "causal_actor_temporal_motion_missing" in {
        failure["code"] for failure in result.failures
    }


def test_cyclic_actor_accepts_four_salient_temporal_states():
    evidence = _passing_evidence()
    for sample in evidence["causalResponse"]["samples"]:
        sample["temporalMode"] = "cyclic"
    evidence["causalResponse"]["temporalSamples"] = [
        _causal_sample(
            0,
            0,
            visual_value,
            temporal_mode="cyclic",
            time_ms=time_ms,
        )
        for time_ms, visual_value in zip(
            (0, 80, 160, 240),
            (100, 140, 180, 140),
            strict=True,
        )
    ]

    result = _evaluate_with_causal_report(evidence)

    assert result.passed is True
    assert result.failures == []


def test_legacy_artifact_without_marker_keeps_existing_browser_contract():
    from server.browser_verify import _evaluate

    evidence = _passing_evidence()
    evidence.pop("causalResponse")

    result = _evaluate(evidence)

    assert result.passed is True
    assert result.check_count == 6


def test_browser_probe_samples_causal_actor_at_control_quartiles_and_four_times():
    source = (ROOT / "scripts" / "check_artifact.mjs").read_text(encoding="utf-8")

    assert "LAYSH_CAUSAL_RESPONSE_V1" in source
    assert "__layshActorResponse" in source
    assert "0.25" in source
    assert "0.75" in source
    assert "temporalSamples" in source
    assert "pauseForCausalSampling" in source


def _causal_artifact(*, actor_moves: bool) -> str:
    from server.assemble import assemble_artifact
    from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

    visual_expression = "value / 360 * 80" if actor_moves else "0"
    module_js = f"""
/* LAYSH_CAUSAL_RESPONSE_V1 */
window.LayshSimulation = (function () {{
  var canvas, context, width = 720, height = 400, value = 90, emitFrame = function () {{}};
  function draw() {{
    var outputValue = value / 360;
    var visualValue = {visual_expression};
    var centerX = width * 0.35 + visualValue;
    context.fillStyle = 'rgb(' + Math.round(10 + outputValue * 80) + ',24,48)';
    context.fillRect(0, 0, width, height);
    context.fillStyle = '#f7c95c';
    context.fillRect(centerX - 12, height * 0.5 - 12, 24, 24);
    canvas.__layshActorResponse = {{
      schemaVersion: '1.0', actorId: 'primary-actor', outputName: 'lit_fraction',
      channel: 'x', relation: 'direct', temporalMode: 'parameter_driven',
      parameterValue: value, outputValue: outputValue, visualValue: visualValue,
      fittedBounds: {{left:centerX-12,top:height*0.5-12,right:centerX+12,
        bottom:height*0.5+12,width:24,height:24}}, timeMs: 0
    }};
    emitFrame();
  }}
  return {{
    version: 1,
    init: function (options) {{ canvas=options.canvas; context=options.context;
      width=options.width; height=options.height; emitFrame=options.emitFrame; draw(); }},
    setParameter: function (_name, next) {{ value=Number(next); draw(); }},
    test: function (inputs) {{ return {{lit_fraction:Number(inputs.angle_deg)/360}}; }},
    resize: function (nextWidth,nextHeight) {{ width=nextWidth; height=nextHeight; draw(); }},
    destroy: function () {{ context=null; }}
  }};
}}());
"""
    return assemble_artifact(
        deepcopy(VALID_UNDERSTANDING),
        {**VALID_MODULE_OUTPUT, "module_js": module_js},
    )


@pytest.mark.browser
def test_real_browser_gate_accepts_causal_actor_and_rejects_global_only_motion():
    from server.browser_verify import verify_artifact_in_browser

    moving = verify_artifact_in_browser(_causal_artifact(actor_moves=True))
    decorative = verify_artifact_in_browser(_causal_artifact(actor_moves=False))

    assert moving.passed is True, moving.failures
    assert moving.evidence["causalResponse"]["report"]["passed"] is True
    assert decorative.passed is False
    assert "causal_response_static" in {
        failure["code"] for failure in decorative.failures
    }


@pytest.mark.asyncio
async def test_browser_failure_enters_heal_with_exact_report_before_publish():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    reports = [
        BrowserVerificationResult(
            passed=False,
            check_count=5,
            failures=[
                {
                    "gate": "browser_readiness",
                    "code": "primary_control_unchanged",
                    "expected": {"control_changed": True},
                    "actual": {"control_changed": False},
                }
            ],
            evidence={
                "ready": True,
                "controlChanged": False,
                "frameChanged": True,
                "runtimeError": False,
                "externalRequests": 0,
            },
        ),
        BrowserVerificationResult.passing(),
    ]

    def browser_verifier(_artifact):
        return reports.pop(0)

    backend = MockCodexBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=browser_verifier,
    )
    record = manager.start("success", "ar")
    await record.task

    assert record.status == "complete"
    assert backend.heal_calls == 1
    assert backend.last_heal_failures[0] == [
        {
            "gate": "browser_readiness",
            "code": "primary_control_unchanged",
            "expected": {"control_changed": True},
            "actual": {"control_changed": False},
        }
    ]
    assert record.simulation is not None
    assert record.simulation.heal_count == 1
    assert reports == []
