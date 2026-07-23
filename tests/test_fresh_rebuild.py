from pathlib import Path

import pytest

from tests.conftest import wait_for_terminal

ROOT = Path(__file__).parents[1]


@pytest.mark.asyncio
async def test_fresh_rebuild_bypasses_a_verified_cache_hit_without_retaining_question(
    tmp_path,
):
    from server.browser_verify import BrowserVerificationResult
    from server.cache import VerifiedCache
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=tmp_path / "golden",
        secret=b"fresh-rebuild-cache-secret",
        contract_version="1.0",
    )
    backend = MockCodexBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=cache,
    )

    original = manager.start("success", "ar")
    await original.task
    cached = manager.start("success", "ar")
    await cached.task
    rebuilt = manager.start("success", "ar", fresh_generation=True)
    await rebuilt.task

    assert original.status == cached.status == rebuilt.status == "complete"
    assert original.simulation is not None
    assert cached.simulation is not None
    assert rebuilt.simulation is not None
    assert cached.simulation.effective_model == "verified/cache"
    assert rebuilt.simulation.effective_model != "verified/cache"
    assert backend.generate_calls == 2
    assert rebuilt.question is None


def test_api_accepts_only_the_closed_fresh_generation_mode(client):
    accepted = client.post(
        "/api/ask",
        json={
            "question": "success",
            "locale": "ar",
            "generation_mode": "fresh",
        },
    )
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]
    result = wait_for_terminal(client, job_id)
    record = client.app.state.jobs.get(job_id)

    assert result["status"] == "complete"
    assert record is not None and record.fresh_generation is True
    assert record.question is None
    assert client.post(
        "/api/ask",
        json={
            "question": "success",
            "locale": "ar",
            "generation_mode": "unknown",
        },
    ).status_code == 422


def test_result_improvement_action_requests_a_fresh_build_instead_of_reloading_iframe():
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    translations = (ROOT / "web" / "translations.js").read_text(encoding="utf-8")

    assert 'generation_mode: fresh ? "fresh" : "standard"' in script
    assert "submitQuestion(rebuildQuestion, { fresh: true })" in script
    assert "frame.src = frame.src" not in script
    assert '"result.replay": "حسّن وأعد البناء"' in translations
    assert '"result.replay": "Improve and rebuild"' in translations
