from __future__ import annotations

import json

import pytest

UNDERSTANDING = {
    "safe": True,
    "unsafe_category": None,
    "simulatable": True,
    "reason_code": "ok",
    "lang": "ar",
    "canonical_intent": "linear_response",
    "domain": "physics",
    "title": "كيف تتغير الاستجابة؟",
    "tldr": "تتبع الاستجابة قيمة المدخل في هذا النموذج المبسط.",
    "key_formula": "y = x",
    "learning_objective": "ربط المدخل بالاستجابة المرصودة",
    "primary_parameter": {
        "id": "input_value",
        "label": "قيمة المدخل",
        "unit": "",
        "min": 0,
        "max": 10,
        "default": 5,
        "step": 1,
    },
    "secondary_parameter": None,
    "prediction": {
        "prompt": "ماذا يحدث عند زيادة المدخل؟",
        "choices": ["تزداد الاستجابة", "تنقص الاستجابة"],
    },
    "misconception": "تصحيح: هذا النموذج ليس ثابتًا؛ بل تتبع الاستجابة المدخل.",
    "explanation_prompt": "تغيرت الاستجابة لأن…",
    "transfer_prompt": "ماذا تتوقع إذا صارت قيمة المدخل ٨؟",
    "module_spec": {
        "outputs": ["response"],
        "actor": "visible_body",
        "action": "rotates",
    },
    "checks": [
        {
            "id": "midpoint",
            "kind": "numeric",
            "inputs": [{"name": "input_value", "value": 5}],
            "output": "response",
            "expected": 5,
            "tolerance": 0.001,
            "unit": "",
        },
        {
            "id": "upper_value",
            "kind": "numeric",
            "inputs": [{"name": "input_value", "value": 8}],
            "output": "response",
            "expected": 8,
            "tolerance": 0.001,
            "unit": "",
        },
    ],
    "suggestions": [],
}


def _sample(
    *,
    phase: str = "post_fit",
    geometry_type: str = "circle",
    overlap_policy: str | None = None,
    actor_x: int = 320,
    time_ms: int = 0,
) -> dict[str, object]:
    objects: list[dict[str, object]] = [
        {
            "id": "source",
            "scientific": True,
            "clippingPolicy": "forbid",
            "geometry": (
                {"type": "circle", "cx": 300, "cy": 200, "radius": 40}
                if geometry_type == "circle"
                else {"type": geometry_type}
            ),
        }
    ]
    relations: list[dict[str, object]] = []
    if overlap_policy is not None:
        objects.append(
            {
                "id": "actor",
                "scientific": True,
                "clippingPolicy": "forbid",
                "geometry": {
                    "type": "circle",
                    "cx": actor_x,
                    "cy": 200,
                    "radius": 30,
                },
            }
        )
        relations.append(
            {
                "objects": ["source", "actor"],
                "overlapPolicy": overlap_policy,
                "contactPolicy": "allow",
                "minimumClearance": 0,
            }
        )
    return {
        "schemaVersion": "1.0",
        "phase": phase,
        "viewport": {"width": 720, "height": 400, "safeInset": 0},
        "state": {"id": "rendered", "timeMs": time_ms},
        "objects": objects,
        "relations": relations,
    }


def _module_output(
    sample: dict[str, object] | list[dict[str, object]],
) -> dict[str, object]:
    samples = sample if isinstance(sample, list) else [sample]
    source = """
window.LayshSimulation = (() => {
  "use strict";
  let canvas;
  let context;
  let width;
  let height;
  let emitFrame;
  let inputValue = 5;

  /* LAYSH_SHARED_MODEL: computeState */
  function computeState(input) {
    const numeric = Number(input);
    return { response: Number.isFinite(numeric) ? numeric : 5 };
  }

  function draw() {
    const state = computeState(inputValue);
    context.clearRect(0, 0, width, height);
    context.beginPath();
    context.arc(width / 2, height / 2, 20 + state.response, 0, Math.PI * 2);
    context.fill();
    canvas.__layshSceneGeometry = __SCENE_SAMPLES__;
    emitFrame();
  }

  return {
    version: 1,
    init(options) {
      ({ canvas, context, width, height, emitFrame } = options);
      draw();
    },
    setParameter(name, value) {
      if (name !== "input_value") return;
      inputValue = Number(value);
      draw();
    },
    test(inputs) {
      const state = computeState(inputs.input_value);
      return { response: state.response };
    },
    resize(nextWidth, nextHeight) {
      width = nextWidth;
      height = nextHeight;
      canvas.width = nextWidth;
      canvas.height = nextHeight;
      draw();
    },
    destroy() {
      canvas = null;
      context = null;
    },
  };
})();
""".replace("__SCENE_SAMPLES__", json.dumps(samples, separators=(",", ":")))
    return {
        "module_js": source,
        "output_names": ["response"],
        "brief_summary": "يعرض تغير الاستجابة مع المدخل.",
        "assumptions": ["علاقة خطية مبسطة"],
    }


def _geometry_failures(result) -> list[dict[str, object]]:
    return [failure for failure in result.failures if failure["gate"] == "scene_geometry"]


@pytest.mark.parametrize("phase", ["candidate", "clamped"])
def test_generated_path_rejects_evidence_without_post_fit_recomputation(phase):
    from server.verify import verify_candidate

    result = verify_candidate(
        _module_output(_sample(phase=phase)),
        UNDERSTANDING,
    )

    assert result.passed is False
    assert result.artifact is None
    assert [failure["code"] for failure in _geometry_failures(result)] == [
        "post_fit_scene_sample_missing"
    ]


def test_generated_path_fails_closed_for_unsupported_scientific_geometry():
    from server.verify import verify_candidate

    result = verify_candidate(
        _module_output(_sample(geometry_type="spline")),
        UNDERSTANDING,
    )

    assert result.passed is False
    assert result.artifact is None
    assert [failure["code"] for failure in _geometry_failures(result)] == [
        "unsupported_scientific_geometry"
    ]


def test_generated_path_rejects_a_collision_in_a_later_motion_sample():
    from server.verify import verify_candidate

    result = verify_candidate(
        _module_output(
            [
                _sample(overlap_policy="forbid", actor_x=450, time_ms=0),
                _sample(overlap_policy="forbid", actor_x=320, time_ms=100),
            ]
        ),
        UNDERSTANDING,
    )

    assert result.passed is False
    assert result.artifact is None
    failures = _geometry_failures(result)
    assert [failure["code"] for failure in failures] == ["undeclared_overlap"]
    assert failures[0]["sample_index"] == 1
    assert failures[0]["state"] == {"id": "rendered", "timeMs": 100}


def test_generated_path_accepts_explicit_scientific_occlusion():
    from server.verify import verify_candidate

    result = verify_candidate(
        _module_output(_sample(overlap_policy="scientific_occlusion")),
        UNDERSTANDING,
    )

    assert result.passed is True
    assert result.artifact is not None
    assert _geometry_failures(result) == []
