from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import ValidationError

from tests.golden_cases import VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]


def test_simulatable_lesson_requires_a_closed_actor_and_action():
    from server.schemas import validate_understanding

    candidate = deepcopy(VALID_UNDERSTANDING)
    candidate["module_spec"] = {
        "outputs": ["lit_fraction"],
        "actor": "moon",
        "action": "orbits",
    }
    assert validate_understanding(candidate)["module_spec"]["actor"] == "moon"

    missing_actor = deepcopy(candidate)
    missing_actor["module_spec"].pop("actor")
    with pytest.raises(ValidationError):
        validate_understanding(missing_actor)


def test_actor_and_action_values_are_closed():
    from server.schemas import validate_understanding

    candidate = deepcopy(VALID_UNDERSTANDING)
    candidate["module_spec"] = {
        "outputs": ["lit_fraction"],
        "actor": "moon",
        "action": "teleports",
    }

    with pytest.raises(ValidationError):
        validate_understanding(candidate)


def test_curated_review_requires_the_fixture_actor_and_action():
    from server.goldens import review_golden_candidate

    fixture = json.loads((ROOT / "server/fixtures/moon_phases_ar.json").read_text("utf-8"))
    module_output = {
        "module_js": (ROOT / "tests/fixtures/moon_phase_module.js").read_text("utf-8"),
        "output_names": ["lit_fraction"],
        "brief_summary": "fixture",
        "assumptions": [],
    }
    matching = review_golden_candidate(
        fixture=fixture,
        understanding=VALID_UNDERSTANDING,
        module_output=module_output,
    )
    assert matching["checks"]["actor_action_matches_reference"] is True

    mismatched = deepcopy(VALID_UNDERSTANDING)
    mismatched["module_spec"]["action"] = "phases"
    review = review_golden_candidate(
        fixture=fixture,
        understanding=mismatched,
        module_output=module_output,
    )
    assert review["checks"]["actor_action_matches_reference"] is False
    assert "actor_action_reference_mismatch" in review["failure_codes"]
