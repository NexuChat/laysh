import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import ValidationError
from pydantic import ValidationError as PydanticValidationError

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]


def test_valid_understanding_matches_closed_schema():
    from server.schemas import validate_understanding

    assert validate_understanding(VALID_UNDERSTANDING) == VALID_UNDERSTANDING


def test_understanding_contract_removes_prediction_and_declares_sweep_semantics():
    from server.schemas import load_schema, validate_understanding

    schema = load_schema("understand.schema.json")
    assert "prediction" not in schema["properties"]
    assert "prediction" not in schema["required"]
    parameter = schema["properties"]["primary_parameter"]["anyOf"][1]
    assert parameter["properties"]["sweep_mode"]["enum"] == ["cyclic", "bounce"]
    assert "sweep_mode" in parameter["required"]

    legacy = deepcopy(VALID_UNDERSTANDING)
    legacy["prediction"] = {"prompt": "Predict?", "choices": ["Yes", "No"]}
    with pytest.raises(ValidationError):
        validate_understanding(legacy)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"reasoning": "private"}),
        lambda value: value["primary_parameter"].update({"hidden": True}),
        lambda value: value["checks"][0].update({"debug": "leak"}),
    ],
)
def test_understanding_rejects_extra_fields_at_every_level(mutate):
    from server.schemas import validate_understanding

    candidate = deepcopy(VALID_UNDERSTANDING)
    mutate(candidate)
    with pytest.raises(ValidationError):
        validate_understanding(candidate)


def test_simulatable_understanding_requires_two_independent_checks():
    from server.schemas import ContractError, validate_understanding

    candidate = deepcopy(VALID_UNDERSTANDING)
    candidate["checks"] = candidate["checks"][:1]
    with pytest.raises(ContractError, match="at least two"):
        validate_understanding(candidate)


def test_simulatable_understanding_requires_closed_actor_action_contract():
    from server.schemas import ContractError, validate_understanding

    assert VALID_UNDERSTANDING["action"] == "phases"
    assert VALID_UNDERSTANDING["actor"]["tracking_signature"]["color_rgb"] == [
        255,
        118,
        92,
    ]

    missing_actor = deepcopy(VALID_UNDERSTANDING)
    missing_actor.pop("actor")
    with pytest.raises(ValidationError):
        validate_understanding(missing_actor)

    unknown_action = deepcopy(VALID_UNDERSTANDING)
    unknown_action["action"] = "shimmers"
    with pytest.raises(ValidationError):
        validate_understanding(unknown_action)

    null_actor = deepcopy(VALID_UNDERSTANDING)
    null_actor["actor"] = None
    with pytest.raises(ContractError, match="actor and action"):
        validate_understanding(null_actor)


def test_action_taxonomy_includes_honest_static_parameter_response():
    from server.schemas import load_schema, validate_understanding

    candidate = deepcopy(VALID_UNDERSTANDING)
    candidate["action"] = "responds"

    assert validate_understanding(candidate) == candidate
    actions = load_schema("understand.schema.json")["properties"]["action"]
    assert "responds" in actions["anyOf"][0]["enum"]


def test_action_adapter_contract_rejects_a_static_quantity_for_dynamic_motion():
    from server.schemas import action_contract_report

    candidate = deepcopy(VALID_UNDERSTANDING)
    candidate["action"] = "propagates"
    candidate["actor"]["tracking_output"] = "lit_fraction"

    failures = action_contract_report(candidate)

    assert failures == [
        {
            "gate": "action_contract",
            "code": "dynamic_action_tracking_output_not_time",
            "expected": {
                "action": "propagates",
                "tracking_output_semantics": "positive period or duration",
            },
            "actual": {"tracking_output": "lit_fraction"},
        }
    ]


def test_action_adapter_contract_accepts_static_response_and_orbital_angle():
    from server.schemas import action_contract_report

    response = deepcopy(VALID_UNDERSTANDING)
    response["action"] = "responds"
    assert action_contract_report(response) == []
    assert action_contract_report(VALID_UNDERSTANDING) == []


def test_non_simulatable_understanding_must_not_claim_an_actor_action():
    from server.schemas import ContractError, validate_understanding

    candidate = deepcopy(VALID_UNDERSTANDING)
    candidate["simulatable"] = False
    candidate["primary_parameter"] = None
    candidate["checks"] = []
    candidate["actor"] = None
    candidate["action"] = None
    assert validate_understanding(candidate) == candidate

    candidate["action"] = "phases"
    with pytest.raises(ContractError, match="non-simulatable"):
        validate_understanding(candidate)


def test_misconception_gate_accepts_corrective_copy_and_rejects_a_bare_myth():
    from server.schemas import load_schema
    from server.verify import misconception_report

    misconception_schema = load_schema("understand.schema.json")["properties"]["misconception"]
    assert "corrective learner copy" in misconception_schema["description"]
    assert misconception_report(VALID_UNDERSTANDING) == ([], 1)
    bare_myth = deepcopy(VALID_UNDERSTANDING)
    bare_myth["misconception"] = "زيادة طول البندول تجعله أسرع."
    failures, check_count = misconception_report(bare_myth)

    assert check_count == 1
    assert failures[0]["gate"] == "pedagogy"
    assert failures[0]["code"] == "misconception_not_corrective"


def test_current_frozen_contract_manifest_strictly_matches_repository():
    from scripts.freeze_contracts import build_manifest

    expected = json.loads(
        (ROOT / "contracts" / "contracts-frozen-r11.json").read_text(encoding="utf-8")
    )
    historical = json.loads(
        (ROOT / "out" / "evidence" / "contracts-frozen.json").read_text(encoding="utf-8")
    )

    assert historical["contract_version"] == expected["contract_version"] == "1.0"
    assert expected["freeze_revision"] == 11
    assert build_manifest() == expected


def test_valid_module_output_matches_closed_schema():
    from server.schemas import validate_module_output

    assert validate_module_output(VALID_MODULE_OUTPUT) == VALID_MODULE_OUTPUT


def test_module_output_rejects_extra_field():
    from server.schemas import validate_module_output

    candidate = {**VALID_MODULE_OUTPUT, "html": "<script>bad</script>"}
    with pytest.raises(ValidationError):
        validate_module_output(candidate)


def test_public_event_contract_is_versioned_and_closed():
    from server.schemas import PublicEvent

    event = PublicEvent(
        id=1,
        type="stage",
        job_id="job_123",
        timestamp_ms=1_700_000_000_000,
        payload={"stage": "understanding", "detail": "فهم السؤال", "elapsed_ms": 12},
    )
    assert event.contract_version == "1.0"

    with pytest.raises(PydanticValidationError):
        PublicEvent(
            id=1,
            type="stage",
            job_id="job_123",
            timestamp_ms=1_700_000_000_000,
            payload={},
            raw_prompt="must not leak",
        )


def test_public_result_rejects_unknown_contract_version():
    from server.schemas import PublicResult

    with pytest.raises(PydanticValidationError):
        PublicResult(
            contract_version="2.0",
            job_id="job_123",
            status="complete",
            answer={"tldr": "answer", "key_formula": None},
            simulation=None,
            fallback=None,
        )


def test_shared_simulation_contract_contains_no_question_or_cache_secret_fields():
    from server.schemas import SharedSimulation

    shared = SharedSimulation(
        status="complete",
        answer={"tldr": "answer", "key_formula": None},
        simulation={
            "sim_id": "golden_moon_phases",
            "title": "Moon phases",
            "lang": "en",
            "direction": "ltr",
            "artifact_url": "/api/sims/golden_moon_phases/download",
            "share_url": "/sims/golden_moon_phases",
            "tier": "A",
            "effective_model": "verified/golden",
            "elapsed_ms": 0,
            "check_count": 31,
            "heal_count": 0,
        },
    )

    payload = shared.model_dump()
    assert payload["contract_version"] == "1.0"
    assert "question" not in payload
    assert "key" not in payload
    with pytest.raises(PydanticValidationError):
        SharedSimulation(**payload, question="private learner text")


@pytest.mark.parametrize(
    ("schema_name", "document"),
    [
        (
            "module_fixture.schema.json",
            {
                "contract_version": "1.0",
                "fixture_id": "quarter",
                "kind": "numeric",
                "inputs": {"angle_deg": 90},
                "output": "lit_fraction",
                "expected": 0.5,
                "tolerance": 0.02,
                "unit": "ratio",
            },
        ),
        (
            "verification_report.schema.json",
            {
                "contract_version": "1.0",
                "passed": True,
                "tier": "B",
                "check_count": 7,
                "heal_count": 0,
                "checks": [{"id": "schema", "passed": True, "evidence": "closed schema"}],
                "assumptions": ["simplified orbit"],
            },
        ),
    ],
)
def test_supporting_contracts_are_closed(schema_name, document):
    from server.schemas import load_schema, validate_document

    schema = load_schema(schema_name)
    assert validate_document(document, schema) == document
    with pytest.raises(ValidationError):
        validate_document({**document, "unexpected": True}, schema)
