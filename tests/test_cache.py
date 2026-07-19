import json

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
