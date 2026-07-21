from __future__ import annotations

import json

import pytest

from server.promotion import (
    EXPERIMENTAL_PROMOTION_GATES,
    EXPERIMENTAL_ROUTE,
    STABLE_ROUTE,
)


def _receipt(*, passed_gates: frozenset[str] = frozenset()):
    from server.cache import VerificationReceipt

    return VerificationReceipt(
        deterministic_passed=True,
        browser_passed=True,
        failed_gate_count=0,
        check_count=23,
        passed_gates=tuple(sorted(passed_gates)),
    )


def _cache(tmp_path):
    from server.cache import VerifiedCache

    return VerifiedCache(
        root=tmp_path / "live",
        golden_root=tmp_path / "golden",
        secret=b"experimental-policy-fixture",
        contract_version="1.0",
    )


def _write(cache, *, route_label: str, passed_gates: frozenset[str]):
    return cache.write_verified(
        question="generic response experiment",
        locale="en",
        domain="physics",
        canonical_intent="generic_response",
        artifact="verified artifact",
        title="Generic response",
        direction="ltr",
        tier="B",
        receipt=_receipt(passed_gates=passed_gates),
        route_label=route_label,
    )


@pytest.mark.parametrize("missing_gate", sorted(EXPERIMENTAL_PROMOTION_GATES))
def test_experimental_route_cannot_enter_stable_cache_with_any_gate_missing(
    tmp_path, missing_gate
):
    cache = _cache(tmp_path)
    passed_gates = EXPERIMENTAL_PROMOTION_GATES - {missing_gate}

    with pytest.raises(ValueError, match=missing_gate):
        _write(
            cache,
            route_label=EXPERIMENTAL_ROUTE,
            passed_gates=passed_gates,
        )

    assert list((tmp_path / "live").glob("*.json")) == []


def test_fully_gated_experimental_route_retains_its_label_in_stable_cache(tmp_path):
    cache = _cache(tmp_path)

    entry = _write(
        cache,
        route_label=EXPERIMENTAL_ROUTE,
        passed_gates=EXPERIMENTAL_PROMOTION_GATES,
    )

    assert entry.route_label == EXPERIMENTAL_ROUTE
    stored = json.loads(
        (tmp_path / "live" / f"{entry.cache_id}.json").read_text(encoding="utf-8")
    )
    assert stored["route_label"] == EXPERIMENTAL_ROUTE
    assert set(stored["receipt"]["passed_gates"]) == EXPERIMENTAL_PROMOTION_GATES
    assert cache.lookup(
        question="generic response experiment",
        locale="en",
        domain="physics",
        canonical_intent="generic_response",
    ) == entry


def test_stable_route_rejects_unknown_route_labels(tmp_path):
    cache = _cache(tmp_path)

    with pytest.raises(ValueError, match="route label"):
        _write(cache, route_label="unlabelled", passed_gates=frozenset())

    entry = _write(cache, route_label=STABLE_ROUTE, passed_gates=frozenset())
    assert entry.route_label == STABLE_ROUTE


@pytest.mark.asyncio
async def test_existing_generation_pipeline_explicitly_labels_its_stable_route():
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend
    from server.jobs import JobManager

    class RouteRecordingCache:
        route_label = None

        def lookup(self, **kwargs):
            del kwargs
            return None

        def write_verified(self, **kwargs):
            self.route_label = kwargs["route_label"]

    cache = RouteRecordingCache()
    manager = JobManager(
        MockCodexBackend(),
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=cache,
    )
    record = manager.start("success", "en")
    await record.task

    assert record.status == "complete"
    assert cache.route_label == STABLE_ROUTE
