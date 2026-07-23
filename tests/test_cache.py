import json
from pathlib import Path

import pytest

from tests.golden_cases import VALID_UNDERSTANDING


def verified_receipt():
    from server.cache import VerificationReceipt

    return VerificationReceipt(
        deterministic_passed=True,
        browser_passed=True,
        failed_gate_count=0,
        check_count=17,
    )


def test_exact_and_semantic_cache_without_raw_question(tmp_path):
    from server.cache import VerifiedCache

    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=tmp_path / "golden",
        secret=b"test-cache-secret",
        contract_version="1.0",
    )
    question = "ليش يتغير شكل القمر؟ PRIVATE-CANARY-7291"
    entry = cache.write_verified(
        question=question,
        locale="ar",
        domain="astronomy",
        canonical_intent="moon_phase_lit_fraction",
        artifact="<!doctype html><title>verified</title>",
        title="أطوار القمر",
        direction="rtl",
        tier="B",
        receipt=verified_receipt(),
        route_label="stable",
    )

    exact = cache.lookup(
        question=question,
        locale="ar",
        domain="astronomy",
        canonical_intent="moon_phase_lit_fraction",
    )
    semantic = cache.lookup(
        question="shlon yetghayar el qamar",
        locale="ar",
        domain="astronomy",
        canonical_intent="moon_phase_lit_fraction",
    )

    assert exact is not None and exact.cache_id == entry.cache_id
    assert semantic is not None and semantic.cache_id == entry.cache_id
    stored = (tmp_path / "live" / f"{entry.cache_id}.json").read_text(encoding="utf-8")
    assert question not in stored
    assert "PRIVATE-CANARY-7291" not in stored
    assert not list((tmp_path / "live").glob("*.tmp"))


def test_verified_pinned_alias_lookup_returns_the_requested_localized_artifact(tmp_path):
    from server.cache import VerifiedCache

    root = Path(__file__).parents[1]
    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=root / "out" / "cache" / "golden",
        secret=b"test-cache-secret",
        contract_version="1.0",
    )

    english = cache.lookup(
        question="Why do some objects float?",
        locale="en",
        domain="unrelated-domain-does-not-match-semantic-key",
        canonical_intent="unrelated_intent",
    )
    arabic = cache.lookup(
        question="لماذا تطفو بعض الأجسام؟",
        locale="ar",
        domain="unrelated-domain-does-not-match-semantic-key",
        canonical_intent="unrelated_intent",
    )

    assert english is not None
    assert english.pinned is True and english.locale == "en"
    assert english.direction == "ltr"
    assert english.title == "Density and buoyancy in water"
    assert '<html lang="en" dir="ltr">' in english.artifact
    assert arabic is not None
    assert arabic.pinned is True and arabic.locale == "ar"
    assert arabic.direction == "rtl"
    assert '<html lang="ar" dir="rtl">' in arabic.artifact


def test_pinned_alias_lookup_is_exact_and_does_not_guess_learner_intent(tmp_path):
    from server.cache import VerifiedCache

    root = Path(__file__).parents[1]
    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=root / "out" / "cache" / "golden",
        secret=b"test-cache-secret",
        contract_version="1.0",
    )

    assert cache.lookup(
        question="Why do ships float?",
        locale="en",
        domain="unrelated-domain-does-not-match-semantic-key",
        canonical_intent="unrelated_intent",
    ) is None


@pytest.mark.parametrize(
    "receipt,tier",
    [
        (None, "B"),
        ("deterministic_failed", "B"),
        ("browser_failed", "B"),
        ("failed_gate", "B"),
        ("passed", "unverified"),
    ],
)
def test_cache_rejects_every_unverified_write(tmp_path, receipt, tier):
    from server.cache import VerificationReceipt, VerifiedCache

    receipts = {
        None: None,
        "deterministic_failed": VerificationReceipt(False, True, 1, 8),
        "browser_failed": VerificationReceipt(True, False, 1, 12),
        "failed_gate": VerificationReceipt(True, True, 1, 12),
        "passed": verified_receipt(),
    }
    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=tmp_path / "golden",
        secret=b"test-cache-secret",
        contract_version="1.0",
    )

    with pytest.raises(ValueError, match="verified"):
        cache.write_verified(
            question="unsafe canary",
            locale="ar",
            domain="test",
            canonical_intent="test",
            artifact="artifact",
            title="title",
            direction="rtl",
            tier=tier,
            receipt=receipts[receipt],
            route_label="stable",
        )

    assert list((tmp_path / "live").glob("*.json")) == []


def test_contract_version_invalidates_cache_and_golden_is_immutable(tmp_path):
    from server.cache import VerifiedCache

    golden_root = tmp_path / "golden"
    golden_root.mkdir()
    cache_v1 = VerifiedCache(
        root=tmp_path / "live",
        golden_root=golden_root,
        secret=b"test-cache-secret",
        contract_version="1.0",
    )
    entry = cache_v1.write_verified(
        question="moon",
        locale="en",
        domain="astronomy",
        canonical_intent="moon_phase_lit_fraction",
        artifact="artifact-v1",
        title="Moon",
        direction="ltr",
        tier="B",
        receipt=verified_receipt(),
        route_label="stable",
    )
    runtime_path = tmp_path / "live" / f"{entry.cache_id}.json"
    pinned = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime_path.unlink()
    pinned["pinned"] = True
    (golden_root / f"{entry.cache_id}.json").write_text(
        json.dumps(pinned),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pinned"):
        cache_v1.write_verified(
            question="moon",
            locale="en",
            domain="astronomy",
            canonical_intent="moon_phase_lit_fraction",
            artifact="overwrite",
            title="Moon",
            direction="ltr",
            tier="B",
            receipt=verified_receipt(),
            route_label="stable",
        )

    cache_v2 = VerifiedCache(
        root=tmp_path / "live-v2",
        golden_root=golden_root,
        secret=b"test-cache-secret",
        contract_version="2.0",
    )
    assert cache_v2.lookup(
        question="moon",
        locale="en",
        domain="astronomy",
        canonical_intent="moon_phase_lit_fraction",
    ) is None


def test_runtime_cache_uses_the_causal_actor_verification_profile(monkeypatch):
    from server.app import create_app
    from server.codex_backend import MockCodexBackend

    monkeypatch.setenv("LAYSH_CACHE_KEY_SECRET", "offline-cache-profile-test")
    app = create_app(backend=MockCodexBackend())

    assert app.state.jobs.cache is not None
    assert app.state.jobs.cache.contract_version == "1.1-causal-actor"
    assert app.state.jobs.cache.curated_legacy_goldens == {
        "buoyancy": "1.0",
        "day_night": "1.0",
        "moon_phases": "1.0",
        "pendulum": "1.0",
        "simple_circuit": "1.0",
        "sound_pitch": "1.0",
    }


def test_causal_cache_bypasses_legacy_live_but_keeps_explicit_curated_golden(
    tmp_path,
):
    from server.cache import VERIFIED_CACHE_CONTRACT_VERSION, VerifiedCache

    live_root = tmp_path / "live"
    golden_root = tmp_path / "golden"
    legacy = VerifiedCache(
        root=live_root,
        golden_root=golden_root,
        secret=b"test-cache-secret",
        contract_version="1.0",
    )
    legacy.write_verified(
        question="legacy generated question",
        locale="en",
        domain="mechanics",
        canonical_intent="legacy_generated_intent",
        artifact="<!doctype html><title>legacy generated</title>",
        title="Legacy generated",
        direction="ltr",
        tier="B",
        receipt=verified_receipt(),
        route_label="stable",
    )
    repository_golden = (
        Path(__file__).parents[1] / "out" / "cache" / "golden" / "buoyancy.json"
    )
    golden_root.mkdir(exist_ok=True)
    (golden_root / "buoyancy.json").write_bytes(repository_golden.read_bytes())

    causal = VerifiedCache(
        root=live_root,
        golden_root=golden_root,
        secret=b"test-cache-secret",
        contract_version=VERIFIED_CACHE_CONTRACT_VERSION,
        curated_legacy_goldens={"buoyancy": "1.0"},
    )

    assert causal.lookup(
        question="legacy generated question",
        locale="en",
        domain="mechanics",
        canonical_intent="legacy_generated_intent",
    ) is None
    golden = causal.lookup(
        question="Why do some objects float?",
        locale="en",
        domain="unrelated",
        canonical_intent="unrelated",
    )
    assert golden is not None
    assert golden.cache_id == "golden_buoyancy"
    assert golden.contract_version == "1.0"
    assert golden.pinned is True


@pytest.mark.parametrize(
    ("allowlist", "stored_version"),
    [
        ({}, "1.0"),
        ({"buoyancy": "1.0"}, "0.9"),
        ({"different_lesson": "1.0"}, "1.0"),
    ],
)
def test_pinned_alias_cannot_bypass_explicit_curated_version_allowlist(
    tmp_path,
    allowlist,
    stored_version,
):
    from server.cache import VERIFIED_CACHE_CONTRACT_VERSION, VerifiedCache

    golden_root = tmp_path / "golden"
    golden_root.mkdir()
    source = (
        Path(__file__).parents[1] / "out" / "cache" / "golden" / "buoyancy.json"
    )
    document = json.loads(source.read_text(encoding="utf-8"))
    document["contract_version"] = stored_version
    (golden_root / "buoyancy.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )
    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=golden_root,
        secret=b"test-cache-secret",
        contract_version=VERIFIED_CACHE_CONTRACT_VERSION,
        curated_legacy_goldens=allowlist,
    )

    assert cache.lookup(
        question="Why do some objects float?",
        locale="en",
        domain="unrelated",
        canonical_intent="unrelated",
    ) is None


@pytest.mark.asyncio
async def test_pipeline_writes_cache_only_after_browser_pass(tmp_path):
    from server.browser_verify import BrowserVerificationResult
    from server.cache import VerifiedCache
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=tmp_path / "golden",
        secret=b"test-cache-secret",
        contract_version="1.0",
    )
    backend = MockCodexBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=cache,
    )
    record = manager.start("success", "ar")
    await record.task

    assert record.status == "complete"
    hit = cache.lookup(
        question="success",
        locale="ar",
        domain=VALID_UNDERSTANDING["domain"],
        canonical_intent=VALID_UNDERSTANDING["canonical_intent"],
    )
    assert hit is not None
    assert hit.receipt.failed_gate_count == 0
    assert hit.receipt.browser_passed is True


@pytest.mark.asyncio
async def test_pipeline_never_caches_or_shares_an_artifact_echoing_its_question(tmp_path):
    from server.browser_verify import BrowserVerificationResult
    from server.cache import VerifiedCache
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    learner_question = "private learner phrasing 829104 about orbital light"

    class EchoingBackend(MockCodexBackend):
        async def understand(self, question, locale, *, runtime_context=None):
            understanding = await super().understand(
                question,
                locale,
                runtime_context=runtime_context,
            )
            understanding["title"] = question
            return understanding

    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=tmp_path / "golden",
        secret=b"test-cache-secret",
        contract_version="1.0",
    )
    manager = JobManager(
        EchoingBackend(),
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=cache,
    )

    record = manager.start(learner_question, "en")
    await record.task

    assert record.status == "complete"
    assert record.share_eligible is False
    assert cache.list_entries() == []


@pytest.mark.asyncio
async def test_semantic_cache_hit_cannot_requalify_an_artifact_echoing_another_question(
    tmp_path,
):
    from server.browser_verify import BrowserVerificationResult
    from server.cache import VerifiedCache
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    first_question = "private learner phrasing 829104 about orbital light"
    second_question = "Why does the illuminated part change?"
    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=tmp_path / "golden",
        secret=b"test-cache-secret",
        contract_version="1.0",
    )
    cache.write_verified(
        question=first_question,
        locale="en",
        domain=VALID_UNDERSTANDING["domain"],
        canonical_intent=VALID_UNDERSTANDING["canonical_intent"],
        artifact=f"<!doctype html><title>{first_question}</title>",
        title=first_question,
        direction="ltr",
        tier="B",
        receipt=verified_receipt(),
        route_label="stable",
    )
    backend = MockCodexBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=cache,
    )

    record = manager.start(second_question, "en")
    await record.task

    assert record.status == "complete"
    assert backend.generate_calls == 0
    assert record.share_eligible is False


@pytest.mark.asyncio
async def test_adversarial_candidate_never_reaches_cache(tmp_path):
    from server.browser_verify import BrowserVerificationResult
    from server.cache import VerifiedCache
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    cache = VerifiedCache(
        root=tmp_path / "live",
        golden_root=tmp_path / "golden",
        secret=b"test-cache-secret",
        contract_version="1.0",
    )
    manager = JobManager(
        MockCodexBackend(),
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=cache,
    )
    record = manager.start("exhausted heal", "ar")
    await record.task

    assert record.status == "answer_only"
    assert record.artifact is None
    assert cache.list_entries() == []


def test_cache_admin_lists_inspects_and_purges_only_explicit_runtime_id(tmp_path, capsys):
    from scripts.cache_admin import main
    from server.cache import VerifiedCache

    root = tmp_path / "live"
    golden = tmp_path / "golden"
    cache = VerifiedCache(
        root=root,
        golden_root=golden,
        secret=b"test-cache-secret",
        contract_version="1.0",
    )
    entry = cache.write_verified(
        question="moon",
        locale="en",
        domain="astronomy",
        canonical_intent="moon_phase_lit_fraction",
        artifact="artifact",
        title="Moon",
        direction="ltr",
        tier="B",
        receipt=verified_receipt(),
        route_label="stable",
    )
    common = [
        "--root",
        str(root),
        "--golden-root",
        str(golden),
        "--secret",
        "test-cache-secret",
    ]

    assert main([*common, "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["cache_id"] == entry.cache_id
    assert "artifact" not in listed[0]
    assert main([*common, "inspect", entry.cache_id]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["artifact_sha256"] == entry.artifact_sha256
    assert main([*common, "purge", entry.cache_id]) == 0
    assert json.loads(capsys.readouterr().out) == {"purged": entry.cache_id}
    assert cache.inspect(entry.cache_id) is None
