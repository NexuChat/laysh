from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from tests.golden_cases import VALID_UNDERSTANDING


def _case(fixture_id: str, model: str, *, passed: bool = True, elapsed_ms: int = 1000):
    return {
        "fixture_id": fixture_id,
        "spec_sha256": (fixture_id.encode().hex() + "0" * 64)[:64],
        "generation_model": model,
        "passed": passed,
        "elapsed_ms": elapsed_ms,
        "live_calls": [
            {
                "stage": "generate",
                "model": model,
                "effort": "medium",
                "why_model_was_called": "fixed_spec_candidate",
                "elapsed_ms": elapsed_ms,
                "outcome": "completed",
                "thread_id_captured": True,
                "failure_code": None,
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 40,
            }
        ],
        "heal_count": 0,
        "failure_code": None if passed else "deterministic_verification_failed",
    }


def _healed_case(fixture_id: str, model: str, *, qa_model: str = "gpt-5.6-sol"):
    case = _case(fixture_id, model, elapsed_ms=3000)
    case["live_calls"] = [
        {**case["live_calls"][0], "elapsed_ms": 1000},
        {
            **case["live_calls"][0],
            "stage": "heal",
            "why_model_was_called": "one_same_model_repair_after_gate_failure",
            "elapsed_ms": 1000,
        },
        {
            **case["live_calls"][0],
            "stage": "qa",
            "model": qa_model,
            "why_model_was_called": "post_heal_closed_review",
            "elapsed_ms": 1000,
        },
    ]
    case["heal_count"] = 1
    return case


def _prior_aborted_evidence() -> list[dict[str, object]]:
    return [
        {
            "path": "out/evidence/route-02-aborted-preflight.json",
            "sha256": "a" * 64,
            "model": "gpt-5.6-sol",
            "elapsed_ms_approximate": 25_000,
            "live_call_count_conservative": 1,
        },
        {
            "path": "out/evidence/route-02-aborted-guard-red-2.json",
            "sha256": "b" * 64,
            "model": "gpt-5.6-terra",
            "elapsed_ms_approximate": 11_000,
            "live_call_count_conservative": 1,
        },
    ]


def test_bounded_route_report_adopts_terra_only_from_complete_observed_evidence():
    from scripts.evaluate_generation_routing import build_report

    fixtures = ("fixed_spec_alpha", "fixed_spec_beta")
    cases = [
        *[_case(item, "gpt-5.6-terra", elapsed_ms=800) for item in fixtures],
        *[_case(item, "gpt-5.6-sol", elapsed_ms=1000) for item in fixtures],
    ]
    report = build_report(
        cases,
        account_usage={
            "observed": True,
            "source": "codex_app_server_account_usage_read",
            "terra_delta_units": 120,
            "sol_delta_units": 180,
        },
        fixture_ids=fixtures,
        configured_terra_tiers={"bounded_single_parameter_v1"},
    )

    assert report["passed"] is True
    assert report["call_cap"] == 12
    assert report["cohort_live_calls"] == 4
    assert report["prior_aborted_live_calls"] == 0
    assert report["total_live_calls"] == 4
    assert report["fresh_sol_generate_after_terra_failure"] is False
    assert report["evaluation_set"] == [
        {
            "fixture_id": item,
            "spec_sha256": (item.encode().hex() + "0" * 64)[:64],
        }
        for item in fixtures
    ]
    assert report["tier_decision"] == {
        "tier": "bounded_single_parameter_v1",
        "generation_model": "gpt-5.6-terra",
        "adopted": True,
        "decision_applied": True,
        "reason": "terra_met_quality_calls_latency_and_observed_usage_gates",
    }


def test_route_report_counts_prior_aborted_attempts_inside_the_total_cap():
    from scripts.evaluate_generation_routing import build_report

    fixtures = ("fixed_spec_alpha", "fixed_spec_beta")
    cases = [
        *[_case(item, "gpt-5.6-terra", elapsed_ms=800) for item in fixtures],
        *[_case(item, "gpt-5.6-sol", elapsed_ms=1000) for item in fixtures],
    ]
    report = build_report(
        cases,
        account_usage={
            "observed": True,
            "source": "codex_app_server_account_usage_read",
            "terra_delta_units": 120,
            "sol_delta_units": 180,
        },
        fixture_ids=fixtures,
        configured_terra_tiers={"bounded_single_parameter_v1"},
        prior_aborted_evidence=_prior_aborted_evidence(),
    )

    assert report["cohort_live_calls"] == 4
    assert report["prior_aborted_live_calls"] == 2
    assert report["total_live_calls"] == 6
    assert report["prior_aborted_evidence"] == _prior_aborted_evidence()


def test_route_decision_cannot_pass_until_runtime_config_matches_it():
    from scripts.evaluate_generation_routing import build_report

    fixtures = ("fixed_spec_alpha", "fixed_spec_beta")
    cases = [
        *[_case(item, "gpt-5.6-terra", elapsed_ms=800) for item in fixtures],
        *[_case(item, "gpt-5.6-sol", elapsed_ms=1000) for item in fixtures],
    ]
    report = build_report(
        cases,
        account_usage={
            "observed": True,
            "source": "codex_app_server_account_usage_read",
            "terra_delta_units": 120,
            "sol_delta_units": 180,
        },
        fixture_ids=fixtures,
        configured_terra_tiers=set(),
    )

    assert report["passed"] is False
    assert report["tier_decision"]["adopted"] is True
    assert report["tier_decision"]["decision_applied"] is False
    assert report["gates"]["runtime_config_matches_decision"] is False


def test_repository_route_contract_matches_safe_unmeasured_defaults():
    from scripts.evaluate_generation_routing import repository_configured_terra_tiers

    assert repository_configured_terra_tiers() == set()


def test_repository_blank_overrides_defer_to_the_data_decision(tmp_path, monkeypatch):
    import scripts.evaluate_generation_routing as evaluation
    import server.model_routing as routing

    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [routing.BOUNDED_SINGLE_PARAMETER])
    (tmp_path / "deploy").mkdir()
    (tmp_path / ".env.example").write_text(
        "LAYSH_QA_MODEL=gpt-5.6-sol\nLAYSH_TERRA_GENERATION_TIERS=\n",
        encoding="utf-8",
    )
    (tmp_path / "deploy" / "laysh.service").write_text(
        "Environment=LAYSH_QA_MODEL=gpt-5.6-sol\n"
        "Environment=LAYSH_TERRA_GENERATION_TIERS=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    monkeypatch.setattr(routing, "ROUTING_DECISION_PATH", decision_path)

    assert evaluation.repository_configured_terra_tiers() == {
        routing.BOUNDED_SINGLE_PARAMETER
    }


def test_route_report_keeps_direct_sol_and_passes_when_measured_terra_quality_fails():
    from scripts.evaluate_generation_routing import build_report

    fixtures = ("fixed_spec_alpha", "fixed_spec_beta")
    cases = [
        _case(fixtures[0], "gpt-5.6-terra", passed=False),
        _case(fixtures[1], "gpt-5.6-terra"),
        *[_case(item, "gpt-5.6-sol") for item in fixtures],
    ]
    report = build_report(
        cases,
        account_usage={
            "observed": True,
            "source": "codex_app_server_account_usage_read",
            "terra_delta_units": 100,
            "sol_delta_units": 100,
        },
        fixture_ids=fixtures,
        configured_terra_tiers=set(),
    )

    assert report["passed"] is True
    assert report["tier_decision"]["generation_model"] == "gpt-5.6-sol"
    assert report["tier_decision"]["adopted"] is False
    assert set(report["abort_conditions"])


def _write_routing_decision(path: Path, tiers: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "terra_generation_tiers": tiers,
            }
        ),
        encoding="utf-8",
    )


def _write_tracked_raw_evidence(repo_root: Path, raw: dict) -> Path:
    raw_path = repo_root / "out" / "evidence" / "route-02-raw.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    if not (repo_root / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run(["git", "add", str(raw_path)], cwd=repo_root, check=True)
    return raw_path


def _write_tracked_prior_aborted_evidence(repo_root: Path) -> None:
    documents = (
        (
            "route-02-aborted-preflight.json",
            {
                "schema_version": "1.0",
                "acceptance_row": "ROUTE-02",
                "sanitized": True,
                "recorded_at": "2026-07-21T19:55:39Z",
                "passed": False,
                "outcome": "aborted_by_test_guard_red",
                "stage": "generate",
                "model": "gpt-5.6-sol",
                "effort": "medium",
                "elapsed_ms_approximate": 25_000,
                "structured_output": False,
                "token_usage": None,
                "live_call_count_conservative": 1,
                "reason": "Conservatively counted test-guard attempt.",
            },
        ),
        (
            "route-02-aborted-guard-red-2.json",
            {
                "schema_version": "1.0",
                "acceptance_row": "ROUTE-02",
                "sanitized": True,
                "recorded_at": "2026-07-21T20:22:44Z",
                "passed": False,
                "outcome": "aborted_by_confirmation_guard_red",
                "stage": "generate",
                "model": "gpt-5.6-terra",
                "effort": "medium",
                "elapsed_ms_approximate": 11_000,
                "structured_output": False,
                "token_usage": None,
                "live_call_count_conservative": 1,
                "remaining_processes_after_root_check": 0,
                "reason": "Conservatively counted confirmation-guard attempt.",
            },
        ),
    )
    evidence_root = repo_root / "out" / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    for name, document in documents:
        (evidence_root / name).write_text(json.dumps(document), encoding="utf-8")
    subprocess.run(
        ["git", "add", *[f"out/evidence/{name}" for name, _ in documents]],
        cwd=repo_root,
        check=True,
    )


def test_route_report_cannot_pass_without_account_observed_usage():
    from scripts.evaluate_generation_routing import build_report

    fixtures = ("fixed_spec_alpha", "fixed_spec_beta")
    cases = [
        *[_case(item, "gpt-5.6-terra") for item in fixtures],
        *[_case(item, "gpt-5.6-sol") for item in fixtures],
    ]
    report = build_report(
        cases,
        account_usage={"observed": False, "source": "unavailable"},
        fixture_ids=fixtures,
        configured_terra_tiers=set(),
    )

    assert report["passed"] is False
    assert report["tier_decision"]["generation_model"] == "gpt-5.6-sol"


def test_route_report_rejects_call_cap_and_cross_model_heal():
    from scripts.evaluate_generation_routing import build_report

    fixtures = ("fixed_spec_alpha", "fixed_spec_beta")
    cases = [
        *[_case(item, "gpt-5.6-terra") for item in fixtures],
        *[_case(item, "gpt-5.6-sol") for item in fixtures],
    ]
    cases[0]["live_calls"] = [
        {
            **cases[0]["live_calls"][0],
            "model": "gpt-5.6-terra",
            "elapsed_ms": 1,
        },
        {
            **cases[0]["live_calls"][0],
            "stage": "heal",
            "model": "gpt-5.6-sol",
            "why_model_was_called": "one_same_model_repair_after_gate_failure",
            "elapsed_ms": 1,
        },
    ]
    cases[0]["heal_count"] = 1
    with pytest.raises(ValueError, match="case_evidence_invalid"):
        build_report(
            cases,
            account_usage={"observed": True, "source": "fixture"},
            fixture_ids=fixtures,
        )

    cases[0]["live_calls"] = [
        {**cases[0]["live_calls"][0], "elapsed_ms": 1}
    ] * 13
    with pytest.raises(ValueError, match="call_cap"):
        build_report(
            cases,
            account_usage={"observed": True, "source": "fixture"},
            fixture_ids=fixtures,
        )

    maximum_cohort = [
        *[_healed_case(item, "gpt-5.6-terra") for item in fixtures],
        *[_healed_case(item, "gpt-5.6-sol") for item in fixtures],
    ]
    with pytest.raises(ValueError, match="call_cap"):
        build_report(
            maximum_cohort,
            account_usage={
                "observed": True,
                "source": "codex_app_server_account_usage_read",
                "terra_delta_units": 120,
                "sol_delta_units": 180,
            },
            fixture_ids=fixtures,
            prior_aborted_evidence=_prior_aborted_evidence(),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda case: case.update({"passed": "false"}),
        lambda case: case.update({"raw_model_output": "must-not-enter-evidence"}),
        lambda case: case["live_calls"][0].update({"prompt": "private"}),
        lambda case: case.update(
            {"passed": False, "failure_code": "private detail /home/dev/token"}
        ),
    ],
)
def test_route_report_rejects_open_or_ambiguous_case_evidence(mutation):
    from scripts.evaluate_generation_routing import build_report

    fixtures = ("fixed_spec_alpha", "fixed_spec_beta")
    cases = [
        *[_case(item, "gpt-5.6-terra") for item in fixtures],
        *[_case(item, "gpt-5.6-sol") for item in fixtures],
    ]
    mutation(cases[0])

    with pytest.raises(ValueError, match="case_evidence"):
        build_report(
            cases,
            account_usage={
                "observed": True,
                "source": "codex_app_server_account_usage_read",
                "terra_delta_units": 10,
                "sol_delta_units": 10,
            },
            fixture_ids=fixtures,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda case: case["live_calls"][0].update(
            {
                "outcome": "failed",
                "failure_code": "stage_timeout",
                "thread_id_captured": False,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        ),
        lambda case: case["live_calls"][0].update({"thread_id_captured": False}),
        lambda case: case["live_calls"][0].update(
            {"why_model_was_called": "one_same_model_repair_after_gate_failure"}
        ),
        lambda case: case.update({"elapsed_ms": 999}),
        lambda case: case["live_calls"][0].update({"elapsed_ms": 0}),
    ],
)
def test_passing_case_is_bound_to_completed_threaded_reasoned_timing(mutation):
    from scripts.evaluate_generation_routing import build_report

    fixtures = ("fixed_spec_alpha", "fixed_spec_beta")
    cases = [
        *[_case(item, "gpt-5.6-terra") for item in fixtures],
        *[_case(item, "gpt-5.6-sol") for item in fixtures],
    ]
    mutation(cases[0])

    with pytest.raises(ValueError, match="case_evidence_invalid"):
        build_report(
            cases,
            account_usage={
                "observed": True,
                "source": "codex_app_server_account_usage_read",
                "terra_delta_units": 10,
                "sol_delta_units": 10,
            },
            fixture_ids=fixtures,
        )


def test_passing_healed_case_requires_production_sol_qa_after_heal():
    from scripts.evaluate_generation_routing import build_report

    fixtures = ("fixed_spec_alpha", "fixed_spec_beta")
    base = [
        _case(fixtures[1], "gpt-5.6-terra"),
        *[_case(item, "gpt-5.6-sol") for item in fixtures],
    ]
    account_usage = {
        "observed": True,
        "source": "codex_app_server_account_usage_read",
        "terra_delta_units": 10,
        "sol_delta_units": 10,
    }

    without_qa = _healed_case(fixtures[0], "gpt-5.6-terra")
    without_qa["live_calls"].pop()
    with pytest.raises(ValueError, match="case_evidence_invalid"):
        build_report(
            [without_qa, *base],
            account_usage=account_usage,
            fixture_ids=fixtures,
        )

    with pytest.raises(ValueError, match="case_evidence_invalid"):
        build_report(
            [
                _healed_case(
                    fixtures[0], "gpt-5.6-terra", qa_model="gpt-5.6-terra"
                ),
                *base,
            ],
            account_usage=account_usage,
            fixture_ids=fixtures,
        )

    report = build_report(
        [_healed_case(fixtures[0], "gpt-5.6-terra"), *base],
        account_usage=account_usage,
        fixture_ids=fixtures,
        configured_terra_tiers=set(),
    )
    assert report["cases"][0]["live_calls"][-1]["model"] == "gpt-5.6-sol"


def test_case_evaluator_uses_the_same_sol_qa_route_as_production(monkeypatch):
    import scripts.evaluate_generation_routing as evaluation
    import server.codex_backend as backend_module
    import server.verify as verify_module
    from server.codex_runtime import StageExecution
    from server.verify import VerificationResult
    from tests.golden_cases import VALID_MODULE_OUTPUT

    captured_settings = []

    class FakeBackend:
        def __init__(self, *, executor, settings):
            del executor
            captured_settings.append(settings)
            self.settings = settings

        async def generate(self, understanding, *, runtime_context):
            del understanding, runtime_context
            return StageExecution(
                data=VALID_MODULE_OUTPUT,
                thread_id="generate-thread",
                model="gpt-5.6-terra",
                elapsed_ms=10,
                input_tokens=10,
                output_tokens=10,
            )

        async def heal(self, *args, **kwargs):
            del args, kwargs
            return StageExecution(
                data=VALID_MODULE_OUTPUT,
                thread_id="heal-thread",
                model="gpt-5.6-terra",
                elapsed_ms=10,
                input_tokens=10,
                output_tokens=10,
            )

        async def qa(self, *args, **kwargs):
            del args, kwargs
            return StageExecution(
                data={"approved": True},
                thread_id="qa-thread",
                model=self.settings.qa_model,
                elapsed_ms=10,
                input_tokens=10,
                output_tokens=10,
            )

    outcomes = iter(
        [
            VerificationResult(
                passed=False,
                check_count=1,
                failures=[{"gate": "invariant", "code": "fixture_mismatch"}],
                artifact=None,
                node_report={},
            ),
            VerificationResult(
                passed=True,
                check_count=2,
                failures=[],
                artifact=None,
                node_report={},
            ),
        ]
    )
    monkeypatch.setattr(backend_module, "CodexBackend", FakeBackend)
    monkeypatch.setattr(verify_module, "verify_candidate", lambda *args: next(outcomes))

    case = asyncio.run(
        evaluation._evaluate_case(
            fixture_id="moon_phases_ar",
            model="gpt-5.6-terra",
            executor=object(),
            checkpoint=lambda *args: None,
        )
    )

    assert captured_settings[0].qa_model == "gpt-5.6-sol"
    assert [call["model"] for call in case["live_calls"]] == [
        "gpt-5.6-terra",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
    ]
    assert case["passed"] is True


def test_zero_or_untrusted_account_usage_cannot_adopt_terra():
    from scripts.evaluate_generation_routing import build_report

    fixtures = ("fixed_spec_alpha", "fixed_spec_beta")
    cases = [
        *[_case(item, "gpt-5.6-terra") for item in fixtures],
        *[_case(item, "gpt-5.6-sol") for item in fixtures],
    ]
    with pytest.raises(ValueError, match="account_usage_evidence_invalid"):
        build_report(
            cases,
            account_usage={
                "observed": True,
                "source": "untrusted_manual_claim",
                "terra_delta_units": 0,
                "sol_delta_units": 0,
                "account_email": "must-not-enter-evidence",
            },
            fixture_ids=fixtures,
        )


def test_zero_trusted_account_usage_is_inconclusive():
    from scripts.evaluate_generation_routing import build_report

    fixtures = ("fixed_spec_alpha", "fixed_spec_beta")
    cases = [
        *[_case(item, "gpt-5.6-terra") for item in fixtures],
        *[_case(item, "gpt-5.6-sol") for item in fixtures],
    ]
    with pytest.raises(ValueError, match="account_usage_evidence_invalid"):
        build_report(
            cases,
            account_usage={
                "observed": True,
                "source": "codex_app_server_account_usage_read",
                "terra_delta_units": 0,
                "sol_delta_units": 0,
            },
            fixture_ids=fixtures,
        )


def test_live_cohort_requires_explicit_spend_confirmation_before_provenance_or_calls(
    tmp_path, monkeypatch
):
    import scripts.evaluate_generation_routing as evaluation

    provenance_called = False

    def provenance():
        nonlocal provenance_called
        provenance_called = True
        return _provenance()

    monkeypatch.setattr(evaluation, "_evaluation_provenance", provenance)
    with pytest.raises(ValueError, match="live_evaluation_confirmation_required"):
        asyncio.run(
            evaluation.run_live_cohort(
                model="gpt-5.6-terra",
                raw_path=tmp_path / "route.json",
                append=False,
            )
        )

    assert provenance_called is False

    with pytest.raises(ValueError, match="live_evaluation_dependencies_required"):
        asyncio.run(
            evaluation.run_live_cohort(
                model="gpt-5.6-terra",
                raw_path=tmp_path / "route.json",
                append=False,
                confirmed=True,
            )
        )
    assert provenance_called is False


def test_live_cohort_rejects_dirty_measured_sources_before_any_live_dependency(
    tmp_path,
    monkeypatch,
):
    import scripts.evaluate_generation_routing as evaluation

    dirty = _provenance()
    dirty["worktree_dirty"] = True
    dirty["worktree_state_sha256"] = "f" * 64
    monkeypatch.setattr(evaluation, "_evaluation_provenance", lambda: dirty)
    monkeypatch.setattr(
        evaluation,
        "_load_prior_aborted_evidence",
        lambda _root: _prior_aborted_evidence(),
    )
    monkeypatch.setattr(
        evaluation,
        "LIVE_LOCK_PATH",
        tmp_path / ".route-02-live.lock",
    )
    raw_path = tmp_path / "route.json"

    with pytest.raises(ValueError, match="evaluation_worktree_dirty"):
        asyncio.run(
            evaluation.run_live_cohort(
                model="gpt-5.6-terra",
                raw_path=raw_path,
                append=False,
                confirmed=True,
                dependencies=_never_live_dependencies(),
            )
        )

    assert not raw_path.exists()


def _never_live_dependencies():
    from scripts.evaluate_generation_routing import LiveEvaluationDependencies

    async def usage_reader():
        raise AssertionError("usage reader must not be reached by a preflight test")

    async def case_evaluator(**kwargs):
        del kwargs
        raise AssertionError("case evaluator must not be reached by a preflight test")

    return LiveEvaluationDependencies(
        usage_reader=usage_reader,
        case_evaluator=case_evaluator,
        executor_factory=object,
        sleep=lambda _: asyncio.sleep(0),
    )


def test_live_cohort_refuses_wrong_order_overwrite_and_incomplete_append(tmp_path):
    from scripts.evaluate_generation_routing import run_live_cohort

    raw_path = tmp_path / "route.json"
    with pytest.raises(ValueError, match="terra_must_run_first"):
        asyncio.run(
            run_live_cohort(
                model="gpt-5.6-sol",
                raw_path=raw_path,
                append=False,
                confirmed=True,
                dependencies=_never_live_dependencies(),
            )
        )

    raw_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="already_exists"):
        asyncio.run(
            run_live_cohort(
                model="gpt-5.6-terra",
                raw_path=raw_path,
                append=False,
                confirmed=True,
                dependencies=_never_live_dependencies(),
            )
        )
    with pytest.raises(ValueError, match="complete_terra_cohort"):
        asyncio.run(
            run_live_cohort(
                model="gpt-5.6-sol",
                raw_path=raw_path,
                append=True,
                confirmed=True,
                dependencies=_never_live_dependencies(),
            )
        )


def test_prior_aborted_attempts_reduce_the_new_cohort_budget_to_ten(
    tmp_path,
    monkeypatch,
):
    import scripts.evaluate_generation_routing as evaluation

    raw = _complete_raw("cohort_complete")
    raw["active_model"] = "gpt-5.6-terra"
    fixture_hashes = {
        item["fixture_id"]: item["payload_sha256"]
        for item in raw["evaluation_provenance"]["fixture_prompt_fingerprints"]
    }
    raw["cases"] = [
        _healed_case(fixture_id, "gpt-5.6-terra")
        for fixture_id in ("moon_phases_ar", "pendulum_ar")
    ]
    for case in raw["cases"]:
        case["spec_sha256"] = fixture_hashes[case["fixture_id"]]
    raw["usage_observations"] = raw["usage_observations"][:1]
    raw_path = tmp_path / "route.json"
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(evaluation, "_evaluation_provenance", lambda: _provenance())
    monkeypatch.setattr(
        evaluation,
        "_load_prior_aborted_evidence",
        lambda _root: _prior_aborted_evidence(),
        raising=False,
    )

    with pytest.raises(ValueError, match="projected_live_calls_exceed_12"):
        asyncio.run(
            evaluation.run_live_cohort(
                model="gpt-5.6-sol",
                raw_path=raw_path,
                append=True,
                confirmed=True,
                dependencies=_never_live_dependencies(),
            )
        )


def test_account_usage_evidence_is_derived_from_observed_cohort_deltas():
    from scripts.evaluate_generation_routing import account_usage_from_raw

    usage = account_usage_from_raw(
        {
            "usage_observations": [
                {
                    "model": "gpt-5.6-terra",
                    "source": "codex_app_server_account_usage_read",
                    "delta_units": 120,
                    "turn_reported_tokens": 100,
                    "sample_count": 3,
                    "observed_before_at": "2026-07-21T19:00:00Z",
                    "observed_after_at": "2026-07-21T19:01:00Z",
                },
                {
                    "model": "gpt-5.6-sol",
                    "source": "codex_app_server_account_usage_read",
                    "delta_units": 180,
                    "turn_reported_tokens": 140,
                    "sample_count": 3,
                    "observed_before_at": "2026-07-21T19:02:00Z",
                    "observed_after_at": "2026-07-21T19:03:00Z",
                },
            ]
        }
    )

    assert usage == {
        "observed": True,
        "source": "codex_app_server_account_usage_read",
        "terra_delta_units": 120,
        "sol_delta_units": 180,
    }


@pytest.mark.parametrize(
    "observations",
    [
        [
            {
                "model": "gpt-5.6-terra",
                "source": "codex_app_server_account_usage_read",
                "delta_units": 99,
                "turn_reported_tokens": 100,
                "sample_count": 2,
                "observed_before_at": "2026-07-21T19:00:00Z",
                "observed_after_at": "2026-07-21T19:01:00Z",
            },
            {
                "model": "gpt-5.6-sol",
                "source": "codex_app_server_account_usage_read",
                "delta_units": 180,
                "turn_reported_tokens": 140,
                "sample_count": 2,
                "observed_before_at": "2026-07-21T19:02:00Z",
                "observed_after_at": "2026-07-21T19:03:00Z",
            },
        ],
        [
            {
                "model": "gpt-5.6-terra",
                "source": "codex_app_server_account_usage_read",
                "delta_units": 120,
                "turn_reported_tokens": 100,
                "sample_count": 2,
                "observed_before_at": "2026-07-21T19:00:00Z",
                "observed_after_at": "2026-07-21T19:01:00Z",
                "account_email": "must-not-be-accepted",
            },
            {
                "model": "gpt-5.6-sol",
                "source": "codex_app_server_account_usage_read",
                "delta_units": 180,
                "turn_reported_tokens": 140,
                "sample_count": 2,
                "observed_before_at": "2026-07-21T19:02:00Z",
                "observed_after_at": "2026-07-21T19:03:00Z",
            },
        ],
    ],
)
def test_account_usage_cross_check_is_fail_closed(observations):
    from scripts.evaluate_generation_routing import account_usage_from_raw

    assert account_usage_from_raw({"usage_observations": observations}) == {
        "observed": False,
        "source": "invalid_account_usage_observation",
    }


def test_account_usage_timestamps_are_strictly_ordered_with_sequential_cohorts():
    from scripts.evaluate_generation_routing import account_usage_from_raw

    raw = _complete_raw()
    raw["usage_observations"][0]["observed_after_at"] = raw[
        "usage_observations"
    ][0]["observed_before_at"]
    assert account_usage_from_raw(raw) == {
        "observed": False,
        "source": "invalid_account_usage_observation",
    }

    raw = _complete_raw()
    raw["usage_observations"][1]["observed_before_at"] = "2026-07-21T18:00:00Z"
    assert account_usage_from_raw(raw) == {
        "observed": False,
        "source": "invalid_account_usage_observation",
    }


def test_account_usage_reader_uses_app_server_without_exposing_account_data():
    from scripts.evaluate_generation_routing import read_account_lifetime_tokens

    class FakeReader:
        def __init__(self):
            self.lines = iter(
                [
                    json.dumps({"id": 1, "result": {"userAgent": "ignored"}}),
                    json.dumps(
                        {
                            "id": 2,
                            "result": {
                                "summary": {
                                    "lifetimeTokens": 4321,
                                    "privateAccountField": "must-not-leak",
                                }
                            },
                        }
                    ),
                ]
            )

        async def readline(self):
            try:
                return (next(self.lines) + "\n").encode()
            except StopIteration:
                return b""

    class FakeWriter:
        def __init__(self):
            self.payloads = []

        def write(self, payload):
            self.payloads.append(json.loads(payload))

        async def drain(self):
            return None

        def close(self):
            return None

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeWriter()
            self.stdout = FakeReader()
            self.returncode = None

        async def wait(self):
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = -15

    process = FakeProcess()

    async def factory(*args, **kwargs):
        assert args[-2:] == ("app-server", "--stdio")
        assert kwargs["shell"] is False
        return process

    observed = asyncio.run(read_account_lifetime_tokens(process_factory=factory))

    assert observed == 4321
    assert process.stdin.payloads[-1] == {
        "id": 2,
        "method": "account/usage/read",
    }


def test_account_usage_reader_rejects_boolean_counter():
    from scripts.evaluate_generation_routing import read_account_lifetime_tokens

    class FakeReader:
        def __init__(self):
            self.lines = iter(
                [
                    json.dumps({"id": 1, "result": {}}),
                    json.dumps(
                        {
                            "id": 2,
                            "result": {"summary": {"lifetimeTokens": True}},
                        }
                    ),
                ]
            )

        async def readline(self):
            try:
                return (next(self.lines) + "\n").encode()
            except StopIteration:
                return b""

    class FakeWriter:
        def write(self, payload):
            del payload

        async def drain(self):
            return None

        def close(self):
            return None

    class FakeProcess:
        stdin = FakeWriter()
        stdout = FakeReader()

        async def wait(self):
            return 0

        def terminate(self):
            return None

    async def factory(*args, **kwargs):
        del args, kwargs
        return FakeProcess()

    with pytest.raises(RuntimeError, match="counter_unavailable"):
        asyncio.run(read_account_lifetime_tokens(process_factory=factory))


def test_fixed_spec_hash_covers_the_complete_generation_prompt_payload():
    from scripts.evaluate_generation_routing import _fixed_spec_hash

    baseline = deepcopy(VALID_UNDERSTANDING)
    changed = deepcopy(VALID_UNDERSTANDING)
    changed["tldr"] = "A different explanation changes the generation prompt."

    assert _fixed_spec_hash(baseline) != _fixed_spec_hash(changed)


def test_evaluation_provenance_covers_evaluator_runtime_tree_dirty_and_fixture_payload():
    import scripts.evaluate_generation_routing as evaluation
    from server.goldens import _artifact_lesson_and_module, load_pinned_golden
    from server.schemas import validate_understanding

    provenance = evaluation._evaluation_provenance()
    assert provenance["evaluator_sha256"] == hashlib.sha256(
        Path(evaluation.__file__).read_bytes()
    ).hexdigest()
    assert provenance["runtime_sha256"] == hashlib.sha256(
        (evaluation.ROOT / "server" / "codex_runtime.py").read_bytes()
    ).hexdigest()
    git_path = shutil.which("git")
    assert git_path is not None
    tree_oid = evaluation._git_capture(git_path, "rev-parse", "HEAD^{tree}").strip()
    assert provenance["head_tree_sha256"] == hashlib.sha256(tree_oid).hexdigest()
    assert type(provenance["worktree_dirty"]) is bool
    assert len(provenance["worktree_state_sha256"]) == 64

    expected_payloads = {}
    for fixture_id in evaluation.FIXTURE_IDS:
        golden = load_pinned_golden(fixture_id.removesuffix("_ar"))
        understanding, _ = _artifact_lesson_and_module(golden["artifact"])
        expected_payloads[fixture_id] = evaluation._fixed_spec_hash(
            validate_understanding(understanding)
        )
    assert {
        item["fixture_id"]: item["payload_sha256"]
        for item in provenance["fixture_prompt_fingerprints"]
    } == expected_payloads


def test_evaluation_provenance_covers_transitive_verifier_and_assembly_inputs():
    from scripts.evaluate_generation_routing import SOURCE_SNAPSHOT_PATHS

    assert {
        "scripts/check_artifact.mjs",
        "server/shared_state.py",
        "sim_shell/contract.js",
        "sim_shell/shell.css",
        "sim_shell/shell.html",
        "sim_shell/shell.js",
        "web/fonts/free-sans-arabic-latin.woff2",
        "web/fonts/free-serif-arabic-display.woff2",
    } <= set(SOURCE_SNAPSHOT_PATHS)


def test_account_counter_poll_rejects_decrease_and_requires_stable_cross_check():
    from scripts.evaluate_generation_routing import observe_account_usage_delta

    decreasing = iter([999])

    async def read_decreasing():
        return next(decreasing)

    with pytest.raises(ValueError, match="counter_decreased"):
        asyncio.run(
            observe_account_usage_delta(
                before_units=1000,
                turn_reported_tokens=100,
                reader=read_decreasing,
                sleep=lambda _: asyncio.sleep(0),
            )
        )

    samples = iter([1050, 1100, 1100])

    async def read_stable():
        return next(samples)

    observation = asyncio.run(
        observe_account_usage_delta(
            before_units=1000,
            turn_reported_tokens=100,
            reader=read_stable,
            sleep=lambda _: asyncio.sleep(0),
        )
    )
    assert observation == {"delta_units": 100, "sample_count": 3}

    with pytest.raises(ValueError, match="baseline_invalid"):
        asyncio.run(
            observe_account_usage_delta(
                before_units=True,
                turn_reported_tokens=100,
                reader=read_stable,
                sleep=lambda _: asyncio.sleep(0),
            )
        )


def _provenance(seed: str = "a") -> dict:
    digest = seed * 64
    return {
        "head_commit": digest[:40],
        "head_tree_sha256": digest,
        "worktree_state_sha256": hashlib.sha256(b"").hexdigest(),
        "worktree_dirty": False,
        "source_snapshot_sha256": digest,
        "evaluator_sha256": digest,
        "runtime_sha256": digest,
        "generate_prompt_sha256": digest,
        "heal_prompt_sha256": digest,
        "qa_prompt_sha256": digest,
        "module_verifier_sha256": digest,
        "server_verifier_sha256": digest,
        "fixture_prompt_fingerprints": [
            {
                "fixture_id": fixture_id,
                "payload_sha256": (fixture_id.encode().hex() + "0" * 64)[:64],
            }
            for fixture_id in ("moon_phases_ar", "pendulum_ar")
        ],
    }


def _complete_raw(status: str = "complete") -> dict:
    fixtures = ("moon_phases_ar", "pendulum_ar")
    provenance = _provenance()
    fixture_hashes = {
        item["fixture_id"]: item["payload_sha256"]
        for item in provenance["fixture_prompt_fingerprints"]
    }
    cases = [
        *[_case(item, "gpt-5.6-terra", elapsed_ms=800) for item in fixtures],
        *[_case(item, "gpt-5.6-sol", elapsed_ms=1000) for item in fixtures],
    ]
    for case in cases:
        case["spec_sha256"] = fixture_hashes[case["fixture_id"]]
    return {
        "schema_version": "1.0",
        "acceptance_row": "ROUTE-02",
        "sanitized": True,
        "call_cap": 12,
        "status": status,
        "active_model": "gpt-5.6-sol",
        "evaluation_provenance": provenance,
        "cases": cases,
        "usage_observations": [
            {
                "model": "gpt-5.6-terra",
                "source": "codex_app_server_account_usage_read",
                "delta_units": 300,
                "turn_reported_tokens": 280,
                "sample_count": 2,
                "observed_before_at": "2026-07-21T19:00:00Z",
                "observed_after_at": "2026-07-21T19:01:00Z",
            },
            {
                "model": "gpt-5.6-sol",
                "source": "codex_app_server_account_usage_read",
                "delta_units": 400,
                "turn_reported_tokens": 280,
                "sample_count": 2,
                "observed_before_at": "2026-07-21T19:02:00Z",
                "observed_after_at": "2026-07-21T19:03:00Z",
            },
        ],
        "inflight": None,
    }


def _build_bound_report(
    repo_root: Path,
    raw: dict,
    *,
    routing_decision_path: Path,
    current_provenance: dict | None = None,
) -> dict:
    from scripts.evaluate_generation_routing import build_report_from_raw

    raw_path = _write_tracked_raw_evidence(repo_root, raw)
    _write_tracked_prior_aborted_evidence(repo_root)
    return build_report_from_raw(
        raw,
        current_provenance=current_provenance or _provenance(),
        routing_decision_path=routing_decision_path,
        raw_evidence_path=raw_path,
        repository_root=repo_root,
    )


def test_finalize_applies_measured_terra_from_the_closed_decision_file(tmp_path):
    from server.model_routing import BOUNDED_SINGLE_PARAMETER

    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [BOUNDED_SINGLE_PARAMETER])

    report = _build_bound_report(
        tmp_path,
        _complete_raw(),
        routing_decision_path=decision_path,
    )

    assert report["passed"] is True
    assert report["tier_decision"]["generation_model"] == "gpt-5.6-terra"
    assert report["tier_decision"]["decision_applied"] is True
    assert report["routing_decision_sha256"] == hashlib.sha256(
        decision_path.read_bytes()
    ).hexdigest()


def test_finalize_retains_sol_from_the_closed_decision_file(tmp_path):
    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [])
    raw = _complete_raw()
    raw["cases"][0]["passed"] = False
    raw["cases"][0]["failure_code"] = "deterministic_verification_failed"

    report = _build_bound_report(
        tmp_path,
        raw,
        routing_decision_path=decision_path,
    )

    assert report["passed"] is True
    assert report["tier_decision"]["generation_model"] == "gpt-5.6-sol"
    assert report["tier_decision"]["decision_applied"] is True


def test_final_report_rejects_post_report_routing_decision_change(tmp_path):
    from scripts.evaluate_generation_routing import validate_routing_report
    from server.model_routing import BOUNDED_SINGLE_PARAMETER

    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [BOUNDED_SINGLE_PARAMETER])
    report = _build_bound_report(
        tmp_path,
        _complete_raw(),
        routing_decision_path=decision_path,
    )

    _write_routing_decision(decision_path, [])
    with pytest.raises(ValueError, match="routing_decision_changed"):
        validate_routing_report(
            report,
            routing_decision_path=decision_path,
            repository_root=tmp_path,
            current_provenance=_provenance(),
        )


def test_final_report_rejects_tampered_terra_decision_when_cases_fail(tmp_path):
    from scripts.evaluate_generation_routing import validate_routing_report
    from server.model_routing import BOUNDED_SINGLE_PARAMETER

    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [BOUNDED_SINGLE_PARAMETER])
    report = _build_bound_report(
        tmp_path,
        _complete_raw(),
        routing_decision_path=decision_path,
    )
    report["cases"][0]["passed"] = False
    report["cases"][0]["failure_code"] = "deterministic_verification_failed"

    with pytest.raises(ValueError, match="routing_report_noncanonical"):
        validate_routing_report(
            report,
            routing_decision_path=decision_path,
            repository_root=tmp_path,
            current_provenance=_provenance(),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report["metrics_by_model"]["gpt-5.6-terra"].__setitem__(
            "passed_count", 1
        ),
        lambda report: report["gates"].__setitem__("terra_quality", False),
        lambda report: report["tier_decision"].__setitem__(
            "generation_model", "gpt-5.6-sol"
        ),
        lambda report: report.__setitem__("configured_terra_generation_tiers", []),
        lambda report: report["evaluation_set"][0].__setitem__(
            "spec_sha256", "b" * 64
        ),
        lambda report: report["evaluation_provenance"][
            "fixture_prompt_fingerprints"
        ][0].__setitem__("payload_sha256", "b" * 64),
    ],
)
def test_final_report_recomputes_every_derived_route_field(
    tmp_path, mutation
):
    from scripts.evaluate_generation_routing import validate_routing_report
    from server.model_routing import BOUNDED_SINGLE_PARAMETER

    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [BOUNDED_SINGLE_PARAMETER])
    report = _build_bound_report(
        tmp_path,
        _complete_raw(),
        routing_decision_path=decision_path,
    )
    mutation(report)

    with pytest.raises(ValueError, match="routing_report_noncanonical"):
        validate_routing_report(
            report,
            routing_decision_path=decision_path,
            repository_root=tmp_path,
            current_provenance=_provenance(),
        )


def test_final_report_cannot_forge_terra_pass_over_failing_tracked_raw(tmp_path):
    from scripts.evaluate_generation_routing import validate_routing_report
    from server.model_routing import BOUNDED_SINGLE_PARAMETER

    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [BOUNDED_SINGLE_PARAMETER])
    report = _build_bound_report(
        tmp_path,
        _complete_raw(),
        routing_decision_path=decision_path,
    )
    failing_raw = _complete_raw()
    failing_raw["cases"][0]["passed"] = False
    failing_raw["cases"][0]["failure_code"] = "deterministic_verification_failed"
    raw_path = _write_tracked_raw_evidence(tmp_path, failing_raw)
    report["raw_evidence_path"] = "out/evidence/route-02-raw.json"
    report["raw_evidence_sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="routing_report_noncanonical"):
        validate_routing_report(
            report,
            routing_decision_path=decision_path,
            repository_root=tmp_path,
            current_provenance=_provenance(),
        )


def test_final_report_cannot_alter_head_commit_from_tracked_raw(tmp_path):
    from scripts.evaluate_generation_routing import (
        build_report_from_raw,
        validate_routing_report,
    )
    from server.model_routing import BOUNDED_SINGLE_PARAMETER

    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [BOUNDED_SINGLE_PARAMETER])
    raw = _complete_raw()
    raw_path = _write_tracked_raw_evidence(tmp_path, raw)
    _write_tracked_prior_aborted_evidence(tmp_path)
    report = build_report_from_raw(
        raw,
        current_provenance=_provenance(),
        routing_decision_path=decision_path,
        raw_evidence_path=raw_path,
        repository_root=tmp_path,
    )
    report["raw_evidence_path"] = "out/evidence/route-02-raw.json"
    report["raw_evidence_sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    report["evaluation_provenance"]["head_commit"] = "b" * 40

    with pytest.raises(ValueError, match="routing_report_noncanonical"):
        validate_routing_report(
            report,
            routing_decision_path=decision_path,
            repository_root=tmp_path,
            current_provenance=_provenance(),
        )


def test_release_validation_rejects_forged_raw_and_report_head(tmp_path):
    from scripts.evaluate_generation_routing import validate_routing_report
    from server.model_routing import BOUNDED_SINGLE_PARAMETER

    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [BOUNDED_SINGLE_PARAMETER])
    forged_raw = _complete_raw()
    forged_raw["evaluation_provenance"] = _provenance("b")
    report = _build_bound_report(
        tmp_path,
        forged_raw,
        routing_decision_path=decision_path,
        current_provenance=_provenance("b"),
    )

    with pytest.raises(ValueError, match="evaluation_provenance_changed"):
        validate_routing_report(
            report,
            routing_decision_path=decision_path,
            repository_root=tmp_path,
            current_provenance=_provenance("a"),
            require_current_provenance=True,
        )


def test_finalize_requires_raw_evidence_to_be_git_tracked(tmp_path):
    from scripts.evaluate_generation_routing import build_report_from_raw

    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [])
    raw = _complete_raw()
    raw_path = tmp_path / "out" / "evidence" / "route-02-raw.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    with pytest.raises(ValueError, match="routing_raw_evidence_untracked"):
        build_report_from_raw(
            raw,
            current_provenance=_provenance(),
            routing_decision_path=decision_path,
            raw_evidence_path=raw_path,
            repository_root=tmp_path,
        )


def test_prior_aborted_evidence_requires_both_closed_tracked_records(tmp_path):
    import scripts.evaluate_generation_routing as evaluation

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _write_tracked_prior_aborted_evidence(tmp_path)
    records = evaluation._load_prior_aborted_evidence(tmp_path)

    assert [item["path"] for item in records] == list(
        evaluation.PRIOR_ABORTED_EVIDENCE_PATHS
    )
    assert sum(item["live_call_count_conservative"] for item in records) == 2

    first_path = tmp_path / records[0]["path"]
    first = json.loads(first_path.read_text(encoding="utf-8"))
    first["raw_model_output"] = "forbidden"
    first_path.write_text(json.dumps(first), encoding="utf-8")
    with pytest.raises(ValueError, match="prior_aborted_evidence_changed"):
        evaluation._load_prior_aborted_evidence(tmp_path)


def test_final_report_rejects_raw_bytes_changed_after_finalize(tmp_path):
    from scripts.evaluate_generation_routing import validate_routing_report

    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [])
    raw = _complete_raw()
    raw["cases"][0]["passed"] = False
    raw["cases"][0]["failure_code"] = "deterministic_verification_failed"
    report = _build_bound_report(
        tmp_path,
        raw,
        routing_decision_path=decision_path,
    )
    raw_path = tmp_path / report["raw_evidence_path"]
    raw_path.write_text(raw_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="routing_raw_evidence_changed"):
        validate_routing_report(
            report,
            routing_decision_path=decision_path,
            repository_root=tmp_path,
            current_provenance=_provenance(),
        )


def test_final_report_rejects_prior_aborted_evidence_changed_after_finalize(tmp_path):
    from scripts.evaluate_generation_routing import validate_routing_report

    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [])
    raw = _complete_raw()
    raw["cases"][0]["passed"] = False
    raw["cases"][0]["failure_code"] = "deterministic_verification_failed"
    report = _build_bound_report(
        tmp_path,
        raw,
        routing_decision_path=decision_path,
    )
    prior_path = tmp_path / report["prior_aborted_evidence"][0]["path"]
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    prior["reason"] = "Still sanitized, but changed after the report was finalized."
    prior_path.write_text(json.dumps(prior), encoding="utf-8")

    with pytest.raises(ValueError, match="routing_report_noncanonical"):
        validate_routing_report(
            report,
            routing_decision_path=decision_path,
            repository_root=tmp_path,
            current_provenance=_provenance(),
        )


def test_measurement_fingerprint_excludes_only_the_data_decision(tmp_path, monkeypatch):
    import scripts.evaluate_generation_routing as evaluation

    (tmp_path / "server").mkdir()
    decision_path = tmp_path / "server" / "routing_decision.json"
    settings_path = tmp_path / "server" / "settings.py"
    _write_routing_decision(decision_path, [])
    settings_path.write_text("SETTING = 'measured'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Laysh", "-c", "user.email=laysh@example.invalid", "add", "."],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Laysh",
            "-c",
            "user.email=laysh@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    git_path = shutil.which("git")
    assert git_path is not None
    baseline = evaluation._worktree_fingerprint(git_path)

    _write_routing_decision(decision_path, ["bounded_single_parameter_v1"])
    assert evaluation._worktree_fingerprint(git_path) == baseline

    settings_path.write_text("SETTING = 'drifted'\n", encoding="utf-8")
    drifted_digest, drifted = evaluation._worktree_fingerprint(git_path)
    assert drifted is True
    assert drifted_digest != baseline[0]


def test_release_provenance_accepts_descendant_evidence_commit_but_not_source_drift(
    tmp_path,
    monkeypatch,
):
    import scripts.evaluate_generation_routing as evaluation

    _require_measured_provenance_compatible_with_current = (
        evaluation._require_measured_provenance_compatible_with_current
    )

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Laysh"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "laysh@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    settings_path = tmp_path / "server" / "settings.py"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("SETTING = 'measured'\n", encoding="utf-8")
    subprocess.run(["git", "add", "server/settings.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "source"], cwd=tmp_path, check=True)
    measured = _provenance()
    measured["worktree_state_sha256"] = hashlib.sha256(b"").hexdigest()
    measured["head_commit"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    measured_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    ).stdout.strip()
    measured["head_tree_sha256"] = hashlib.sha256(measured_tree).hexdigest()
    stable_fields = (
        "source_snapshot_sha256",
        "evaluator_sha256",
        "runtime_sha256",
        "generate_prompt_sha256",
        "heal_prompt_sha256",
        "qa_prompt_sha256",
        "module_verifier_sha256",
        "server_verifier_sha256",
        "fixture_prompt_fingerprints",
    )
    monkeypatch.setattr(
        evaluation,
        "_provenance_content_fields",
        lambda _reader: {
            field: deepcopy(measured[field]) for field in stable_fields
        },
    )

    evidence_path = tmp_path / "out" / "evidence" / "route-02-raw.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text("{}\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "out/evidence/route-02-raw.json"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "commit", "-qm", "evidence"], cwd=tmp_path, check=True)
    current = deepcopy(measured)
    current["head_commit"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    current_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    ).stdout.strip()
    current["head_tree_sha256"] = hashlib.sha256(current_tree).hexdigest()

    _require_measured_provenance_compatible_with_current(
        measured,
        current,
        repository_root=tmp_path,
        allow_descendant_head=True,
    )

    settings_path.write_text("SETTING = 'drifted'\n", encoding="utf-8")
    subprocess.run(["git", "add", "server/settings.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "source drift"], cwd=tmp_path, check=True)
    current["head_commit"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    current_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    ).stdout.strip()
    current["head_tree_sha256"] = hashlib.sha256(current_tree).hexdigest()
    # This is the hostile shape: raw evidence claims the old measured commit/tree,
    # while copying every stable digest from the newer source commit.
    measured.update(
        {
            field: deepcopy(current[field])
            for field in stable_fields
        }
    )
    with pytest.raises(ValueError, match="evaluation_provenance_changed"):
        _require_measured_provenance_compatible_with_current(
            measured,
            current,
            repository_root=tmp_path,
            allow_descendant_head=True,
        )


def test_release_provenance_recomputes_claimed_hashes_from_measured_git_blobs(
    tmp_path,
    monkeypatch,
):
    import scripts.evaluate_generation_routing as evaluation

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Laysh"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "laysh@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    settings_path = tmp_path / "server" / "settings.py"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("SETTING = 'measured'\n", encoding="utf-8")
    subprocess.run(["git", "add", "server/settings.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "measured"], cwd=tmp_path, check=True)
    measured_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    measured_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    ).stdout.strip()

    evidence_path = tmp_path / "out" / "evidence" / "route-02-raw.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text("{}\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "out/evidence/route-02-raw.json"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "commit", "-qm", "evidence"], cwd=tmp_path, check=True)
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    current_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    ).stdout.strip()

    monkeypatch.setattr(
        evaluation,
        "DIRECT_PROVENANCE_PATHS",
        {"runtime_sha256": "server/settings.py"},
    )
    monkeypatch.setattr(
        evaluation,
        "SOURCE_SNAPSHOT_PATHS",
        ("server/settings.py",),
    )
    monkeypatch.setattr(evaluation, "FIXTURE_IDS", ())
    monkeypatch.setattr(evaluation, "FIXTURE_GOLDEN_PATHS", {})
    measured = _provenance()
    measured.update(
        {
            "head_commit": measured_commit,
            "head_tree_sha256": hashlib.sha256(measured_tree).hexdigest(),
            "worktree_state_sha256": hashlib.sha256(b"").hexdigest(),
            "worktree_dirty": False,
            # Forge both sides consistently. Only the historical blob proves it false.
            "runtime_sha256": "f" * 64,
        }
    )
    current = deepcopy(measured)
    current.update(
        {
            "head_commit": current_commit,
            "head_tree_sha256": hashlib.sha256(current_tree).hexdigest(),
        }
    )

    with pytest.raises(ValueError, match="evaluation_provenance_changed"):
        evaluation._require_measured_provenance_compatible_with_current(
            measured,
            current,
            repository_root=tmp_path,
            allow_descendant_head=True,
        )


def test_final_report_can_anchor_to_a_tracked_release_commit_and_checks_later_head(
    tmp_path,
    monkeypatch,
):
    import scripts.evaluate_generation_routing as evaluation
    from server.model_routing import BOUNDED_SINGLE_PARAMETER

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Laysh"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "laysh@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    settings_path = tmp_path / "server" / "settings.py"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("SETTING = 'stable'\n", encoding="utf-8")
    subprocess.run(["git", "add", "server/settings.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "measured source"], cwd=tmp_path, check=True)
    measured_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    measured_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    ).stdout.strip()
    raw = _complete_raw()
    raw["evaluation_provenance"].update(
        {
            "head_commit": measured_commit,
            "head_tree_sha256": hashlib.sha256(measured_tree).hexdigest(),
            "worktree_state_sha256": hashlib.sha256(b"").hexdigest(),
            "worktree_dirty": False,
        }
    )
    stable_fields = {
        field: deepcopy(raw["evaluation_provenance"][field])
        for field in (
            "source_snapshot_sha256",
            "evaluator_sha256",
            "runtime_sha256",
            "generate_prompt_sha256",
            "heal_prompt_sha256",
            "qa_prompt_sha256",
            "module_verifier_sha256",
            "server_verifier_sha256",
            "fixture_prompt_fingerprints",
        )
    }
    monkeypatch.setattr(
        evaluation,
        "_provenance_content_fields",
        lambda _reader: deepcopy(stable_fields),
    )

    decision_path = tmp_path / "server" / "routing_decision.json"
    _write_routing_decision(decision_path, [BOUNDED_SINGLE_PARAMETER])
    raw_path = _write_tracked_raw_evidence(tmp_path, raw)
    _write_tracked_prior_aborted_evidence(tmp_path)
    report = evaluation.build_report_from_raw(
        raw,
        current_provenance=raw["evaluation_provenance"],
        routing_decision_path=decision_path,
        raw_evidence_path=raw_path,
        repository_root=tmp_path,
    )
    report_path = tmp_path / "out" / "evidence" / "route-02-routing-evaluation.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    subprocess.run(
        [
            "git",
            "add",
            "server/routing_decision.json",
            "out/evidence/route-02-raw.json",
            "out/evidence/route-02-routing-evaluation.json",
        ],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "commit", "-qm", "route evidence"], cwd=tmp_path, check=True)
    # RELEASE anchors to the verified source commit; route decision/evidence are
    # necessarily committed later without changing executable sources.
    release_commit = measured_commit

    later_evidence = tmp_path / "out" / "evidence" / "release-01.json"
    later_evidence.write_text("{}\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "out/evidence/release-01.json"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "commit", "-qm", "release evidence"], cwd=tmp_path, check=True)

    assert evaluation.validate_routing_report(
        report,
        routing_decision_path=decision_path,
        repository_root=tmp_path,
        current_commit=release_commit,
    )["passed"] is True

    settings_path.write_text("SETTING = 'drifted'\n", encoding="utf-8")
    subprocess.run(["git", "add", "server/settings.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "late source drift"], cwd=tmp_path, check=True)
    with pytest.raises(ValueError, match="evaluation_provenance_changed"):
        evaluation.validate_routing_report(
            report,
            routing_decision_path=decision_path,
            repository_root=tmp_path,
            current_commit=release_commit,
        )


def test_finalize_requires_a_closed_completed_raw_cohort():
    from scripts.evaluate_generation_routing import build_report_from_raw

    with pytest.raises(ValueError, match="raw_evidence_incomplete"):
        build_report_from_raw(
            _complete_raw("cohort_complete"),
            configured_terra_tiers=set(),
            current_provenance=_provenance(),
        )

    raw = _complete_raw()
    raw["raw_model_output"] = "must-not-enter-evidence"
    with pytest.raises(ValueError, match="raw_evidence_invalid"):
        build_report_from_raw(
            raw,
            configured_terra_tiers=set(),
            current_provenance=_provenance(),
        )


def test_finalize_rejects_provenance_drift_and_fixture_hash_substitution():
    from scripts.evaluate_generation_routing import build_report_from_raw

    with pytest.raises(ValueError, match="evaluation_provenance_changed"):
        build_report_from_raw(
            _complete_raw(),
            configured_terra_tiers=set(),
            current_provenance=_provenance("b"),
        )

    raw = _complete_raw()
    raw["cases"][0]["spec_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="raw_evidence_invalid"):
        build_report_from_raw(
            raw,
            configured_terra_tiers=set(),
            current_provenance=_provenance(),
        )


def test_final_report_contract_is_closed_and_cross_checked(tmp_path):
    from scripts.evaluate_generation_routing import validate_routing_report

    decision_path = tmp_path / "routing-decision.json"
    _write_routing_decision(decision_path, [])
    raw = _complete_raw()
    raw["cases"][0]["passed"] = False
    raw["cases"][0]["failure_code"] = "deterministic_verification_failed"
    report = _build_bound_report(
        tmp_path,
        raw,
        routing_decision_path=decision_path,
    )
    assert validate_routing_report(
        report,
        routing_decision_path=decision_path,
        repository_root=tmp_path,
        current_provenance=_provenance(),
    ) == report

    report["raw_model_output"] = "must-not-enter-final-evidence"
    with pytest.raises(ValueError, match="routing_report_invalid"):
        validate_routing_report(
            report,
            routing_decision_path=decision_path,
            repository_root=tmp_path,
            current_provenance=_provenance(),
        )


def test_cli_has_no_manual_account_usage_override(tmp_path):
    from scripts.evaluate_generation_routing import _parser

    with pytest.raises(SystemExit):
        _parser().parse_args(
            ["--finalize", "--usage-json", str(tmp_path / "untrusted-usage.json")]
        )


def test_live_cohort_checkpoints_before_spend_and_refuses_provenance_drift(
    tmp_path, monkeypatch
):
    import scripts.evaluate_generation_routing as evaluation

    raw_path = tmp_path / "route.json"
    snapshots: list[dict] = []
    real_atomic = evaluation._atomic_json

    def recording_atomic(path: Path, document: dict):
        snapshots.append(deepcopy(document))
        real_atomic(path, document)

    usage_values = iter([1000, 1280, 1280])
    real_sleep = asyncio.sleep

    async def usage_reader():
        return next(usage_values)

    async def fake_case(*, fixture_id, model, executor, checkpoint):
        del executor
        checkpoint(
            "before_stage",
            {"fixture_id": fixture_id, "model": model, "stage": "generate"},
            [],
        )
        case = _case(fixture_id, model)
        checkpoint(
            "after_stage",
            {"fixture_id": fixture_id, "model": model, "stage": "generate"},
            case["live_calls"],
        )
        return case

    monkeypatch.setattr(evaluation, "_atomic_json", recording_atomic)
    monkeypatch.setattr(evaluation, "_evaluation_provenance", lambda: _provenance())
    monkeypatch.setattr(
        evaluation,
        "_load_prior_aborted_evidence",
        lambda _root: _prior_aborted_evidence(),
    )
    monkeypatch.setattr(evaluation, "read_account_lifetime_tokens", usage_reader)
    monkeypatch.setattr(evaluation, "_evaluate_case", fake_case)
    monkeypatch.setattr(evaluation.asyncio, "sleep", lambda _: real_sleep(0))
    dependencies = evaluation.LiveEvaluationDependencies(
        usage_reader=usage_reader,
        case_evaluator=fake_case,
        executor_factory=object,
        sleep=lambda _: real_sleep(0),
    )

    raw = asyncio.run(
        evaluation.run_live_cohort(
            model="gpt-5.6-terra",
            raw_path=raw_path,
            append=False,
            confirmed=True,
            dependencies=dependencies,
        )
    )

    assert snapshots[0]["status"] == "reserved"
    assert snapshots[0]["cases"] == []
    assert any(
        item["status"] == "running"
        and item["inflight"]["event"] == "before_stage"
        for item in snapshots
    )
    assert raw["status"] == "cohort_complete"
    assert raw["usage_observations"][0]["delta_units"] == 280

    monkeypatch.setattr(evaluation, "_evaluation_provenance", lambda: _provenance("b"))
    with pytest.raises(ValueError, match="evaluation_provenance_changed"):
        asyncio.run(
            evaluation.run_live_cohort(
                model="gpt-5.6-sol",
                raw_path=raw_path,
                append=True,
                confirmed=True,
                dependencies=dependencies,
            )
        )


def test_live_cohort_holds_an_exclusive_lock_across_the_spend_window(
    tmp_path, monkeypatch
):
    import scripts.evaluate_generation_routing as evaluation

    raw_path = tmp_path / "route.json"
    first_reader_entered = asyncio.Event()
    release_first_reader = asyncio.Event()
    readings = iter([1000, 1280, 1280])

    async def usage_reader():
        value = next(readings)
        if value == 1000:
            first_reader_entered.set()
            await release_first_reader.wait()
        return value

    async def fake_case(*, fixture_id, model, executor, checkpoint):
        del executor, checkpoint
        return _case(fixture_id, model)

    monkeypatch.setattr(evaluation, "_evaluation_provenance", lambda: _provenance())
    monkeypatch.setattr(
        evaluation,
        "_load_prior_aborted_evidence",
        lambda _root: _prior_aborted_evidence(),
    )
    dependencies = evaluation.LiveEvaluationDependencies(
        usage_reader=usage_reader,
        case_evaluator=fake_case,
        executor_factory=object,
        sleep=lambda _: asyncio.sleep(0),
    )

    async def scenario():
        first = asyncio.create_task(
            evaluation.run_live_cohort(
                model="gpt-5.6-terra",
                raw_path=raw_path,
                append=False,
                confirmed=True,
                dependencies=dependencies,
            )
        )
        await first_reader_entered.wait()
        with pytest.raises(ValueError, match="routing_evaluation_locked"):
            await evaluation.run_live_cohort(
                model="gpt-5.6-terra",
                raw_path=tmp_path / "different-output.json",
                append=False,
                confirmed=True,
                dependencies=dependencies,
            )
        release_first_reader.set()
        await first

    asyncio.run(scenario())
