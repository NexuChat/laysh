from __future__ import annotations

import inspect
import logging
from copy import deepcopy

import pytest

from server.browser_verify import BrowserVerificationResult
from server.codex_backend import MockCodexBackend
from server.jobs import JobManager
from server.verify import VerificationResult


class SequencedHealBackend(MockCodexBackend):
    public_heal_attempt_limit = 2

    def __init__(self) -> None:
        super().__init__()
        self._heal_markers: list[str] = []

    async def generate(self, *args, **kwargs):
        output = await super().generate(*args, **kwargs)
        output["brief_summary"] = "initial"
        return output

    async def heal(self, module_output, understanding, failures, attempt, **kwargs):
        output = await super().heal(
            module_output,
            understanding,
            failures,
            attempt,
            **kwargs,
        )
        output["brief_summary"] = self._heal_markers.pop(0)
        return output


def verification_for(
    marker: str,
    pairs: list[tuple[str, str]],
) -> VerificationResult:
    return VerificationResult(
        passed=not pairs,
        check_count=1,
        failures=[{"gate": gate, "code": code} for gate, code in pairs],
        artifact=f"artifact-{marker}",
        node_report={"marker": marker},
    )


def sequence_verifier(sequence):
    def verify(module_output, _understanding):
        return verification_for(module_output["brief_summary"], sequence.pop(0))

    return verify


def make_manager(backend: SequencedHealBackend) -> JobManager:
    return JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )


@pytest.mark.asyncio
async def test_heal_loop_continues_when_distinct_failure_pairs_strictly_shrink(
    monkeypatch,
):
    from server import pipeline

    backend = SequencedHealBackend()
    backend._heal_markers = ["heal-1", "heal-2"]
    monkeypatch.setattr(
        pipeline,
        "verify_candidate",
        sequence_verifier(
            [
                [("interface", "missing_init"), ("fixtures", "mismatch")],
                [("interface", "missing_init")],
                [],
            ]
        ),
    )

    record = make_manager(backend).start("success", "ar")
    await record.task

    assert record.status == "complete"
    assert backend.heal_calls == 2


@pytest.mark.asyncio
async def test_heal_loop_aborts_on_identical_failure_pairs_without_another_heal(
    monkeypatch,
    caplog,
):
    from server import pipeline

    backend = SequencedHealBackend()
    backend._heal_markers = ["heal-1", "must-not-heal"]
    monkeypatch.setattr(
        pipeline,
        "verify_candidate",
        sequence_verifier(
            [
                [("interface", "missing_init"), ("fixtures", "mismatch")],
                [("interface", "missing_init"), ("fixtures", "mismatch")],
            ]
        ),
    )

    record = make_manager(backend).start("success", "ar")
    await record.task

    assert record.status == "answer_only"
    assert backend.heal_calls == 1
    assert "heal convergence aborted job=" in caplog.text
    assert "reason=no_improvement" in caplog.text


@pytest.mark.asyncio
async def test_heal_loop_aborts_on_new_failure_and_restores_best_snapshot(
    monkeypatch,
    caplog,
):
    from server import pipeline

    backend = SequencedHealBackend()
    backend._heal_markers = ["regressed", "must-not-heal"]
    caplog.set_level(logging.WARNING, logger="server.pipeline")
    monkeypatch.setattr(
        pipeline,
        "verify_candidate",
        sequence_verifier(
            [
                [("interface", "missing_init"), ("fixtures", "mismatch")],
                [("interface", "missing_init"), ("runtime", "crash")],
            ]
        ),
    )
    observed: dict[str, object] = {}
    original_fallback = pipeline._fallback

    def capture_fallback(*args, **kwargs):
        frame = inspect.currentframe()
        assert frame is not None and frame.f_back is not None
        locals_at_abort = frame.f_back.f_locals
        observed.update(
            module_output=deepcopy(locals_at_abort["module_output"]),
            verification=locals_at_abort["verification"],
            browser_evidence=deepcopy(locals_at_abort["browser_evidence"]),
        )
        return original_fallback(*args, **kwargs)

    monkeypatch.setattr(pipeline, "_fallback", capture_fallback)
    record = make_manager(backend).start("success", "ar")
    await record.task

    assert record.status == "answer_only"
    assert backend.heal_calls == 1
    assert observed["module_output"] == {
        "module_js": backend._good_source,
        "output_names": ["lit_fraction"],
        "brief_summary": "initial",
        "assumptions": ["مدار دائري مبسط", "لا تمثل المسافات بمقياس حقيقي"],
    }
    assert observed["verification"].artifact == "artifact-initial"
    assert observed["browser_evidence"] is None
    assert "heal convergence aborted job=" in caplog.text
    assert "reason=regression" in caplog.text
