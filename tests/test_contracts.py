from copy import deepcopy

import pytest
from jsonschema import ValidationError
from pydantic import ValidationError as PydanticValidationError

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING


def test_valid_understanding_matches_closed_schema():
    from server.schemas import validate_understanding

    assert validate_understanding(VALID_UNDERSTANDING) == VALID_UNDERSTANDING


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
