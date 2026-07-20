import pytest

from server.codex_runtime import StageExecution
from tests.golden_cases import VALID_UNDERSTANDING


class VisionRecordingExecutor:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = []

    async def execute_stage(self, **kwargs):
        self.calls.append(kwargs)
        return StageExecution(
            data=self.verdict,
            thread_id="vision-thread",
            model=kwargs["model"],
            elapsed_ms=12,
        )


@pytest.mark.asyncio
async def test_semantic_vision_uses_terra_three_frames_and_closed_judgment(tmp_path):
    from server.codex_backend import CodexBackend, RuntimeContext
    from server.settings import Settings

    verdict = {
        "actor_visible": True,
        "action_performed": True,
        "physically_consistent": True,
        "defects": [],
    }
    executor = VisionRecordingExecutor(verdict)
    backend = CodexBackend(executor=executor, settings=Settings())
    frames = []
    for index in range(3):
        path = tmp_path / f"frame-{index}.png"
        path.write_bytes(b"png")
        frames.append(path)

    result = await backend.vision(
        VALID_UNDERSTANDING,
        frames,
        runtime_context=RuntimeContext(public=False, evidence_fixture_id="moon_phases_ar"),
    )

    assert result.data == verdict
    call = executor.calls[0]
    assert call["model"] == "gpt-5.6-terra"
    assert call["effort"] == "low"
    assert call["schema_path"].name == "vision.schema.json"
    assert call["image_paths"] == frames
    assert "actor_visible" in call["prompt"]
    assert VALID_UNDERSTANDING["actor"]["id"] in call["prompt"]


def test_vision_verdict_failure_becomes_exact_heal_diagnostic():
    from server.vision_verify import evaluate_vision_verdict

    verdict = {
        "actor_visible": True,
        "action_performed": False,
        "physically_consistent": False,
        "defects": ["The landmass remains fixed while only the shadow boundary moves."],
    }
    result = evaluate_vision_verdict(verdict)

    assert result.passed is False
    assert result.failure == {
        "gate": "semantic_vision",
        "code": "semantic_action_not_performed",
        "expected": {
            "actor_visible": True,
            "action_performed": True,
            "physically_consistent": True,
        },
        "actual": verdict,
    }


@pytest.mark.asyncio
async def test_failed_vision_verdict_enters_bounded_heal_loop_with_exact_critique():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    backend = MockCodexBackend()
    verdicts = [
        {
            "actor_visible": True,
            "action_performed": False,
            "physically_consistent": False,
            "defects": ["The actor remains fixed while its shadow changes."],
        },
        {
            "actor_visible": True,
            "action_performed": True,
            "physically_consistent": True,
            "defects": [],
        },
    ]

    async def vision(*_args, **_kwargs):
        return verdicts.pop(0)

    backend.vision = vision
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    record = manager.start("success", "ar")
    await record.task

    assert record.status == "complete"
    assert backend.heal_calls == 1
    assert backend.last_heal_failures[0] == [
        {
            "gate": "semantic_vision",
            "code": "semantic_action_not_performed",
            "expected": {
                "actor_visible": True,
                "action_performed": True,
                "physically_consistent": True,
            },
            "actual": {
                "actor_visible": True,
                "action_performed": False,
                "physically_consistent": False,
                "defects": ["The actor remains fixed while its shadow changes."],
            },
        }
    ]
    assert verdicts == []
