import json
from pathlib import Path

import pytest

from server.codex_runtime import StageExecution
from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING


class RecordingExecutor:
    def __init__(self):
        self.calls = []

    async def execute_stage(self, **kwargs):
        self.calls.append(kwargs)
        schema_name = kwargs["schema_path"].name
        if schema_name == "understand.schema.json":
            data = VALID_UNDERSTANDING
        elif schema_name == "qa.schema.json":
            data = {"approved": True, "issues": [], "replacement_module_js": None}
        else:
            data = VALID_MODULE_OUTPUT
        return StageExecution(
            data=data,
            thread_id="evidence-thread-123",
            model=kwargs["model"],
            elapsed_ms=17,
        )


@pytest.mark.asyncio
async def test_understand_is_one_luna_call_with_closed_schema_and_zero_echo_prompt():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.settings import Settings

    executor = RecordingExecutor()
    backend = CodexBackend(executor=executor, settings=Settings())
    result = await backend.understand(
        "ليش القمر يتغير شكله؟",
        "ar",
        runtime_context=RuntimeContext(public=True),
    )

    assert result.data == VALID_UNDERSTANDING
    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert call["model"] == "gpt-5.6-luna"
    assert call["effort"] == "low"
    assert call["schema_path"].name == "understand.schema.json"
    assert "ONE structured call" in call["prompt"]
    assert "Never echo unsafe input" in call["prompt"]
    assert "ليش القمر يتغير شكله؟" in call["prompt"]
    assert call["public"] is True


@pytest.mark.asyncio
async def test_generate_heal_and_qa_route_only_to_sol_with_bounded_effort():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.settings import Settings

    executor = RecordingExecutor()
    backend = CodexBackend(executor=executor, settings=Settings())
    context = RuntimeContext(public=False, evidence_fixture_id="moon_phases_ar")

    await backend.generate(VALID_UNDERSTANDING, runtime_context=context)
    await backend.heal(
        VALID_MODULE_OUTPUT,
        VALID_UNDERSTANDING,
        ["fixture_failed"],
        1,
        runtime_context=context,
    )
    await backend.heal(
        VALID_MODULE_OUTPUT,
        VALID_UNDERSTANDING,
        ["fixture_failed"],
        2,
        runtime_context=context,
    )
    await backend.qa(VALID_MODULE_OUTPUT, VALID_UNDERSTANDING, runtime_context=context)

    assert [call["model"] for call in executor.calls] == ["gpt-5.6-sol"] * 4
    assert [call["effort"] for call in executor.calls] == ["medium", "medium", "high", "medium"]
    assert [call["schema_path"].name for call in executor.calls] == [
        "module.schema.json",
        "module.schema.json",
        "module.schema.json",
        "qa.schema.json",
    ]
    assert all(call["public"] is False for call in executor.calls)
    assert all(call["evidence_fixture_id"] == "moon_phases_ar" for call in executor.calls)
    assert "full HTML" in executor.calls[0]["prompt"]
    assert "exact gate failures" in executor.calls[1]["prompt"]


def test_twenty_dialect_arabizi_and_code_switch_fixtures_share_stable_intent(backend):
    cases = json.loads(
        (Path(__file__).parent / "fixtures" / "normalization_cases.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(cases) == 20
    observed = {backend.normalize_fixture(case["question"])["canonical_intent"] for case in cases}
    assert observed == {"moon_phase_lit_fraction"}
    assert {case["lang"] for case in cases} == {"ar", "en"}


def test_qa_schema_is_closed():
    from jsonschema import ValidationError

    from server.schemas import load_schema, validate_document

    valid = {"approved": True, "issues": [], "replacement_module_js": None}
    schema = load_schema("qa.schema.json")
    assert validate_document(valid, schema) == valid
    with pytest.raises(ValidationError):
        validate_document({**valid, "reasoning": "private"}, schema)
