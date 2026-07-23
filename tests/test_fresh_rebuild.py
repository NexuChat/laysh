from pathlib import Path

import pytest

from tests.conftest import wait_for_terminal

ROOT = Path(__file__).parents[1]


@pytest.mark.asyncio
async def test_fresh_rebuild_bypasses_a_verified_cache_hit_without_retaining_question(
    tmp_path,
):
    from server.browser_verify import BrowserVerificationResult
    from server.cache import VERIFIED_CACHE_CONTRACT_VERSION, VerifiedCache
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=tmp_path / "golden",
        secret=b"fresh-rebuild-cache-secret",
        contract_version=VERIFIED_CACHE_CONTRACT_VERSION,
    )
    class DistinctRebuildBackend(MockCodexBackend):
        async def generate(self, *args, **kwargs):
            generated = await super().generate(*args, **kwargs)
            if self.generate_calls > 1:
                generated["module_js"] += "\n// fresh candidate\n"
            return generated

    backend = DistinctRebuildBackend()
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
    assert rebuilt.simulation.tier == "B"
    assert rebuilt.fresh_outcome is None
    assert rebuilt.artifact != original.artifact
    incumbent = cache.lookup(
        question="success",
        locale="ar",
        domain="astronomy",
        canonical_intent="moon_phase_lit_fraction",
    )
    assert incumbent is not None and incumbent.artifact == rebuilt.artifact
    assert backend.generate_calls == 2
    assert rebuilt.question is None
    assert list((tmp_path / "golden").glob("*.json")) == []
    assert all(entry.tier == "B" for entry in cache.list_entries())


@pytest.mark.asyncio
async def test_fresh_rebuild_keeps_a_better_incumbent_and_leaves_cache_untouched(tmp_path):
    from server.browser_verify import BrowserVerificationResult
    from server.cache import VERIFIED_CACHE_CONTRACT_VERSION, VerificationReceipt, VerifiedCache
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    class DistinctRebuildBackend(MockCodexBackend):
        async def generate(self, *args, **kwargs):
            generated = await super().generate(*args, **kwargs)
            if self.generate_calls > 1:
                generated["module_js"] += "\n// fresh candidate\n"
            return generated

    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=tmp_path / "golden",
        secret=b"fresh-rebuild-cache-secret",
        contract_version=VERIFIED_CACHE_CONTRACT_VERSION,
    )
    backend = DistinctRebuildBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=cache,
    )

    original = manager.start("success", "ar")
    await original.task
    assert original.simulation is not None and original.artifact is not None
    cache.write_verified(
        question="success",
        locale="ar",
        domain="astronomy",
        canonical_intent="moon_phase_lit_fraction",
        artifact=original.artifact,
        title=original.simulation.title,
        direction="rtl",
        tier="B",
        receipt=VerificationReceipt(True, True, 0, original.simulation.check_count + 1),
        route_label="stable",
    )

    rebuilt = manager.start("success", "ar", fresh_generation=True)
    await rebuilt.task
    result = rebuilt.public_result().model_dump(mode="json")
    cached = cache.lookup(
        question="success",
        locale="ar",
        domain="astronomy",
        canonical_intent="moon_phase_lit_fraction",
    )

    assert rebuilt.status == "complete"
    assert rebuilt.artifact == original.artifact
    assert rebuilt.simulation is not None
    assert result["fresh_outcome"] == "kept_incumbent"
    assert result["fresh_outcome_reason_code"] == "check_count_regression"
    assert cached is not None and cached.artifact == original.artifact
    assert any(
        item == {"type": "fresh_candidate_kept_incumbent", "reason_code": "check_count_regression"}
        for item in rebuilt.builder_diagnostics
    )
    public_surface = str(
        {
            "result": result,
            "events": [event.model_dump(mode="json") for event in rebuilt.events],
            "diagnostics": rebuilt.builder_diagnostics,
        }
    )
    assert "success" not in public_surface
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
    assert '"result.keptBetterVersion": "أبقينا النسخة الأفضل"' in translations
    assert '"result.keptBetterVersion": "We kept the better version"' in translations
    assert 'result.fresh_outcome === "kept_incumbent"' in script
