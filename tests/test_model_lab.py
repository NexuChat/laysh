from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import wait_for_terminal
from tests.golden_cases import VALID_UNDERSTANDING
from tests.test_parallel_fragment_generation import PHYSICS_FRAGMENT, VISUAL_FRAGMENT


def _wait_for_lab_run(client: TestClient, status_url: str, timeout: float = 4.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(status_url)
        assert response.status_code == 200
        document = response.json()
        if document["status"] in {"complete", "rejected", "failed"}:
            return document
        time.sleep(0.01)
    raise AssertionError("model-lab run did not finish")


class _ComparingBackend:
    backend_name = "mock"

    def __init__(self, *, reject_luna: bool = False) -> None:
        from server.settings import Settings

        self.settings = Settings(max_parallel_model_calls=2)
        self.reject_luna = reject_luna
        self.understand_calls: list[tuple[str, str]] = []
        self.fragment_calls: list[tuple[str, str, str, str]] = []
        self.heal_calls = 0
        self.qa_calls = 0
        self.active_generations = 0
        self.peak_generations = 0
        self._both_started = asyncio.Event()

    async def understand_for_lab(
        self,
        question,
        locale,
        *,
        model,
        effort,
        runtime_context=None,
    ):
        del question, runtime_context
        self.understand_calls.append((model, effort))
        document = deepcopy(VALID_UNDERSTANDING)
        document["lang"] = locale or "ar"
        return document

    async def generate_fragments_for_lab(
        self,
        understanding,
        *,
        physics_spec,
        visual_spec,
        runtime_context=None,
    ):
        del understanding, runtime_context
        self.fragment_calls.append(
            (
                physics_spec.model,
                physics_spec.effort,
                visual_spec.model,
                visual_spec.effort,
            )
        )
        self.active_generations += 1
        self.peak_generations = max(self.peak_generations, self.active_generations)
        if self.active_generations == 2:
            self._both_started.set()
        try:
            await asyncio.wait_for(self._both_started.wait(), timeout=1)
            physics = deepcopy(PHYSICS_FRAGMENT)
            visual = deepcopy(VISUAL_FRAGMENT)
            if self.reject_luna and physics_spec.model == "gpt-5.6-luna":
                visual["causal_response"]["actor_id"] = "missing"
            return physics, visual
        finally:
            self.active_generations -= 1


def _enabled_client(monkeypatch, backend: Any):
    from server.app import create_app
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend

    monkeypatch.setenv("LAYSH_MODEL_LAB_ENABLED", "1")
    return TestClient(
        create_app(
            backend=MockCodexBackend(),
            model_lab_backend=backend,
            browser_verifier=lambda _: BrowserVerificationResult.passing(),
        )
    )


def _comparison_payload() -> dict:
    return {
        "question": "لماذا يزداد ضغط الماء مع العمق؟",
        "locale": "ar",
        "understand": {"model": "gpt-5.6-terra", "effort": "medium"},
        "candidates": [
            {
                "physics": {"model": "gpt-5.6-luna", "effort": "low"},
                "visual": {"model": "gpt-5.6-terra", "effort": "medium"},
            },
            {
                "physics": {"model": "gpt-5.6-sol", "effort": "high"},
                "visual": {"model": "gpt-5.6-sol", "effort": "high"},
            },
        ],
    }


def test_model_lab_is_disabled_by_default(client):
    assert client.get("/model-lab").status_code == 404
    assert client.post("/api/model-lab/compare", json=_comparison_payload()).status_code == 404


def test_model_lab_page_is_separate_and_has_closed_comparison_controls(monkeypatch):
    with _enabled_client(monkeypatch, _ComparingBackend()) as client:
        response = client.get("/model-lab")

    assert response.status_code == 200
    assert 'id="model-lab-form"' in response.text
    assert 'name="question"' in response.text
    assert response.text.count('name="model"') == 5
    assert response.text.count('name="effort"') == 5
    assert 'data-role="understand"' in response.text
    assert response.text.count('data-role="physics"') == 2
    assert response.text.count('data-role="visual"') == 2
    assert "/api/model-lab/compare" not in response.text
    assert 'href="/"' in response.text


def test_model_lab_understands_once_and_compares_two_verified_candidates_concurrently(
    monkeypatch,
):
    backend = _ComparingBackend()
    with _enabled_client(monkeypatch, backend) as client:
        accepted = client.post("/api/model-lab/compare", json=_comparison_payload())
        assert accepted.status_code == 202
        run = _wait_for_lab_run(client, accepted.json()["status_url"])

        assert run["status"] == "complete"
        assert run["answer"]["tldr"]
        assert run["understand_elapsed_ms"] >= 0
        assert [
            (
                candidate["physics_model"],
                candidate["physics_effort"],
                candidate["visual_model"],
                candidate["visual_effort"],
                candidate["status"],
            )
            for candidate in run["candidates"]
        ] == [
            (
                "gpt-5.6-luna",
                "low",
                "gpt-5.6-terra",
                "medium",
                "verified",
            ),
            ("gpt-5.6-sol", "high", "gpt-5.6-sol", "high", "verified"),
        ]
        assert all(candidate["artifact_url"] for candidate in run["candidates"])
        assert all(candidate["check_count"] > 0 for candidate in run["candidates"])
        assert all(
            client.get(candidate["artifact_url"]).status_code == 200
            for candidate in run["candidates"]
        )
        assert client.app.state.jobs.artifacts == {}

    assert backend.understand_calls == [("gpt-5.6-terra", "medium")]
    assert backend.fragment_calls == [
        ("gpt-5.6-luna", "low", "gpt-5.6-terra", "medium"),
        ("gpt-5.6-sol", "high", "gpt-5.6-sol", "high"),
    ]
    assert backend.peak_generations == 2
    assert backend.heal_calls == 0
    assert backend.qa_calls == 0


def test_model_lab_does_not_mutate_or_route_through_the_learner_backend(monkeypatch):
    from server.app import create_app
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend

    learner_backend = MockCodexBackend()
    lab_backend = _ComparingBackend()
    monkeypatch.setenv("LAYSH_MODEL_LAB_ENABLED", "1")
    with TestClient(
        create_app(
            backend=learner_backend,
            model_lab_backend=lab_backend,
            browser_verifier=lambda _: BrowserVerificationResult.passing(),
        )
    ) as client:
        accepted = client.post("/api/model-lab/compare", json=_comparison_payload())
        _wait_for_lab_run(client, accepted.json()["status_url"])

        assert client.app.state.jobs.backend is learner_backend
        assert client.app.state.model_lab.backend is lab_backend
        assert client.app.state.jobs.artifacts == {}
        assert learner_backend.understand_calls == 0
        assert learner_backend.generate_calls == 0

        learner_job = client.post(
            "/api/ask",
            json={"question": "success", "locale": "ar"},
        )
        learner_result = wait_for_terminal(client, learner_job.json()["job_id"])
        assert learner_result["status"] == "complete"
        assert learner_backend.understand_calls == 1
        assert learner_backend.generate_calls == 1
        assert lab_backend.understand_calls == [("gpt-5.6-terra", "medium")]
        assert len(lab_backend.fragment_calls) == 2


def test_enabled_codex_lab_owns_a_distinct_backend_executor_and_semaphore(monkeypatch):
    from server.app import create_app
    from server.codex_backend import CodexBackend

    monkeypatch.setenv("LAYSH_CODEX_BACKEND", "codex")
    monkeypatch.setenv("LAYSH_MODEL_LAB_ENABLED", "1")
    app = create_app()

    learner_backend = app.state.jobs.backend
    lab_backend = app.state.model_lab.backend
    assert isinstance(learner_backend, CodexBackend)
    assert isinstance(lab_backend, CodexBackend)
    assert lab_backend is not learner_backend
    assert lab_backend.executor is not learner_backend.executor
    assert lab_backend._model_slots is not learner_backend._model_slots


def test_model_lab_withholds_rejected_candidate_and_exposes_only_safe_gate_names(
    monkeypatch,
):
    backend = _ComparingBackend(reject_luna=True)
    with _enabled_client(monkeypatch, backend) as client:
        accepted = client.post("/api/model-lab/compare", json=_comparison_payload())
        run = _wait_for_lab_run(client, accepted.json()["status_url"])

        rejected, verified = run["candidates"]
        assert rejected["status"] == "rejected"
        assert rejected["artifact_url"] is None
        assert "generation_contract" in rejected["failed_gates"]
        assert "failures" not in rejected
        assert verified["status"] == "verified"
        assert verified["artifact_url"]


def test_model_lab_contract_rejects_unknown_models_efforts_and_extra_fields(monkeypatch):
    with _enabled_client(monkeypatch, _ComparingBackend()) as client:
        invalid_model = _comparison_payload()
        invalid_model["candidates"][0]["physics"]["model"] = "not-approved-model"
        assert client.post("/api/model-lab/compare", json=invalid_model).status_code == 422

        invalid_effort = _comparison_payload()
        invalid_effort["understand"]["effort"] = "ultra"
        assert client.post("/api/model-lab/compare", json=invalid_effort).status_code == 422

        extra_field = _comparison_payload()
        extra_field["debug"] = True
        assert client.post("/api/model-lab/compare", json=extra_field).status_code == 422


class _RecordingLabExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute_stage(self, **kwargs):
        from server.codex_runtime import StageExecution

        self.calls.append(kwargs)
        documents = {
            "understand.schema.json": VALID_UNDERSTANDING,
            "physics_fragment.schema.json": PHYSICS_FRAGMENT,
            "visual_fragment.schema.json": VISUAL_FRAGMENT,
        }
        return StageExecution(
            data=deepcopy(documents[kwargs["schema_path"].name]),
            thread_id=None,
            model=kwargs["model"],
            elapsed_ms=7,
        )


async def _exercise_explicit_lab_routing():
    from server.codex_backend import CodexBackend, RuntimeContext, StageModelSpec
    from server.settings import Settings

    executor = _RecordingLabExecutor()
    backend = CodexBackend(executor=executor, settings=Settings())
    context = RuntimeContext(public=True)

    await backend.understand_for_lab(
        "Why?",
        "en",
        model="gpt-5.6-luna",
        effort="high",
        runtime_context=context,
    )
    await backend.generate_fragments_for_lab(
        VALID_UNDERSTANDING,
        physics_spec=StageModelSpec("gpt-5.6-sol", "low"),
        visual_spec=StageModelSpec("gpt-5.6-terra", "high"),
        runtime_context=context,
    )
    return executor.calls


def test_codex_model_lab_passes_each_selected_model_and_effort_explicitly():
    calls = asyncio.run(_exercise_explicit_lab_routing())

    assert {
        call["schema_path"].name: (call["model"], call["effort"])
        for call in calls
    } == {
        "understand.schema.json": ("gpt-5.6-luna", "high"),
        "physics_fragment.schema.json": ("gpt-5.6-sol", "low"),
        "visual_fragment.schema.json": ("gpt-5.6-terra", "high"),
    }
    assert all(call["public"] is True for call in calls)
