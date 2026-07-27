from __future__ import annotations

import inspect
import json
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


@pytest.mark.asyncio
async def test_convergence_abort_gives_up_like_natural_heal_exhaustion(monkeypatch):
    """The early abort shortens the loop; it must not change the terminal contract.

    Aborting on a non-converging heal is a *give up*, not a shortcut to shipping.
    It has to land exactly where natural heal exhaustion lands: the textual answer
    is preserved for the learner, and the candidate that never passed verification
    stays invisible — no artifact on the record, no simulation on the public
    payload, nothing registered for download.
    """
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

    manager = make_manager(backend)
    record = manager.start("success", "ar")
    await record.task

    # The guard still pays for itself: the second heal is never dispatched.
    assert backend.heal_calls == 1
    assert backend.qa_calls == 0

    # (a) the answer survives the abort
    assert record.status == "answer_only"
    assert record.answer is not None and record.answer.tldr
    assert record.fallback is not None
    assert record.fallback.reason_code == "verification_exhausted"

    # (b) the unverified artifact never reaches the learner
    assert record.artifact is None
    assert record.simulation is None
    assert manager.artifacts == {}

    public = record.public_result().model_dump(mode="json")
    assert public["status"] == "answer_only"
    assert public["answer"]["tldr"]
    assert public["simulation"] is None
    assert public["fallback"]["reason_code"] == "verification_exhausted"
    assert "artifact-" not in json.dumps(public, ensure_ascii=False)
