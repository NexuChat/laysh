from __future__ import annotations

import json
from copy import deepcopy

import pytest

from server.codex_runtime import CodexRuntimeError, StageExecution
from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING


def test_routing_decision_contract_rejects_malformed_document(tmp_path):
    from server.model_routing import load_routing_decision

    decision_path = tmp_path / "routing-decision.json"
    decision_path.write_text('{"schema_version":"1.0"', encoding="utf-8")

    with pytest.raises(ValueError, match="routing_decision_invalid"):
        load_routing_decision(decision_path)


def test_routing_decision_contract_rejects_unknown_tier(tmp_path):
    from server.model_routing import load_routing_decision

    decision_path = tmp_path / "routing-decision.json"
    decision_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "terra_generation_tiers": ["unmeasured-tier"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="routing_decision_invalid"):
        load_routing_decision(decision_path)


def test_routing_decision_rejects_a_known_but_unmeasured_tier(tmp_path):
    from server.model_routing import (
        COMPLEX_OR_MULTI_PARAMETER,
        ModelRoutingPolicy,
        load_routing_decision,
    )

    decision_path = tmp_path / "routing-decision.json"
    decision_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "terra_generation_tiers": [COMPLEX_OR_MULTI_PARAMETER],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="routing_decision_invalid"):
        load_routing_decision(decision_path)

    with pytest.raises(ValueError, match="unmeasured generation routing tiers"):
        ModelRoutingPolicy(
            terra_eligible_tiers=frozenset({COMPLEX_OR_MULTI_PARAMETER})
        )


class RoutingExecutor:
    def __init__(
        self,
        *,
        luna_result=None,
        fallback_result=None,
        fail_model: str | None = None,
        fail_code=None,
    ):
        self.calls: list[dict[str, object]] = []
        self.luna_result = luna_result
        self.fallback_result = fallback_result
        self.fail_model = fail_model
        self.fail_code = fail_code

    async def execute_stage(self, **kwargs):
        self.calls.append(kwargs)
        model = kwargs["model"]
        if model == self.fail_model:
            raise CodexRuntimeError(
                self.fail_code or "stage_timeout",
                safe_detail={"kind": "runtime_error", "model": model},
            )
        schema = kwargs["schema_path"].name
        if schema == "understand.schema.json":
            data = (
                self.luna_result
                if model == "gpt-5.6-luna"
                else self.fallback_result or VALID_UNDERSTANDING
            )
        elif schema == "qa.schema.json":
            data = {
                "approved": True,
                "issues": [],
                "replacement_module_js": None,
                "visual_richness": {
                    "scene_depth": True,
                    "physical_light": True,
                    "idle_motion": True,
                    "reactive_feedback": True,
                    "readable_overlays": True,
                },
            }
        else:
            data = VALID_MODULE_OUTPUT
        return StageExecution(
            data=data,
            thread_id="offline-routing",
            model=model,
            elapsed_ms=7,
        )


def _eligible_policy():
    from server.model_routing import BOUNDED_SINGLE_PARAMETER, ModelRoutingPolicy

    return ModelRoutingPolicy(terra_eligible_tiers=frozenset({BOUNDED_SINGLE_PARAMETER}))


def test_generation_tiers_default_to_direct_sol_until_evidence_enables_terra():
    from server.model_routing import (
        BOUNDED_SINGLE_PARAMETER,
        COMPLEX_OR_MULTI_PARAMETER,
        ModelRoutingPolicy,
        classify_generation_tier,
    )

    policy = ModelRoutingPolicy()
    assert classify_generation_tier(VALID_UNDERSTANDING) == BOUNDED_SINGLE_PARAMETER
    assert policy.generation_model(VALID_UNDERSTANDING) == "gpt-5.6-sol"

    measured = ModelRoutingPolicy(
        terra_eligible_tiers=frozenset({BOUNDED_SINGLE_PARAMETER})
    )
    assert measured.generation_model(VALID_UNDERSTANDING) == "gpt-5.6-terra"

    complex_contract = deepcopy(VALID_UNDERSTANDING)
    complex_contract["secondary_parameter"] = {
        "id": "second_input",
        "label": "مدخل ثانٍ",
        "unit": "ratio",
        "min": 0,
        "max": 1,
        "default": 0.5,
        "step": 0.1,
    }
    assert classify_generation_tier(complex_contract) == COMPLEX_OR_MULTI_PARAMETER
    assert measured.generation_model(complex_contract) == "gpt-5.6-sol"


@pytest.mark.asyncio
async def test_public_luna_classification_failure_retries_once_on_terra():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.settings import Settings

    invalid = deepcopy(VALID_UNDERSTANDING)
    invalid["module_spec"] = {**invalid["module_spec"], "actor": None}
    executor = RoutingExecutor(luna_result=invalid)
    backend = CodexBackend(executor=executor, settings=Settings())

    result = await backend.understand(
        "generic safe science question",
        "en",
        runtime_context=RuntimeContext(public=True),
    )

    assert [call["model"] for call in executor.calls] == [
        "gpt-5.6-luna",
        "gpt-5.6-terra",
    ]
    assert result.model == "gpt-5.6-terra"
    assert result.attempted_models == ("gpt-5.6-luna", "gpt-5.6-terra")
    assert result.prior_failure_codes == ("classification_validation_failed",)
    assert all(call["timeout_seconds"] <= 90 for call in executor.calls)
    assert sum(call["timeout_seconds"] for call in executor.calls) <= 90


@pytest.mark.asyncio
async def test_invalid_terra_understanding_fallback_fails_closed():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.codex_runtime import CodexRuntimeError
    from server.settings import Settings

    invalid = deepcopy(VALID_UNDERSTANDING)
    invalid["module_spec"] = {**invalid["module_spec"], "actor": None}
    executor = RoutingExecutor(luna_result=invalid, fallback_result=invalid)
    backend = CodexBackend(executor=executor, settings=Settings())

    with pytest.raises(CodexRuntimeError, match="classification_validation_failed"):
        await backend.understand(
            "generic safe science question",
            "en",
            runtime_context=RuntimeContext(public=True),
        )

    assert [call["model"] for call in executor.calls] == [
        "gpt-5.6-luna",
        "gpt-5.6-terra",
    ]


@pytest.mark.asyncio
async def test_public_luna_operational_failure_does_not_spend_a_terra_retry():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.settings import Settings

    executor = RoutingExecutor(fail_model="gpt-5.6-luna", fail_code="stage_timeout")
    backend = CodexBackend(executor=executor, settings=Settings())

    with pytest.raises(CodexRuntimeError, match="stage_timeout"):
        await backend.understand(
            "generic safe science question",
            "en",
            runtime_context=RuntimeContext(public=True),
        )

    assert [call["model"] for call in executor.calls] == ["gpt-5.6-luna"]


@pytest.mark.asyncio
async def test_terra_generation_failure_never_starts_a_fresh_sol_generation():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.settings import Settings

    executor = RoutingExecutor(fail_model="gpt-5.6-terra", fail_code="nonzero_exit")
    backend = CodexBackend(
        executor=executor,
        settings=Settings(),
        routing_policy=_eligible_policy(),
    )

    with pytest.raises(CodexRuntimeError, match="nonzero_exit"):
        await backend.generate(
            VALID_UNDERSTANDING,
            runtime_context=RuntimeContext(public=True),
        )

    assert [call["model"] for call in executor.calls] == ["gpt-5.6-terra"]


@pytest.mark.asyncio
async def test_heal_uses_generation_model_then_allows_one_final_sol_attempt():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.settings import Settings

    executor = RoutingExecutor()
    backend = CodexBackend(
        executor=executor,
        settings=Settings(),
        routing_policy=_eligible_policy(),
    )
    context = RuntimeContext(public=True)

    await backend.generate(VALID_UNDERSTANDING, runtime_context=context)
    await backend.heal(
        VALID_MODULE_OUTPUT,
        VALID_UNDERSTANDING,
        [{"gate": "invariant", "code": "fixture_mismatch"}],
        1,
        runtime_context=context,
    )
    await backend.heal(
        VALID_MODULE_OUTPUT,
        VALID_UNDERSTANDING,
        [{"gate": "invariant", "code": "fixture_mismatch"}],
        2,
        runtime_context=context,
    )
    await backend.qa(
        VALID_MODULE_OUTPUT,
        VALID_UNDERSTANDING,
        {"passed": True, "check_count": 10, "gate_names": ["invariant"]},
        runtime_context=context,
    )

    assert [call["model"] for call in executor.calls] == [
        "gpt-5.6-terra",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
        "gpt-5.6-sol",
    ]
    assert [call["effort"] for call in executor.calls] == [
        "medium",
        "medium",
        "high",
        "medium",
    ]
