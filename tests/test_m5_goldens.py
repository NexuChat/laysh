from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_p0_fixture_registry_is_allowlisted_bilingual_and_builder_reviewable():
    from server.goldens import GOLDEN_FIXTURE_IDS, load_golden_fixtures

    fixtures = load_golden_fixtures()

    assert set(fixtures) == set(GOLDEN_FIXTURE_IDS) == {
        "buoyancy_ar",
        "day_night_ar",
        "moon_phases_ar",
        "pendulum_ar",
        "simple_circuit_ar",
        "sound_pitch_ar",
    }
    for fixture_id, fixture in fixtures.items():
        assert fixture["fixture_id"] == fixture_id
        assert fixture["locale"] == "ar"
        assert fixture["question"]
        assert set(fixture["metadata"]) == {"ar", "en"}
        for locale in ("ar", "en"):
            assert fixture["metadata"][locale]["title"]
            assert fixture["metadata"][locale]["domain"]
            assert fixture["metadata"][locale]["summary"]
        review = fixture["review_contract"]
        assert len(review["reference_fixtures"]) >= 3
        assert review["primary_parameter"]["min"] < review["primary_parameter"]["default"]
        assert review["primary_parameter"]["default"] < review["primary_parameter"]["max"]
        assert review["formula"]
        assert review["units"]
        assert review["assumptions"]
        assert review["misconception"]


def test_generate_prompt_requires_light_occlusion_labels_and_smooth_shading():
    from server.codex_backend import CodexBackend
    from tests.golden_cases import VALID_UNDERSTANDING

    prompt = CodexBackend._render_prompt("generate_module.md", VALID_UNDERSTANDING)

    assert "never draw light through an opaque body" in prompt
    assert "subtle shadow cone" in prompt
    assert "منظر علوي" in prompt and "كما يبدو من الأرض" in prompt
    assert "smooth fills or gradients" in prompt
    assert "golf-ball dot patterns" in prompt


def test_builder_reference_review_rechecks_three_independent_moon_values():
    from server.goldens import load_golden_fixtures, review_golden_candidate
    from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

    fixture = load_golden_fixtures()["moon_phases_ar"]
    module_output = {
        **VALID_MODULE_OUTPUT,
        "module_js": (Path(__file__).parent / "fixtures" / "moon_phase_module.js").read_text(
            encoding="utf-8"
        ),
    }
    review = review_golden_candidate(
        fixture=fixture,
        understanding=VALID_UNDERSTANDING,
        module_output=module_output,
    )

    assert review["checks"]["formula_matches_reference"] is True
    assert review["checks"]["bilingual_metadata"] is True
    assert review["checks"]["reference_fixture_count"] == 3
    assert review["checks"]["reference_fixtures_passed"] is True
    assert review["checks"]["misconception_present"] is True
    assert review["checks"]["teaching_flow_complete"] is True
    assert review["passed"] is True


def test_builder_reference_review_rejects_wrong_formula_and_reference_outputs():
    from copy import deepcopy

    from server.goldens import load_golden_fixtures, review_golden_candidate
    from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

    fixture = load_golden_fixtures()["moon_phases_ar"]
    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["key_formula"] = "f = θ"
    good_source = (Path(__file__).parent / "fixtures" / "moon_phase_module.js").read_text(
        encoding="utf-8"
    )
    module_output = {
        **VALID_MODULE_OUTPUT,
        "module_js": good_source.replace(
            "return { lit_fraction: litFraction(Number(inputs.angle_deg)) };",
            "return { lit_fraction: 0 };",
        ),
    }
    review = review_golden_candidate(
        fixture=fixture,
        understanding=understanding,
        module_output=module_output,
    )

    assert review["passed"] is False
    assert review["checks"]["formula_matches_reference"] is False
    assert review["checks"]["reference_fixtures_passed"] is False
    assert "formula_reference_mismatch" in review["failure_codes"]
    assert "builder_reference_fixture_failed" in review["failure_codes"]


def test_builder_review_rejects_loose_model_fixture_tolerances():
    from copy import deepcopy

    from server.goldens import load_golden_fixtures, review_golden_candidate
    from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

    fixture = load_golden_fixtures()["moon_phases_ar"]
    understanding = deepcopy(VALID_UNDERSTANDING)
    for check in understanding["checks"]:
        check["tolerance"] = 1.0
    module_output = {
        **VALID_MODULE_OUTPUT,
        "module_js": (Path(__file__).parent / "fixtures" / "moon_phase_module.js").read_text(
            encoding="utf-8"
        ),
    }

    review = review_golden_candidate(
        fixture=fixture,
        understanding=understanding,
        module_output=module_output,
    )

    assert review["checks"]["model_fixtures_match_reference"] is False
    assert "model_fixture_contract_mismatch" in review["failure_codes"]


def test_portable_shell_keeps_arabic_kicker_clear_and_text_alternative_localized():
    root = Path(__file__).parents[1]
    css = (root / "sim_shell" / "shell.css").read_text(encoding="utf-8")
    script = (root / "sim_shell" / "shell.js").read_text(encoding="utf-8")

    assert ".eyebrow" in css and "line-height: 1.8" in css
    assert "margin-block-end: .8rem" in css
    assert "line-height: 1.3" in css
    assert "firstName" not in script
    assert "النتيجة المحسوبة" in script


def test_verified_golden_pin_is_tier_a_alias_aware_and_immutable(tmp_path):
    from server.cache import VerificationReceipt, VerifiedCache

    golden_root = tmp_path / "out" / "cache" / "golden"
    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=golden_root,
        secret=b"offline-test-secret",
        contract_version="1.0",
    )
    receipt = VerificationReceipt(True, True, 0, 31)
    metadata = {
        "ar": {"title": "أطوار القمر", "domain": "الفلك", "summary": "ملخص"},
        "en": {"title": "Moon phases", "domain": "Astronomy", "summary": "Summary"},
    }

    entry = cache.pin_golden(
        golden_id="moon_phases",
        question="لماذا يتغير شكل القمر؟",
        locale="ar",
        domain="astronomy",
        canonical_intent="moon_phase_lit_fraction",
        artifact="<!doctype html><title>verified</title>",
        title="لماذا يتغير شكل القمر؟",
        direction="rtl",
        receipt=receipt,
        aliases=["moon-phases", "اطوار-القمر"],
        answer={"tldr": "جواب", "key_formula": "f = (1 − cos θ) / 2"},
        metadata=metadata,
        review={"verdict": "pass"},
        evidence={"report": "goldens/moon_phases.json"},
    )

    assert entry.pinned is True and entry.tier == "A"
    document = json.loads((golden_root / "moon_phases.json").read_text(encoding="utf-8"))
    assert document["golden_id"] == "moon_phases"
    assert document["aliases"] == ["moon-phases", "اطوار-القمر"]
    assert document["metadata"] == metadata
    assert cache.lookup(
        question="different wording",
        locale="ar",
        domain="astronomy",
        canonical_intent="moon_phase_lit_fraction",
    ) == entry

    with pytest.raises(ValueError, match="immutable"):
        cache.pin_golden(
            golden_id="moon_phases",
            question="لماذا يتغير شكل القمر؟",
            locale="ar",
            domain="astronomy",
            canonical_intent="moon_phase_lit_fraction",
            artifact="replacement",
            title="replacement",
            direction="rtl",
            receipt=receipt,
            aliases=[],
            answer={"tldr": "x", "key_formula": None},
            metadata=metadata,
            review={"verdict": "pass"},
            evidence={},
        )


@pytest.mark.asyncio
async def test_promoted_evidence_job_always_runs_qa_and_retains_review_inputs():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    backend = MockCodexBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        evidence_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    record = manager.start_evidence(
        "success",
        "ar",
        "moon_phases_ar",
        promote_golden=True,
    )
    await record.task

    assert record.status == "complete"
    assert record.promote_golden is True
    assert backend.qa_calls == 1
    assert record.builder_outputs["understanding"]["key_formula"] == "f = (1 − cos θ) / 2"
    assert record.builder_outputs["module_output"]["module_js"]
    assert record.builder_outputs["verification"]["passed"] is True
    assert record.builder_outputs["browser"]["ready"] is True
