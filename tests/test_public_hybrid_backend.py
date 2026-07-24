from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from server.codex_runtime import StageExecution
from tests.golden_cases import VALID_UNDERSTANDING
from tests.test_parallel_fragment_generation import PHYSICS_FRAGMENT, VISUAL_FRAGMENT


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute_stage(self, **kwargs: Any) -> StageExecution:
        self.calls.append(kwargs)
        schema_name = kwargs["schema_path"].name
        if schema_name == "physics_fragment.schema.json":
            data = deepcopy(PHYSICS_FRAGMENT)
        elif schema_name == "visual_fragment.schema.json":
            data = deepcopy(VISUAL_FRAGMENT)
        else:
            source = (
                Path(__file__).parent / "fixtures" / "moon_phase_module.js"
            ).read_text(encoding="utf-8")
            data = {
                "module_js": source,
                "output_names": list(
                    VALID_UNDERSTANDING["module_spec"]["outputs"]
                ),
                "brief_summary": "Direct scientific Canvas fixture.",
                "assumptions": ["Deterministic offline fixture"],
            }
        return StageExecution(
            data=data,
            thread_id="offline-public-hybrid",
            model=kwargs["model"],
            elapsed_ms=1,
        )


@pytest.mark.asyncio
async def test_public_hybrid_backend_routes_explicit_fast_gpt_5_6_stages():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.model_lab_discovery import build_discovery_plan
    from server.settings import Settings

    executor = _RecordingExecutor()
    backend = CodexBackend(
        executor=executor,
        settings=Settings(
            physics_model="gpt-5.6-luna",
            visual_model="gpt-5.6-terra",
            public_generation_strategy="hybrid",
        ),
    )
    context = RuntimeContext(public=True)

    physics = await backend.generate_hybrid_physics(
        VALID_UNDERSTANDING,
        runtime_context=context,
    )
    discovery = build_discovery_plan(
        VALID_UNDERSTANDING,
        physics.data,
        source_ids=(),
    ).model_dump(mode="json")
    await asyncio.gather(
        backend.generate_hybrid_visual_plan(
            VALID_UNDERSTANDING,
            physics.data,
            discovery,
            runtime_context=context,
        ),
        backend.generate_hybrid_visual_module(
            VALID_UNDERSTANDING,
            physics.data,
            discovery,
            runtime_context=context,
        ),
    )

    assert [
        (
            call["schema_path"].name,
            call["model"],
            call["effort"],
            call["fast"],
            call["model_lab"],
        )
        for call in executor.calls
    ] == [
        (
            "physics_fragment.schema.json",
            "gpt-5.6-luna",
            "medium",
            True,
            False,
        ),
        (
            "visual_fragment.schema.json",
            "gpt-5.6-terra",
            "medium",
            True,
            False,
        ),
        ("module.schema.json", "gpt-5.6-terra", "medium", True, False),
    ]
    assert all(call["public"] is True for call in executor.calls)
    visual_plan_prompt = next(
        call["prompt"]
        for call in executor.calls
        if call["schema_path"].name == "visual_fragment.schema.json"
    )
    assert "PUBLIC_HYBRID_FIXED_CONTEXT" in visual_plan_prompt
    assert "MODEL_LAB_FIXED_CONTEXT" not in visual_plan_prompt


@pytest.mark.asyncio
async def test_public_direct_canvas_prompt_keeps_full_production_geometry_contract():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.model_lab_discovery import build_discovery_plan
    from server.settings import Settings

    executor = _RecordingExecutor()
    backend = CodexBackend(
        executor=executor,
        settings=Settings(
            physics_model="gpt-5.6-luna",
            visual_model="gpt-5.6-terra",
            public_generation_strategy="hybrid",
        ),
    )
    discovery = build_discovery_plan(
        VALID_UNDERSTANDING,
        PHYSICS_FRAGMENT,
        source_ids=(),
    ).model_dump(mode="json")

    await backend.generate_hybrid_visual_module(
        VALID_UNDERSTANDING,
        PHYSICS_FRAGMENT,
        discovery,
        runtime_context=RuntimeContext(public=True),
    )

    prompt = executor.calls[0]["prompt"]
    assert "LAYSH_PRODUCTION_SCIENTIFIC_CANVAS_V1" in prompt
    assert "isolated Model Lab" not in prompt
    assert "isolated model-comparison lab" not in prompt
    assert "`canvas.__layshSceneGeometry is optional`" not in prompt
    assert "canvas.__layshSceneGeometry" in prompt
    assert 'phase: "post_fit"' in prompt
    assert "required by the production verifier" in prompt
    assert "/* LAYSH_CAUSAL_RESPONSE_V1 */" in prompt
    assert "canvas.__layshActorResponse" in prompt
    assert "simulation.spec.representation" in prompt
    assert "Missing representation evidence fails closed." in prompt


@pytest.mark.asyncio
async def test_public_hybrid_retries_one_transient_nonzero_stage_exit():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.codex_runtime import CodexRuntimeError
    from server.settings import Settings

    class _FailOnceExecutor(_RecordingExecutor):
        async def execute_stage(self, **kwargs: Any) -> StageExecution:
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise CodexRuntimeError(
                    "nonzero_exit",
                    safe_detail={
                        "kind": "process_exit",
                        "model": kwargs["model"],
                    },
                )
            return StageExecution(
                data=deepcopy(PHYSICS_FRAGMENT),
                thread_id="offline-public-hybrid-retry",
                model=kwargs["model"],
                elapsed_ms=2,
            )

    executor = _FailOnceExecutor()
    backend = CodexBackend(
        executor=executor,
        settings=Settings(
            physics_model="gpt-5.6-luna",
            public_generation_strategy="hybrid",
        ),
    )

    result = await backend.generate_hybrid_physics(
        VALID_UNDERSTANDING,
        runtime_context=RuntimeContext(public=True),
    )

    assert len(executor.calls) == 2
    assert result.attempted_models == (
        "gpt-5.6-luna",
        "gpt-5.6-luna",
    )
    assert result.prior_failure_codes == ("nonzero_exit",)
    assert [call["fast"] for call in executor.calls] == [True, True]
    assert [call["model_lab"] for call in executor.calls] == [False, False]


@pytest.mark.asyncio
async def test_public_hybrid_stops_after_two_nonzero_stage_exits():
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.codex_runtime import CodexRuntimeError
    from server.settings import Settings

    class _AlwaysFailExecutor(_RecordingExecutor):
        async def execute_stage(self, **kwargs: Any) -> StageExecution:
            self.calls.append(kwargs)
            raise CodexRuntimeError(
                "nonzero_exit",
                safe_detail={
                    "kind": "process_exit",
                    "model": kwargs["model"],
                },
            )

    executor = _AlwaysFailExecutor()
    backend = CodexBackend(
        executor=executor,
        settings=Settings(
            physics_model="gpt-5.6-luna",
            public_generation_strategy="hybrid",
        ),
    )

    with pytest.raises(CodexRuntimeError, match="nonzero_exit"):
        await backend.generate_hybrid_physics(
            VALID_UNDERSTANDING,
            runtime_context=RuntimeContext(public=True),
        )

    assert len(executor.calls) == 2
    assert [call["model"] for call in executor.calls] == [
        "gpt-5.6-luna",
        "gpt-5.6-luna",
    ]
    assert [call["fast"] for call in executor.calls] == [True, True]
