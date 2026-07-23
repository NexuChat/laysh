from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from server.model_lab_discovery import (
    ModelLabEvidenceBundle,
    ModelLabEvidenceSource,
)
from tests.golden_cases import VALID_UNDERSTANDING
from tests.test_parallel_fragment_generation import (
    PHYSICS_FRAGMENT,
    VISUAL_FRAGMENT,
)


def _module_output() -> dict[str, Any]:
    source = (
        Path(__file__).parent / "fixtures" / "moon_phase_module.js"
    ).read_text(encoding="utf-8")
    return {
        "module_js": source,
        "output_names": list(VALID_UNDERSTANDING["module_spec"]["outputs"]),
        "brief_summary": "A safe direct Canvas simulation.",
        "assumptions": ["Deterministic offline fixture"],
    }


def _pipeline_payload() -> dict[str, Any]:
    return {
        "question": "لماذا يزداد ضغط الماء مع العمق؟",
        "locale": "ar",
        "source_mode": "off",
        "visual_mode": "trusted_scene_plan",
        "stages": {
            "understand": {
                "model": "gpt-5.6-luna",
                "effort": "max",
                "fast": True,
            },
            "physics": {
                "model": "gpt-5.6-terra",
                "effort": "high",
                "fast": False,
            },
            "visual": {
                "model": "gpt-5.6-sol",
                "effort": "ultra",
                "fast": True,
            },
            "repair_1": {
                "model": "gpt-5.6-sol",
                "effort": "medium",
                "fast": True,
            },
            "repair_2": {
                "model": "gpt-5.6-terra",
                "effort": "xhigh",
                "fast": False,
            },
            "qa": {
                "model": "gpt-5.6-luna",
                "effort": "low",
                "fast": True,
            },
        },
    }


def _wait_for_pipeline(
    client: TestClient,
    status_url: str,
    *,
    revision: int = 1,
    timeout: float = 5.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(status_url)
        assert response.status_code == 200
        document = response.json()
        if (
            document["revision"] >= revision
            and document["status"] in {
                "complete",
                "rejected",
                "failed",
                "cancelled",
            }
        ):
            return document
        time.sleep(0.01)
    raise AssertionError("model-lab pipeline did not finish")


class _PipelineBackend:
    backend_name = "mock"

    def __init__(self, *, break_first_visual: bool = False) -> None:
        from server.settings import Settings

        self.settings = Settings(max_parallel_model_calls=2)
        self.break_first_visual = break_first_visual
        self.calls: list[tuple[str, str, str, bool]] = []
        self.heal_failures: list[list[dict[str, Any]]] = []
        self.received_evidence: list[dict[str, Any]] = []
        self.received_discovery: list[dict[str, Any]] = []

    @staticmethod
    def _record_spec(stage: str, spec: Any) -> tuple[str, str, str, bool]:
        return stage, spec.model, spec.effort, spec.fast

    async def understand_for_lab(
        self,
        question,
        locale,
        *,
        model,
        effort,
        fast,
        evidence=None,
        runtime_context=None,
    ):
        del question, runtime_context
        self.calls.append(("understand", model, effort, fast))
        self.received_evidence.append(deepcopy(evidence or {}))
        document = deepcopy(VALID_UNDERSTANDING)
        document["lang"] = locale or "ar"
        if document["lang"] == "en":
            document.update(
                {
                    "title": "Why does water pressure increase with depth?",
                    "tldr": "Water pressure rises as the weight of water above increases.",
                    "learning_objective": "Connect depth to pressure.",
                    "prediction": {
                        "prompt": "Where will pressure be greater?",
                        "choices": ["Deeper", "Shallower"],
                    },
                    "misconception": (
                        "Correction: pressure depends on depth, not only container width."
                    ),
                    "explanation_prompt": "Explain what changed and why.",
                    "transfer_prompt": "Predict the pressure at twice the depth.",
                }
            )
        return document

    async def generate_physics_for_lab(
        self,
        understanding,
        *,
        stage_spec,
        runtime_context=None,
    ):
        del understanding, runtime_context
        self.calls.append(self._record_spec("physics", stage_spec))
        return deepcopy(PHYSICS_FRAGMENT)

    async def generate_visual_module_for_lab(
        self,
        understanding,
        physics_document,
        *,
        stage_spec,
        discovery_plan=None,
        runtime_context=None,
    ):
        del understanding, physics_document, runtime_context
        self.received_discovery.append(deepcopy(discovery_plan or {}))
        self.calls.append(self._record_spec("visual", stage_spec))
        module = _module_output()
        if self.break_first_visual:
            module["module_js"] = module["module_js"].replace(
                "return { lit_fraction: state.lit_fraction };",
                "return { lit_fraction: 0 };",
            )
        return module

    async def generate_visual_plan_for_lab(
        self,
        understanding,
        physics_document,
        discovery_plan,
        *,
        stage_spec,
        runtime_context=None,
    ):
        del understanding, physics_document, runtime_context
        self.received_discovery.append(deepcopy(discovery_plan))
        self.calls.append(self._record_spec("visual", stage_spec))
        return deepcopy(VISUAL_FRAGMENT)

    async def heal_for_lab(
        self,
        module_output,
        understanding,
        failures,
        attempt,
        *,
        stage_spec,
        runtime_context=None,
    ):
        del module_output, understanding, attempt, runtime_context
        self.calls.append(self._record_spec(f"repair_{len(self.heal_failures) + 1}", stage_spec))
        self.heal_failures.append(deepcopy(failures))
        return _module_output()

    async def qa_for_lab(
        self,
        module_output,
        understanding,
        gate_outcome,
        *,
        stage_spec,
        runtime_context=None,
    ):
        del module_output, understanding, gate_outcome, runtime_context
        self.calls.append(self._record_spec("qa", stage_spec))
        return {
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


def _enabled_client(
    monkeypatch,
    backend: Any,
    *,
    evidence_provider: Any | None = None,
) -> TestClient:
    from server.app import create_app
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend

    monkeypatch.setenv("LAYSH_MODEL_LAB_ENABLED", "1")
    return TestClient(
        create_app(
            backend=MockCodexBackend(),
            model_lab_backend=backend,
            model_lab_evidence_provider=evidence_provider,
            browser_verifier=lambda _: BrowserVerificationResult.passing(),
        )
    )


def test_pipeline_runs_every_applicable_stage_and_exposes_only_safe_outputs(monkeypatch):
    backend = _PipelineBackend()
    with _enabled_client(monkeypatch, backend) as client:
        accepted = client.post("/api/model-lab/pipeline", json=_pipeline_payload())
        assert accepted.status_code == 202
        run = _wait_for_pipeline(client, accepted.json()["status_url"])

        assert run["status"] == "complete"
        assert run["artifact_url"]
        assert client.get(run["artifact_url"]).status_code == 200
        assert [
            event["stage"]
            for event in run["timeline"]
            if event["revision"] == 1
        ] == [
            "evidence",
            "understand",
            "physics",
            "plan",
            "visual",
            "verify",
            "browser",
            "repair_1",
            "repair_2",
            "qa",
            "finalize",
        ]
        assert {
            event["status"]
            for event in run["timeline"]
            if event["stage"] in {"repair_1", "repair_2"}
        } == {"skipped"}
        serialized = str(run)
        assert "module_js" not in serialized
        assert "reasoning" not in serialized
        assert run["timeline"][0]["output"]["summary"]
        assert next(
            event for event in run["timeline"] if event["stage"] == "physics"
        )["output"]["expressions"]
        assert next(
            event for event in run["timeline"] if event["stage"] == "visual"
        )["output"]["summary"]
        plan = next(
            event for event in run["timeline"] if event["stage"] == "plan"
        )["output"]["discovery"]
        assert plan["learning_cycle"]["prediction"]
        assert plan["learning_cycle"]["observe"]
        assert plan["learning_cycle"]["explain"]
        assert plan["learning_cycle"]["transfer"]
        assert plan["representation"]["renderer"] == "canvas_2d"
        assert {reference["provider"] for reference in plan["related_references"]} == {
            "phet",
            "nasa",
        }
        assert all(
            reference["usage"] == "linked_reference"
            for reference in plan["related_references"]
        )
        assert run["source_mode"] == "off"
        assert run["visual_mode"] == "trusted_scene_plan"

    assert backend.calls == [
        ("understand", "gpt-5.6-luna", "max", True),
        ("physics", "gpt-5.6-terra", "high", False),
        ("visual", "gpt-5.6-sol", "ultra", True),
        ("qa", "gpt-5.6-luna", "low", True),
    ]
    assert backend.received_evidence == [
        {
            "mode": "off",
            "locale": "ar",
            "status": "skipped",
            "sources": [],
        }
    ]
    assert backend.received_discovery[0]["locale"] == "ar"


def test_rerunning_physics_reexecutes_it_and_every_dependent_stage_only(monkeypatch):
    backend = _PipelineBackend()
    with _enabled_client(monkeypatch, backend) as client:
        accepted = client.post("/api/model-lab/pipeline", json=_pipeline_payload())
        initial = _wait_for_pipeline(client, accepted.json()["status_url"])
        initial_call_count = len(backend.calls)

        rerun = client.post(
            f"/api/model-lab/pipeline/{initial['run_id']}/rerun",
            json={
                "stage": "physics",
                "config": {
                    "model": "gpt-5.6-sol",
                    "effort": "xhigh",
                    "fast": False,
                },
            },
        )
        assert rerun.status_code == 202
        revised = _wait_for_pipeline(
            client,
            rerun.json()["status_url"],
            revision=2,
        )

    assert backend.calls[initial_call_count:] == [
        ("physics", "gpt-5.6-sol", "xhigh", False),
        ("visual", "gpt-5.6-sol", "ultra", True),
        ("qa", "gpt-5.6-luna", "low", True),
    ]
    assert [
        event["stage"]
        for event in revised["timeline"]
        if event["revision"] == 2
    ] == [
        "physics",
        "plan",
        "visual",
        "verify",
        "browser",
        "repair_1",
        "repair_2",
        "qa",
        "finalize",
    ]
    assert revised["stages"]["physics"] == {
        "model": "gpt-5.6-sol",
        "effort": "xhigh",
        "fast": False,
    }


def test_each_rerunnable_stage_preserves_prior_inputs_and_cascades_forward(monkeypatch):
    backend = _PipelineBackend()
    with _enabled_client(monkeypatch, backend) as client:
        accepted = client.post("/api/model-lab/pipeline", json=_pipeline_payload())
        run = _wait_for_pipeline(client, accepted.json()["status_url"])

        cases = [
            ("plan", None, ["visual", "qa"]),
            (
                "visual",
                {
                    "model": "gpt-5.6-terra",
                    "effort": "medium",
                    "fast": False,
                },
                ["visual", "qa"],
            ),
            ("verify", None, ["qa"]),
            (
                "qa",
                {
                    "model": "gpt-5.6-sol",
                    "effort": "high",
                    "fast": True,
                },
                ["qa"],
            ),
            ("browser", None, ["qa"]),
            ("finalize", None, []),
            (
                "evidence",
                None,
                ["understand", "physics", "visual", "qa"],
            ),
            (
                "understand",
                {
                    "model": "gpt-5.6-terra",
                    "effort": "low",
                    "fast": False,
                },
                ["understand", "physics", "visual", "qa"],
            ),
        ]
        for stage, config, expected_calls in cases:
            before = len(backend.calls)
            response = client.post(
                f"/api/model-lab/pipeline/{run['run_id']}/rerun",
                json={"stage": stage, "config": config},
            )
            assert response.status_code == 202
            run = _wait_for_pipeline(
                client,
                response.json()["status_url"],
                revision=run["revision"] + 1,
            )
            assert [call[0] for call in backend.calls[before:]] == expected_calls


def test_failed_verification_runs_configured_repair_then_reverifies(monkeypatch):
    backend = _PipelineBackend(break_first_visual=True)
    payload = _pipeline_payload()
    payload["visual_mode"] = "direct_canvas"
    with _enabled_client(monkeypatch, backend) as client:
        accepted = client.post("/api/model-lab/pipeline", json=payload)
        run = _wait_for_pipeline(client, accepted.json()["status_url"])

    assert run["status"] == "complete"
    assert run["artifact_tier"] == "verified"
    assert [call[0] for call in backend.calls] == [
        "understand",
        "physics",
        "visual",
        "repair_1",
        "qa",
    ]
    assert backend.heal_failures
    assert any(
        failure.get("expected") is not None and failure.get("actual") is not None
        for failure in backend.heal_failures[0]
    )
    revision_events = [
        event for event in run["timeline"] if event["revision"] == 1
    ]
    assert [event["stage"] for event in revision_events].count("verify") == 2
    assert next(
        event for event in revision_events if event["stage"] == "repair_1"
    )["status"] == "passed"
    assert next(
        event for event in revision_events if event["stage"] == "repair_2"
    )["status"] == "skipped"


def test_pipeline_contract_supports_real_efforts_and_rejects_luna_ultra(monkeypatch):
    with _enabled_client(monkeypatch, _PipelineBackend()) as client:
        valid = _pipeline_payload()
        assert client.post("/api/model-lab/pipeline", json=valid).status_code == 202

        invalid = _pipeline_payload()
        invalid["stages"]["understand"]["effort"] = "ultra"
        assert client.post("/api/model-lab/pipeline", json=invalid).status_code == 422

        extra = _pipeline_payload()
        extra["stages"]["visual"]["debug"] = True
        assert client.post("/api/model-lab/pipeline", json=extra).status_code == 422

        invalid_mode = _pipeline_payload()
        invalid_mode["visual_mode"] = "hidden_custom_renderer"
        assert client.post("/api/model-lab/pipeline", json=invalid_mode).status_code == 422


def test_hybrid_race_generates_two_visual_strategies_concurrently_and_returns_one(
    monkeypatch,
):
    class _RacingBackend(_PipelineBackend):
        def __init__(self) -> None:
            super().__init__()
            self.active_visuals = 0
            self.peak_visuals = 0

        async def _visual_delay(self) -> None:
            self.active_visuals += 1
            self.peak_visuals = max(self.peak_visuals, self.active_visuals)
            try:
                await asyncio.sleep(0.05)
            finally:
                self.active_visuals -= 1

        async def generate_visual_plan_for_lab(self, *args, **kwargs):
            await self._visual_delay()
            return await super().generate_visual_plan_for_lab(*args, **kwargs)

        async def generate_visual_module_for_lab(self, *args, **kwargs):
            await self._visual_delay()
            return await super().generate_visual_module_for_lab(*args, **kwargs)

    backend = _RacingBackend()
    payload = _pipeline_payload()
    payload["visual_mode"] = "hybrid_race"
    with _enabled_client(monkeypatch, backend) as client:
        accepted = client.post("/api/model-lab/pipeline", json=payload)
        assert accepted.status_code == 202
        run = _wait_for_pipeline(client, accepted.json()["status_url"])

    assert run["status"] == "complete"
    assert run["artifact_tier"] == "verified"
    assert backend.peak_visuals == 2
    assert [call[0] for call in backend.calls].count("visual") == 2
    assert "qa" not in [call[0] for call in backend.calls]
    visual = next(event for event in run["timeline"] if event["stage"] == "visual")
    assert visual["output"]["details"] == [
        "2 parallel visual strategies",
        "selected direct_canvas",
    ]
    qa = next(event for event in run["timeline"] if event["stage"] == "qa")
    assert qa["status"] == "skipped"
    assert "first-pass" in qa["output"]["summary"].lower()


def test_pipeline_cancel_endpoint_cancels_the_active_backend_task(monkeypatch):
    class _CancellableBackend(_PipelineBackend):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def understand_for_lab(self, *args, **kwargs):
            self.started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
            return await super().understand_for_lab(*args, **kwargs)

    backend = _CancellableBackend()
    with _enabled_client(monkeypatch, backend) as client:
        accepted = client.post("/api/model-lab/pipeline", json=_pipeline_payload())
        run_id = accepted.json()["run_id"]
        deadline = time.monotonic() + 2
        while not backend.started.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert backend.started.is_set()

        cancelled = client.post(f"/api/model-lab/pipeline/{run_id}/cancel")
        assert cancelled.status_code == 200
        run = _wait_for_pipeline(client, accepted.json()["status_url"])

    assert run["status"] == "cancelled"
    assert run["active_stage"] is None
    assert backend.cancelled.is_set()


def test_pipeline_rerun_refuses_overlapping_execution(monkeypatch):
    class _SlowBackend(_PipelineBackend):
        async def understand_for_lab(self, *args, **kwargs):
            await asyncio.sleep(0.08)
            return await super().understand_for_lab(*args, **kwargs)

    with _enabled_client(monkeypatch, _SlowBackend()) as client:
        accepted = client.post("/api/model-lab/pipeline", json=_pipeline_payload())
        run_id = accepted.json()["run_id"]
        response = client.post(
            f"/api/model-lab/pipeline/{run_id}/rerun",
            json={
                "stage": "visual",
                "config": {
                    "model": "gpt-5.6-terra",
                    "effort": "medium",
                    "fast": True,
                },
            },
        )
        assert response.status_code == 409


def test_public_reference_evidence_is_opt_in_and_grounding_reaches_the_plan(monkeypatch):
    class _EvidenceProvider:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def collect(self, question: str, locale: str) -> ModelLabEvidenceBundle:
            self.calls.append((question, locale))
            return ModelLabEvidenceBundle(
                mode="public_references",
                locale=locale,
                status="ready",
                sources=[
                    ModelLabEvidenceSource(
                        source_id="wikipedia:42",
                        provider="wikipedia",
                        title="Water pressure",
                        summary="Pressure in a fluid increases with depth.",
                        url="https://en.wikipedia.org/wiki/Pressure",
                        language="en",
                        license="CC BY-SA; see source page",
                    )
                ],
            )

    backend = _PipelineBackend()
    provider = _EvidenceProvider()
    payload = _pipeline_payload()
    payload["question"] = "Why does water pressure increase with depth?"
    payload["locale"] = "en"
    payload["source_mode"] = "public_references"
    with _enabled_client(
        monkeypatch,
        backend,
        evidence_provider=provider,
    ) as client:
        accepted = client.post("/api/model-lab/pipeline", json=payload)
        run = _wait_for_pipeline(client, accepted.json()["status_url"])

    assert provider.calls == [(payload["question"], "en")]
    evidence_event = next(
        event for event in run["timeline"] if event["stage"] == "evidence"
    )
    assert evidence_event["status"] == "passed"
    assert evidence_event["output"]["sources"][0]["source_id"] == "wikipedia:42"
    assert backend.received_evidence[0]["sources"][0]["source_id"] == "wikipedia:42"
    plan_event = next(event for event in run["timeline"] if event["stage"] == "plan")
    assert plan_event["output"]["discovery"]["source_ids"] == ["wikipedia:42"]


def test_source_mode_off_never_calls_an_injected_public_provider(monkeypatch):
    class _ForbiddenProvider:
        async def collect(self, question: str, locale: str):
            del question, locale
            raise AssertionError("off mode must not call a public reference provider")

    with _enabled_client(
        monkeypatch,
        _PipelineBackend(),
        evidence_provider=_ForbiddenProvider(),
    ) as client:
        accepted = client.post("/api/model-lab/pipeline", json=_pipeline_payload())
        run = _wait_for_pipeline(client, accepted.json()["status_url"])

    assert run["status"] == "complete"
