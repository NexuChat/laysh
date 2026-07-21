from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]


SHARED_MODEL_SOURCE = """
/* LAYSH_SHARED_MODEL: modelState */
window.LayshSimulation = (() => {
  "use strict";
  let canvas, context, width, height, emitFrame, angleDeg = 90;
  function modelState(value) {
    const angle = Math.max(0, Math.min(360, Number(value)));
    return { angle, lit_fraction: (1 - Math.cos(angle * Math.PI / 180)) / 2 };
  }
  function draw() {
    const state = modelState(angleDeg);
    context.clearRect(0, 0, width, height);
    context.fillStyle = `rgb(${Math.round(state.lit_fraction * 255)} 80 120)`;
    context.fillRect(0, 0, width, height);
    canvas.__layshSceneGeometry = [{
      schemaVersion: "1.0",
      phase: "post_fit",
      viewport: { width, height, safeInset: 0 },
      state: { id: "rendered", timeMs: 0 },
      objects: [{
        id: "actor",
        scientific: true,
        clippingPolicy: "forbid",
        geometry: { type: "circle", cx: width / 2, cy: height / 2, radius: 20 },
      }],
      relations: [],
    }];
    emitFrame();
  }
  return {
    version: 1,
    init(options) { ({ canvas, context, width, height, emitFrame } = options); draw(); },
    setParameter(name, value) { if (name === "angle_deg") { angleDeg = Number(value); draw(); } },
    test(inputs) {
      const state = modelState(inputs.angle_deg);
      return { lit_fraction: state.lit_fraction };
    },
    resize(nextWidth, nextHeight) { width = nextWidth; height = nextHeight; draw(); },
    destroy() { context = null; }
  };
})();
"""


def test_shared_state_static_contract_requires_one_model_function_for_draw_and_test():
    from server.shared_state import shared_model_report

    report = shared_model_report(SHARED_MODEL_SOURCE)

    assert report["passed"] is True
    assert report["model_function"] == "modelState"


def test_shared_state_static_contract_rejects_a_deliberately_divergent_visual_model():
    from server.shared_state import shared_model_report

    divergent = SHARED_MODEL_SOURCE.replace(
        "  function draw() {\n    const state = modelState(angleDeg);",
        "  function visualState(value) {\n"
        "    return { lit_fraction: Number(value) / 360 };\n"
        "  }\n"
        "  function draw() {\n    const state = visualState(angleDeg);",
    )

    report = shared_model_report(divergent)

    assert report["passed"] is False
    assert {failure["code"] for failure in report["failures"]} == {
        "shared_model_not_used_by_render"
    }


def test_shared_state_static_contract_rejects_an_unused_shared_call_next_to_visual_drift():
    from server.shared_state import shared_model_report

    divergent = SHARED_MODEL_SOURCE.replace(
        "  function draw() {",
        "  function visualState(value) {\n"
        "    return { lit_fraction: Number(value) / 360 };\n"
        "  }\n"
        "  function draw() {",
    ).replace(
        "    const state = modelState(angleDeg);\n"
        "    context.clearRect(0, 0, width, height);\n"
        "    context.fillStyle = `rgb(${Math.round(state.lit_fraction * 255)} 80 120)`;",
        "    const state = modelState(angleDeg);\n"
        "    const visual = visualState(angleDeg);\n"
        "    context.clearRect(0, 0, width, height);\n"
        "    context.fillStyle = `rgb(${Math.round(visual.lit_fraction * 255)} 80 120)`;",
    )

    report = shared_model_report(divergent)

    assert report["passed"] is False
    assert "shared_model_state_not_consumed_by_render" in {
        failure["code"] for failure in report["failures"]
    }


def test_shared_state_static_contract_requires_a_named_state_object():
    from server.shared_state import shared_model_report

    scalar = SHARED_MODEL_SOURCE.replace(
        "return { angle, lit_fraction: (1 - Math.cos(angle * Math.PI / 180)) / 2 };",
        "return (1 - Math.cos(angle * Math.PI / 180)) / 2;",
    ).replace("state.lit_fraction", "state")

    report = shared_model_report(scalar)

    assert report["passed"] is False
    assert "shared_model_not_state_object" in {
        failure["code"] for failure in report["failures"]
    }


def test_candidate_verification_rejects_a_divergent_visual_model_even_when_numeric_tests_pass():
    from server.verify import verify_candidate

    divergent = SHARED_MODEL_SOURCE.replace(
        "  function draw() {\n    const state = modelState(angleDeg);",
        "  function visualState(value) {\n"
        "    return { lit_fraction: Number(value) / 360 };\n"
        "  }\n"
        "  function draw() {\n    const state = visualState(angleDeg);",
    )

    result = verify_candidate(
        {**VALID_MODULE_OUTPUT, "module_js": divergent},
        deepcopy(VALID_UNDERSTANDING),
    )

    assert result.node_report["passed"] is True
    assert "shared_model_not_used_by_render" in {
        failure["code"] for failure in result.failures
    }


def test_all_six_pinned_goldens_declare_a_single_shared_model_state():
    from server.goldens import _artifact_lesson_and_module, load_pinned_golden
    from server.shared_state import shared_model_report

    for golden_id in (
        "moon_phases",
        "buoyancy",
        "pendulum",
        "simple_circuit",
        "sound_pitch",
        "day_night",
    ):
        golden = load_pinned_golden(golden_id)
        assert golden is not None
        _, source = _artifact_lesson_and_module(golden["artifact"])
        assert shared_model_report(source)["passed"] is True


def test_golden_shared_state_upgrade_is_deterministic_and_satisfies_the_contract():
    from server.golden_shared_state import upgrade_golden_module
    from server.goldens import _artifact_lesson_and_module, load_pinned_golden
    from server.shared_state import shared_model_report

    for golden_id in (
        "moon_phases",
        "buoyancy",
        "pendulum",
        "simple_circuit",
        "sound_pitch",
        "day_night",
    ):
        golden = load_pinned_golden(golden_id)
        assert golden is not None
        _, source = _artifact_lesson_and_module(golden["artifact"])
        upgraded = upgrade_golden_module(golden_id, source)

        assert upgraded == upgrade_golden_module(golden_id, source)
        assert shared_model_report(upgraded)["passed"] is True


def test_legacy_shared_model_refresh_fails_closed_without_scene_evidence(
    tmp_path, monkeypatch
):
    import server.codex_backend
    from server.browser_verify import BrowserVerificationResult
    from server.goldens import refresh_pinned_golden_shared_model_states

    monkeypatch.setattr(
        server.codex_backend.CodexBackend,
        "__init__",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("model call is forbidden")),
    )
    golden_root = tmp_path / "golden"
    shutil.copytree(ROOT / "out/cache/golden", golden_root)
    for path in golden_root.glob("*.json"):
        if path.name == "manifest.json":
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        document["artifact"] = document["artifact"].replace(
            "LAYSH_CURATED_SCENE_ADAPTER_V1", "LEGACY_SCENE_ADAPTER", 1
        )
        document["evidence"].pop("curated_shell_refresh", None)
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    before = {path.name: path.read_bytes() for path in golden_root.glob("*.json")}

    with pytest.raises(ValueError, match="deterministic refresh verification"):
        refresh_pinned_golden_shared_model_states(
            root=golden_root,
            browser_verifier=lambda _artifact: BrowserVerificationResult.passing(),
        )

    assert {path.name: path.read_bytes() for path in golden_root.glob("*.json")} == before


def test_generation_prompt_requires_the_shared_model_state_contract():
    from pathlib import Path

    prompt = (Path(__file__).parents[1] / "server/prompts/generate_module.md").read_text(
        encoding="utf-8"
    )

    assert "LAYSH_SHARED_MODEL" in prompt
    assert "same model function" in prompt
