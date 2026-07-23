from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from server.codex_runtime import CodexRuntimeError


class _FailingSiblingExecutor:
    def __init__(self) -> None:
        self.entered = {
            "physics_fragment.schema.json": asyncio.Event(),
            "visual_fragment.schema.json": asyncio.Event(),
        }
        self.cancelled_visual = asyncio.Event()

    async def execute_stage(self, **kwargs):
        schema_name = Path(kwargs["schema_path"]).name
        self.entered[schema_name].set()
        await asyncio.gather(*(event.wait() for event in self.entered.values()))
        if schema_name == "physics_fragment.schema.json":
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
