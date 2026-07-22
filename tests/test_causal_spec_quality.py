from copy import deepcopy

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

IDENTITY_UNDERSTANDING = {
    **deepcopy(VALID_UNDERSTANDING),
    "canonical_intent": "wavelength_color_identity",
    "domain": "optics",
    "title": "كيف يفصل المطر ألوان الضوء؟",
    "tldr": "تشتت القطرة أطوال الضوء الموجية بزوايا مختلفة.",
    "key_formula": "λ → color",
    "learning_objective": "ربط الطول الموجي بمقدار انحراف الضوء",
    "primary_parameter": {
        "id": "wavelength_nm",
        "label": "الطول الموجي للضوء",
        "unit": "nm",
        "min": 380,
        "max": 700,
        "default": 550,
        "step": 10,
    },
    "module_spec": {
        "outputs": ["color_wavelength_nm"],
        "actor": "wavefront",
        "action": "propagates",
    },
    "checks": [
        {
            "id": f"wavelength_{value}",
            "kind": "numeric",
            "inputs": [{"name": "wavelength_nm", "value": value}],
            "output": "color_wavelength_nm",
            "expected": value,
            "tolerance": 0,
            "unit": "nm",
        }
        for value in (380, 550, 700)
    ],
}


IDENTITY_MODULE = r"""
/* LAYSH_SHARED_MODEL: modelState */
window.LayshSimulation = (() => {
  "use strict";
  let canvas, context, width, height, emitFrame, wavelengthNm = 550;
  function modelState(value) {
    const wavelength = Math.max(380, Math.min(700, Number(value)));
    return { color_wavelength_nm: wavelength };
  }
  function draw() {
    const state = modelState(wavelengthNm);
    context.clearRect(0, 0, width, height);
    context.fillStyle = `rgb(${Math.round(state.color_wavelength_nm / 3)} 90 160)`;
    context.fillRect(0, 0, width, height);
    canvas.__layshSceneGeometry = [{
      schemaVersion: "1.0",
      phase: "post_fit",
      viewport: { width, height, safeInset: 0 },
      state: { id: "rendered", timeMs: 0 },
      objects: [{
        id: "wavefront",
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
    setParameter(name, value) {
      if (name === "wavelength_nm") { wavelengthNm = Number(value); draw(); }
    },
    test(inputs) {
      const state = modelState(inputs.wavelength_nm);
      return { color_wavelength_nm: state.color_wavelength_nm };
    },
    resize(nextWidth, nextHeight) { width = nextWidth; height = nextHeight; draw(); },
    destroy() { context = null; }
  };
})();
"""


def test_understanding_may_omit_formula_when_display_math_would_mislead():
    from server.schemas import validate_understanding

    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["key_formula"] = None

    assert validate_understanding(understanding)["key_formula"] is None


def test_verifier_rejects_identity_output_even_if_contract_preflight_is_bypassed():
    from server.verify import verify_candidate

    result = verify_candidate(
        {
            **VALID_MODULE_OUTPUT,
            "module_js": IDENTITY_MODULE,
            "output_names": ["color_wavelength_nm"],
        },
        deepcopy(IDENTITY_UNDERSTANDING),
    )

    failure = next(item for item in result.failures if item["gate"] == "causal_observable")
    assert result.passed is False
    assert failure["code"] == "primary_input_identity"
    assert failure["parameter"] == "wavelength_nm"
    assert failure["output"] == "color_wavelength_nm"
    assert failure["actual"]["samples"] == [
        {"input": 380, "output": 380},
        {"input": 550, "output": 550},
        {"input": 700, "output": 700},
    ]


def test_verifier_accepts_a_legitimate_identity_relation_with_a_distinct_quantity_name():
    from server.verify import verify_candidate

    understanding = deepcopy(IDENTITY_UNDERSTANDING)
    understanding["key_formula"] = "y = x"
    understanding["primary_parameter"]["id"] = "input_value"
    understanding["module_spec"]["outputs"] = ["response"]
    for check in understanding["checks"]:
        check["inputs"][0]["name"] = "input_value"
        check["output"] = "response"
    source = IDENTITY_MODULE.replace("wavelength_nm", "input_value").replace(
        "color_wavelength_nm", "response"
    )

    result = verify_candidate(
        {**VALID_MODULE_OUTPUT, "module_js": source, "output_names": ["response"]},
        understanding,
    )

    assert not any(item["gate"] == "causal_observable" for item in result.failures)


def test_understand_prompt_requires_a_derived_causal_observable():
    from server.codex_backend import CodexBackend

    prompt = CodexBackend._render_prompt(
        "understand.md",
        {"question": "كيف يتغير الأثر؟", "locale": "ar"},
    )
    normalized = " ".join(prompt.split())

    assert "first output must be a derived scientific consequence" in normalized
    assert "Never merely rename or repeat the primary control as an output" in normalized
    assert "at least three distinct primary values" in normalized
    assert "bare mapping such as `λ → color`" in normalized


def test_understand_prompt_does_not_force_categorical_questions_into_fake_sliders():
    from server.codex_backend import CodexBackend

    prompt = CodexBackend._render_prompt(
        "understand.md",
        {"question": "ليش تختلف مادتان؟", "locale": "ar"},
    )
    normalized = " ".join(prompt.split())

    assert "Do not invent a numeric slider for a categorical or material comparison" in normalized
    assert "no declared actor/action can show the mechanism honestly" in normalized


def test_generation_heal_and_review_require_salient_causal_evidence_without_live_overlays():
    from server.codex_backend import CodexBackend

    prompts = {
        name: " ".join(CodexBackend._render_prompt(name, {}).split())
        for name in ("generate_module.md", "heal_module.md", "qa.md", "visual_qa.md")
    }
    for prompt in prompts.values():
        assert "prediction must be visibly testable" in prompt
        assert "not only text, a marker, a frame counter, or decorative motion" in prompt
    for name in ("generate_module.md", "heal_module.md", "qa.md"):
        assert (
            "Never draw changing numbers, percentages, or live readout values on the canvas"
            in prompts[name]
        )
        assert "trusted shell owns the live numeric readout below the scene" in prompts[name]
