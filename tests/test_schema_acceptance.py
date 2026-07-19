from pathlib import Path

import pytest

from server.codex_runtime import CodexRuntimeError, StageExecution


class ProbeExecutor:
    def __init__(self, failing_schema: str | None = None):
        self.calls = []
        self.failing_schema = failing_schema

    async def execute_stage(self, **kwargs):
        self.calls.append(kwargs)
        schema_name = Path(kwargs["schema_path"]).name
        if schema_name == self.failing_schema:
            raise CodexRuntimeError(
                "nonzero_exit",
                builder_detail='{"type":"error","message":"invalid_json_schema"}',
            )
        return StageExecution(
            data={},
            thread_id=f"thread-{schema_name}",
            model=kwargs["model"],
            elapsed_ms=12,
        )


@pytest.mark.asyncio
async def test_acceptance_probe_submits_each_bound_schema_on_luna_in_evidence_mode():
    from server.schema_acceptance import OUTPUT_SCHEMA_PROBES, run_schema_probes

    executor = ProbeExecutor()
    outcomes = await run_schema_probes(executor)

    assert set(outcomes) == set(OUTPUT_SCHEMA_PROBES)
    assert all(outcome.accepted for outcome in outcomes.values())
    assert all(call["model"] == "gpt-5.6-luna" for call in executor.calls)
    assert all(call["public"] is False for call in executor.calls)
    assert all(call["evidence_fixture_id"] == "schema_acceptance" for call in executor.calls)
    assert all("Return a valid object" in call["prompt"] for call in executor.calls)


@pytest.mark.asyncio
async def test_acceptance_probe_keeps_builder_diagnostic_and_continues_other_schemas():
    from server.schema_acceptance import run_schema_probes

    executor = ProbeExecutor(failing_schema="module.schema.json")
    outcomes = await run_schema_probes(executor)

    assert len(executor.calls) == 3
    assert outcomes["module"].accepted is False
    assert outcomes["module"].error_code == "nonzero_exit"
    assert "invalid_json_schema" in outcomes["module"].builder_detail
    assert outcomes["understand"].accepted is True
    assert outcomes["qa"].accepted is True
