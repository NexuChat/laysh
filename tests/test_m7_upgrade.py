from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_web_shell_carries_the_night_observatory_identity(client):
    html = client.get("/").text
    css = client.get("/static/app.css").text

    for color in ("#05080b", "#0e1c2b", "#f6a94a", "#58b7ff", "#eef4f8", "#7e93a6"):
        assert color in css
    assert 'class="brand-dot"' in html
    assert "اسأل ليش، والعب الجواب." in html
    assert 'class="star-field"' in html
    assert "orbit-scene" in html
    assert "color-scheme: dark" in css
    assert "letter-spacing: -" not in css
    assert "prefers-reduced-motion: reduce" in css
    assert 'href="/static/fonts/free-serif-arabic-display.woff2"' in html


def test_build_view_has_truthful_agent_theatre_hooks(client):
    html = client.get("/").text
    script = client.get("/static/app.js").text

    for element_id in (
        "agent-theatre",
        "verification-grid",
        "heal-act",
        "domain-fact",
        "sim-silhouette",
    ):
        assert f'id="{element_id}"' in html
    assert "payload.detail" in script
    assert "payload.elapsed_ms" in script
    assert "payload.evidence" in script
    assert 'payload.stage === "healing"' in script
    assert "state.answer" in script and "domain-fact" in script
    assert "Math.round" not in script


def test_result_and_portable_shell_offer_projector_mode(client):
    html = client.get("/").text
    shell_html = (ROOT / "sim_shell" / "shell.html").read_text(encoding="utf-8")
    shell_js = (ROOT / "sim_shell" / "shell.js").read_text(encoding="utf-8")

    assert 'id="projector-result"' in html
    assert 'id="projector"' in shell_html
    assert "requestFullscreen" in shell_js
    assert "projector" in shell_js


def test_shell_scheduler_is_visual_only_and_reduced_motion_aware():
    source = (ROOT / "sim_shell" / "shell.js").read_text(encoding="utf-8")

    assert "requestAnimationFrame" in source
    assert "cancelAnimationFrame" in source
    assert "if (reducedMotion)" in source
    assert "simulation.setParameter(parameter.id, Number(control.value))" in source
    assert "setInterval" not in source


def test_module_budget_is_96_kib_and_prompt_matches_it():
    from server.verify import MAX_SOURCE_BYTES, verify_module_source

    prompt = (ROOT / "server" / "prompts" / "generate_module.md").read_text(
        encoding="utf-8"
    )
    assert MAX_SOURCE_BYTES == 96 * 1024
    assert "96 KiB" in prompt
    source = "window.LayshSimulation = {};/*" + ("x" * (95 * 1024)) + "*/"
    assert verify_module_source(source)["source_size_bytes"] < MAX_SOURCE_BYTES


def test_generation_prompt_enforces_the_living_instrument_bar():
    prompt = (ROOT / "server" / "prompts" / "generate_module.md").read_text(
        encoding="utf-8"
    )

    for requirement in (
        "layered scene depth",
        "physically consistent",
        "idle motion",
        "reactive feedback",
        "readout chips",
        "same-value redraw",
    ):
        assert requirement in prompt
    assert "timers" in prompt and "requestAnimationFrame" in prompt


def test_qa_contract_contains_a_closed_visual_richness_review():
    from server.schemas import load_schema, validate_document

    schema = load_schema("qa.schema.json")
    checklist = {
        "scene_depth": True,
        "physical_light": True,
        "idle_motion": True,
        "reactive_feedback": True,
        "readable_overlays": True,
    }
    valid = {
        "approved": True,
        "issues": [],
        "replacement_module_js": None,
        "visual_richness": checklist,
    }
    assert validate_document(valid, schema) == valid
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    visual_schema = schema["properties"]["visual_richness"]
    assert visual_schema["additionalProperties"] is False
    assert set(visual_schema["required"]) == set(visual_schema["properties"])


def test_qa_prompt_reviews_visual_richness_without_rewriting():
    prompt = (ROOT / "server" / "prompts" / "qa.md").read_text(encoding="utf-8")

    assert "visual_richness" in prompt
    for requirement in ("scene depth", "physical light", "idle motion", "reactive feedback"):
        assert requirement in prompt
    assert "does not implement" in prompt


def test_v11_builder_review_requires_every_visual_richness_item():
    source = (ROOT / "scripts" / "generate_goldens.py").read_text(encoding="utf-8")
    browser_source = (ROOT / "scripts" / "check_golden.mjs").read_text(encoding="utf-8")

    for field in (
        "scene_depth_present",
        "physical_light_beautiful",
        "idle_motion_present",
        "reactive_feedback_present",
        "readout_overlay_clear",
    ):
        assert field in source
    assert '"visual_richness"' in source
    assert 'choices=("v1.1",)' in source
    assert "idleFrameChanged" in browser_source
    assert "reactiveFrameVariants" in browser_source


def test_explicit_release_revision_can_replace_a_pin_but_live_writes_remain_blocked(
    tmp_path: Path,
):
    from server.cache import VerificationReceipt, VerifiedCache

    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=tmp_path / "golden",
        secret=b"release-test-secret",
        contract_version="1.0",
    )
    receipt = VerificationReceipt(True, True, 0, 12)
    common = {
        "golden_id": "moon_phases",
        "question": "لماذا يتغير شكل القمر؟",
        "locale": "ar",
        "domain": "astronomy",
        "canonical_intent": "moon_phase_lit_fraction",
        "title": "أطوار القمر",
        "direction": "rtl",
        "receipt": receipt,
        "aliases": ["moon_phases"],
        "answer": {"tldr": "جواب", "key_formula": "f = (1 − cos θ) / 2"},
        "metadata": {"ar": {"title": "أطوار القمر"}},
        "review": {"verdict": "pass"},
        "evidence": {"gate": "G7"},
    }
    original = cache.pin_golden(artifact="<!doctype html><p>v1</p>", **common)
    replacement = cache.pin_golden(
        artifact="<!doctype html><p>v1.1</p>",
        release_revision="v1.1",
        expected_previous_sha256=original.artifact_sha256,
        **common,
    )

    pinned = json.loads((tmp_path / "golden" / "moon_phases.json").read_text())
    assert replacement.artifact_sha256 != original.artifact_sha256
    assert pinned["release_revision"] == "v1.1"
    with pytest.raises(ValueError, match="immutable"):
        cache.write_verified(
            question=common["question"],
            locale="ar",
            domain="astronomy",
            canonical_intent="moon_phase_lit_fraction",
            artifact="live overwrite",
            title="live",
            direction="rtl",
            tier="B",
            receipt=receipt,
        )


def test_qa_schema_change_keeps_structured_output_restrictions():
    path = ROOT / "server" / "schemas" / "qa.schema.json"
    document = json.loads(path.read_text(encoding="utf-8"))

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False
                assert set(value.get("required", [])) == set(value.get("properties", {}))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)
