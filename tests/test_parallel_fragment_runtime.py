from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from server.codex_runtime import CodexRuntimeError, StageExecution


class _FailingSiblingExecutor:
    def __init__(self) -> None:
        self.entered = {
            "physics_fragment.schema.json": asyncio.Event(),
            "visual_fragment.schema.json": asyncio.Event(),
        }
        self.cancelled_visual = asyncio.Event()
        self.physics_calls = 0

    async def execute_stage(self, **kwargs):
        schema_name = Path(kwargs["schema_path"]).name
        self.entered[schema_name].set()
        await asyncio.gather(*(event.wait() for event in self.entered.values()))
        if schema_name == "physics_fragment.schema.json":
            self.physics_calls += 1
            raise CodexRuntimeError(
                "nonzero_exit",
                safe_detail={"model": kwargs["model"]},
            )
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled_visual.set()
            raise


@pytest.mark.asyncio
async def test_fragment_generation_cancels_and_awaits_the_sibling_on_failure():
    from server.codex_backend import CodexBackend
    from server.settings import Settings
    from tests.golden_cases import VALID_UNDERSTANDING

    executor = _FailingSiblingExecutor()
    backend = CodexBackend(
        executor=executor,
        settings=Settings(max_parallel_model_calls=2),
    )

    with pytest.raises(CodexRuntimeError, match="nonzero_exit"):
        await asyncio.wait_for(
            backend.generate_fragments(VALID_UNDERSTANDING),
            timeout=1,
        )

    assert executor.cancelled_visual.is_set()
    assert executor.physics_calls == 2


class _TransientPhysicsExecutor:
    def __init__(self) -> None:
        self.calls = {
            "physics_fragment.schema.json": 0,
            "visual_fragment.schema.json": 0,
        }

    async def execute_stage(self, **kwargs):
        from tests.test_parallel_fragment_generation import (
            PHYSICS_FRAGMENT,
            VISUAL_FRAGMENT,
        )

        schema_name = Path(kwargs["schema_path"]).name
        self.calls[schema_name] += 1
        if (
            schema_name == "physics_fragment.schema.json"
            and self.calls[schema_name] == 1
        ):
            raise CodexRuntimeError(
                "nonzero_exit",
                safe_detail={
                    "kind": "process_exit",
                    "model": kwargs["model"],
                    "returncode": 1,
                },
            )
        document = (
            PHYSICS_FRAGMENT
            if schema_name == "physics_fragment.schema.json"
            else VISUAL_FRAGMENT
        )
        return StageExecution(
            data=document,
            thread_id=None,
            model=kwargs["model"],
            elapsed_ms=12,
        )


@pytest.mark.asyncio
async def test_public_fragment_generation_retries_one_transient_role_failure():
    from server.codex_backend import CodexBackend
    from server.settings import Settings
    from tests.golden_cases import VALID_UNDERSTANDING

    executor = _TransientPhysicsExecutor()
    backend = CodexBackend(
        executor=executor,
        settings=Settings(max_parallel_model_calls=2),
    )

    physics, visual = await backend.generate_fragments(VALID_UNDERSTANDING)

    assert executor.calls == {
        "physics_fragment.schema.json": 2,
        "visual_fragment.schema.json": 1,
    }
    assert physics.attempted_models == ("gpt-5.6-sol", "gpt-5.6-sol")
    assert physics.prior_failure_codes == ("nonzero_exit",)
    assert visual.attempted_models == ()


@pytest.mark.parametrize(
    "override",
    [
        {"physics_model": "not-a-gpt56-model"},
        {"visual_model": "not-a-gpt56-model"},
    ],
)
def test_fragment_models_remain_inside_the_gpt56_family(override):
    from server.settings import Settings

    with pytest.raises(ValueError, match="approved GPT-5.6"):
        Settings(**override)
