from __future__ import annotations

import re
from pathlib import Path

from tests.conftest import wait_for_terminal

ROOT = Path(__file__).parents[1]


def _generated_source(overlap_policy: str) -> str:
    source = (ROOT / "tests" / "fixtures" / "moon_phase_module.js").read_text(
        encoding="utf-8"
    )
    evidence = f"""
    canvas.__layshSceneGeometry = [{{
      schemaVersion: "1.0",
      phase: "post_fit",
      viewport: {{ width, height, safeInset: 0 }},
      state: {{ id: "rendered", timeMs: 0 }},
      objects: [
        {{
          id: "source",
          scientific: true,
          clippingPolicy: "forbid",
          geometry: {{ type: "circle", cx: width / 2, cy: height / 2, radius: 40 }},
        }},
        {{
          id: "actor",
          scientific: true,
          clippingPolicy: "forbid",
          geometry: {{ type: "circle", cx: width / 2 + 20, cy: height / 2, radius: 30 }},
        }},
      ],
      relations: [{{
        objects: ["source", "actor"],
        overlapPolicy: "{overlap_policy}",
        contactPolicy: "allow",
        minimumClearance: 0,
      }}],
    }}];
"""
    return source.replace("    emitFrame();", f"{evidence}    emitFrame();")


def _source_without_scene_evidence() -> str:
    source = (ROOT / "tests" / "fixtures" / "moon_phase_module.js").read_text(
        encoding="utf-8"
    )
    stripped, count = re.subn(
        r"\n    canvas\.__layshSceneGeometry = \[\{.*?\n    \}\];",
        "",
        source,
        count=1,
        flags=re.DOTALL,
    )
    assert count == 1
    return stripped


def _ask(client, question: str) -> str:
    response = client.post("/api/ask", json={"question": question, "locale": "ar"})
    assert response.status_code == 202
    return response.json()["job_id"]


def test_generated_forbidden_overlap_is_rejected_by_the_learner_pipeline(
    client,
    backend,
):
    backend._good_source = _generated_source("forbid")

    result = wait_for_terminal(client, _ask(client, "اختبار تصادم اصطناعي"))

    assert result["status"] == "answer_only"
    assert result["simulation"] is None
    assert result["fallback"]["reason_code"] == "verification_exhausted"
    assert backend.last_heal_failures
    failures = [
        failure
        for attempt in backend.last_heal_failures
        for failure in attempt
        if failure["gate"] == "scene_geometry"
    ]
    assert {failure["code"] for failure in failures} == {"undeclared_overlap"}
    assert failures[0]["expected"] == {
        "overlapPolicy": "forbid",
        "minimumClearance": 0,
    }
    assert failures[0]["actual"]["overlapPx"] == 50.0


def test_generated_module_without_scene_evidence_fails_closed(client, backend):
    backend._good_source = _source_without_scene_evidence()

    result = wait_for_terminal(client, _ask(client, "اختبار دليل مشهد مفقود"))

    assert result["status"] == "answer_only"
    assert result["simulation"] is None
    assert any(
        failure["gate"] == "scene_geometry"
        and failure["code"] == "scene_samples_missing"
        for attempt in backend.last_heal_failures
        for failure in attempt
    )


def test_generated_scientific_occlusion_uses_shared_gate_and_remains_eligible(
    client,
    backend,
    monkeypatch,
):
    import server.verify
    from server.scene_geometry import validate_scene_geometry as shared_validator

    calls: list[object] = []

    def recording_validator(samples: object):
        calls.append(samples)
        return shared_validator(samples)

    monkeypatch.setattr(server.verify, "validate_scene_geometry", recording_validator)
    backend._good_source = _generated_source("scientific_occlusion")

    result = wait_for_terminal(client, _ask(client, "اختبار حجب علمي اصطناعي"))

    assert result["status"] == "complete"
    assert result["simulation"]["tier"] == "B"
    assert result["simulation"]["heal_count"] == 0
    assert calls
    assert all(isinstance(samples, list) and samples for samples in calls)


def test_generation_and_heal_prompts_require_post_fit_scene_evidence():
    generate = (ROOT / "server" / "prompts" / "generate_module.md").read_text(
        encoding="utf-8"
    )
    heal = (ROOT / "server" / "prompts" / "heal_module.md").read_text(
        encoding="utf-8"
    )

    for prompt in (generate, heal):
        assert "canvas.__layshSceneGeometry" in prompt
        assert 'phase: "post_fit"' in prompt
        assert "scientific_occlusion" in prompt
