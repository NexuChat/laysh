from copy import deepcopy

import pytest

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

ONE_PIXEL_MODULE = r"""
/* LAYSH_SHARED_MODEL: modelState */
window.LayshSimulation = (() => {
  "use strict";
  let canvas, context, width, height, emitFrame, angle = 90;
  function modelState(value) {
    const numeric = Number(value);
    return { lit_fraction: (1 - Math.cos(numeric * Math.PI / 180)) / 2 };
  }
  function draw() {
    const state = modelState(angle);
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#081326";
    context.fillRect(0, 0, width, height);
    context.fillStyle = "#ffffff";
    context.fillRect(Math.round(state.lit_fraction * 10), 10, 1, 1);
    canvas.__layshSceneGeometry = [{
      schemaVersion: "1.0",
      phase: "post_fit",
      viewport: { width, height, safeInset: 0 },
      state: { id: "rendered", timeMs: 0 },
      objects: [{
        id: "moon",
        scientific: true,
        clippingPolicy: "forbid",
        geometry: { type: "circle", cx: width / 2, cy: height / 2, radius: 24 },
      }],
      relations: [],
    }];
    emitFrame();
  }
  return {
    version: 1,
    init(options) { ({ canvas, context, width, height, emitFrame } = options); draw(); },
    setParameter(name, value) { if (name === "angle_deg") { angle = Number(value); draw(); } },
    test(inputs) { return modelState(inputs.angle_deg); },
    resize(nextWidth, nextHeight) { width = nextWidth; height = nextHeight; draw(); },
    destroy() { context = null; },
  };
})();
"""


@pytest.mark.browser
def test_browser_gate_accepts_a_legitimate_identity_relation():
    from server.assemble import assemble_artifact
    from server.browser_verify import verify_artifact_in_browser
    from tests.test_scene_geometry_ci_wiring import UNDERSTANDING, _module_output, _sample

    artifact = assemble_artifact(UNDERSTANDING, _module_output(_sample()))

    result = verify_artifact_in_browser(artifact)

    assert result.passed is True, result.failures


@pytest.mark.browser
def test_browser_gate_rejects_a_correct_model_with_only_one_pixel_of_visual_change():
    from server.assemble import assemble_artifact
    from server.browser_verify import verify_artifact_in_browser

    understanding = deepcopy(VALID_UNDERSTANDING)
    module_output = {
        **VALID_MODULE_OUTPUT,
        "module_js": ONE_PIXEL_MODULE,
        "output_names": ["lit_fraction"],
    }
    artifact = assemble_artifact(understanding, module_output)

    result = verify_artifact_in_browser(artifact)

    assert result.passed is False
    failure = next(
        item for item in result.failures if item["code"] == "canvas_pixels_unchanged"
    )
    assert (
        failure["actual"]["canvas_hash_before"]
        == failure["actual"]["canvas_hash_after"]
    )
