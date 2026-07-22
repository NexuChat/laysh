from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
import zlib
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

EXPECTED_ACCEPTANCE_ROWS = (
    "BASE-01",
    "BASE-02",
    "TEST-01",
    "EVID-01",
    "EVID-02",
    "CONTRACT-01",
    "TEACH-01",
    "TEACH-02",
    "MOTION-01",
    "MOTION-02",
    "MOTION-03",
    "MOTION-04",
    "VQA-01",
    "VISUAL-01",
    "SHARE-01",
    "SHARE-02",
    "LIB-01",
    "I18N-01",
    "I18N-02",
    "UI-01",
    "UI-02",
    "ASSET-01",
    "REL-01",
    "REL-02",
    "GEN-01",
    "EXP-01",
    "GOLD-01",
    "ROUTE-01",
    "ROUTE-02",
    "RELEASE-01",
)
ACCEPTANCE_ROW_TEST_NODEIDS: dict[str, tuple[str, ...]] = {
    "BASE-01": (
        "tests/test_session_provenance.py::test_root_session_manifest_matches_the_current_linear_history",
    ),
    "BASE-02": (
        "tests/test_baseline_provenance.py::test_locked_baseline_identity_counts_and_coverage_agree",
    ),
    "TEST-01": (
        "tests/test_release_report.py::test_release_report_rejects_silent_skips_unknown_fields_and_unsafe_paths",
        "tests/test_release_report.py::test_release_report_rejects_a_spoofed_coverage_baseline",
    ),
    "EVID-01": (
        "tests/test_session_provenance.py::test_future_commit_requires_the_exact_root_session_trailer",
    ),
    "EVID-02": (
        "tests/test_contracts.py::test_runtime_stage_receipt_is_closed_to_allowed_gpt_5_6_models",
        "tests/test_pipeline.py::test_public_runtime_receipts_preserve_every_stage_without_mislabeling_generation",
        "tests/test_pipeline.py::test_public_runtime_receipts_retain_a_sanitized_understand_fallback_attempt",
    ),
    "CONTRACT-01": (
        "tests/test_continuation_contracts.py::test_generated_source_limit_is_96_kib_of_utf8_bytes",
        "tests/test_continuation_contracts.py::test_schema_prompt_and_project_skill_do_not_impose_a_smaller_source_limit",
    ),
    "TEACH-01": (
        "tests/test_continuation_pedagogy.py::test_misconceptions_require_an_explicit_localized_correction",
        "tests/test_continuation_pedagogy.py::test_curated_review_rejects_an_uncorrected_misconception",
    ),
    "TEACH-02": (
        "tests/test_continuation_pedagogy.py::test_trusted_shell_labels_misconceptions_and_never_locks_the_primary_control",
    ),
    "MOTION-01": (
        "tests/test_continuation_motion_contract.py::test_simulatable_lesson_requires_a_closed_actor_and_action",
        "tests/test_continuation_motion_contract.py::test_actor_and_action_values_are_closed",
        "tests/test_continuation_motion_contract.py::test_curated_review_requires_the_fixture_actor_and_action",
    ),
    "MOTION-02": (
        "tests/test_continuation_actor_tracking.py::test_actor_tracking_rejects_decorative_motion_and_invisible_actors",
        "tests/test_continuation_actor_tracking_browser.py::test_browser_probe_rejects_decorative_or_missing_actor_motion",
        "tests/test_continuation_actor_tracking_browser.py::test_all_six_pinned_goldens_pass_actor_only_browser_tracking",
    ),
    "MOTION-03": (
        "tests/test_continuation_physics_motion.py::test_moon_phase_proof_requires_orbit_and_illumination_geometry",
        "tests/test_continuation_physics_motion.py::test_pendulum_proof_requires_reversal_and_a_period_from_length_model",
        "tests/test_continuation_physics_motion.py::test_day_night_proof_requires_landmark_rotation_against_fixed_light",
        "tests/test_continuation_physics_motion.py::test_sound_proof_requires_spatial_phase_not_an_amplitude_pulse",
        "tests/test_continuation_physics_motion.py::test_circuit_proof_requires_carrier_motion_to_increase_with_current",
        "tests/test_continuation_physics_motion.py::test_buoyancy_proof_requires_model_consistent_equilibrium_at_waterline",
        "tests/test_continuation_physics_motion_browser.py::test_all_six_pinned_goldens_prove_their_declared_physics_in_browser",
    ),
    "MOTION-04": (
        "tests/test_continuation_shared_model_state.py::test_shared_state_static_contract_rejects_a_deliberately_divergent_visual_model",
        "tests/test_continuation_shared_model_state.py::test_candidate_verification_rejects_a_divergent_visual_model_even_when_numeric_tests_pass",
        "tests/test_continuation_shared_model_state.py::test_all_six_pinned_goldens_declare_a_single_shared_model_state",
    ),
    "VQA-01": (
        "tests/test_continuation_visual_qa.py::test_visual_qa_schema_is_closed_strict_and_requires_the_four_verdict_fields",
        "tests/test_continuation_visual_qa.py::test_visual_qa_can_never_promote_a_failed_deterministic_gate",
    ),
    "VISUAL-01": (
        "tests/test_readout_visibility.py::test_verification_rejects_outputs_that_remain_dead_at_the_precision_cap",
        "tests/test_embedded_simulation_visibility.py::test_every_gallery_simulation_is_visible_and_unclipped_at_supported_sizes",
        "tests/test_m7_accessibility.py::test_night_observatory_text_pairs_meet_wcag_aa",
        "tests/test_m7_accessibility.py::test_dark_theme_keeps_visible_focus_and_reduced_motion_rules",
    ),
    "SHARE-01": (
        "tests/test_sharing.py::test_completed_artifact_gets_a_stable_privacy_safe_share_url",
        "tests/test_sharing.py::test_model_echoed_learner_question_never_becomes_share_persistence",
        "tests/test_cache.py::test_pipeline_never_caches_or_shares_an_artifact_echoing_its_question",
    ),
    "SHARE-02": (
        "tests/test_sharing.py::test_share_survives_application_restart_and_serves_only_the_portable_artifact",
        "tests/test_sharing.py::test_expired_missing_and_identifier_tampered_shares_fail_the_same_closed_way",
        "tests/test_sharing.py::test_share_storage_rejects_symlink_root",
        "tests/test_sharing.py::test_expiry_cleanup_does_not_delete_a_racing_replacement",
    ),
    "LIB-01": (
        "tests/test_library_playback.py::test_six_library_shells_reassemble_deterministically_without_model_calls",
        "tests/test_library_playback_browser.py::test_six_pinned_lesson_modules_self_play_and_yield_to_controls",
    ),
    "I18N-01": (
        "tests/test_continuation_i18n.py::test_locale_inventory_covers_both_languages_and_every_core_failure_surface",
        "tests/test_continuation_i18n.py::test_gallery_results_are_localized_before_they_are_served",
        "tests/test_continuation_i18n.py::test_direction_contract_covers_application_and_existing_portable_shell",
        "tests/test_continuation_i18n_browser.py::test_ar_en_snapshots_direction_and_locale_control_event_scope",
    ),
    "I18N-02": (
        "tests/test_continuation_i18n.py::test_application_loads_locale_assets_and_exposes_an_explicit_locale_control",
        "tests/test_continuation_i18n_browser.py::test_ar_en_snapshots_direction_and_locale_control_event_scope",
    ),
    "UI-01": (
        "tests/test_embedded_simulation_visibility.py::test_every_gallery_simulation_is_visible_and_unclipped_at_supported_sizes",
        "tests/test_m4_browser.py::test_g4_mock_journeys_accessibility_and_accepted_screenshots",
    ),
    "UI-02": (
        "tests/test_embedded_simulation_visibility.py::test_every_gallery_simulation_is_visible_and_unclipped_at_supported_sizes",
    ),
    "ASSET-01": (
        "tests/test_static_asset_versioning.py::test_frozen_asset_manifest_matches_runtime_assets_and_gallery_contract",
        "tests/test_static_asset_versioning.py::test_document_versions_entrypoints_and_preloaded_fonts_without_duplicate_fetches",
        "tests/test_static_asset_versioning.py::test_production_application_routes_static_assets_through_version_gate",
        "tests/test_static_asset_versioning.py::test_manifest_fails_closed_when_a_versioned_asset_changes",
        "tests/test_static_asset_browser.py::test_versioned_assets_load_immutably_in_a_fresh_browser_profile",
    ),
    "REL-01": (
        "tests/test_pipeline.py::test_generate_failure_after_answer_preserves_the_safe_answer_as_answer_only",
        "tests/test_pipeline.py::test_every_downstream_failure_after_answer_falls_back_without_artifact",
        "tests/test_pipeline.py::test_assembly_failure_after_answer_exhausts_repairs_without_losing_the_answer",
        "tests/test_pipeline.py::test_cache_write_failure_keeps_a_verified_playable_result_after_answer",
    ),
    "REL-02": (
        "tests/test_pipeline.py::test_malformed_simulation_slice_preserves_a_safe_answer_without_generation",
        "tests/test_pipeline.py::test_partial_module_slice_falls_back_without_a_verified_label_or_cache_write",
        "tests/test_pipeline.py::test_contradictory_simulation_contract_never_enters_verified_cache",
    ),
    "GEN-01": (
        "tests/test_generation_prompt_ownership.py::test_failed_html_fixture_keeps_shell_owned_and_generation_route_snapshotted",
        "tests/test_codex_backend_live.py::test_generate_prompt_states_the_exact_runtime_interface_contract",
    ),
    "EXP-01": (
        "tests/test_experimental_promotion.py::test_experimental_route_cannot_enter_stable_cache_with_any_gate_missing",
        "tests/test_experimental_promotion.py::test_fully_gated_experimental_route_retains_its_label_in_stable_cache",
        "tests/test_experimental_promotion.py::test_stable_route_rejects_unknown_route_labels",
        "tests/test_experimental_promotion.py::test_existing_generation_pipeline_explicitly_labels_its_stable_route",
    ),
    "GOLD-01": (
        "tests/test_golden_release_report.py::test_gold_01_report_covers_six_hash_bound_bilingual_goldens",
        "tests/test_golden_release_report.py::test_gold_01_report_fails_closed_on_manifest_hash_drift",
        "tests/test_golden_release_report.py::test_gold_01_report_fails_closed_on_any_browser_or_a11y_failure",
        "tests/test_golden_release_report.py::test_gold_01_report_fails_closed_on_screenshot_hash_drift",
        "tests/test_golden_release_browser.py::test_gold_01_reviews_six_goldens_in_arabic_and_english",
    ),
    "ROUTE-01": (
        "tests/test_model_routing.py::test_generation_tiers_default_to_direct_sol_until_evidence_enables_terra",
        "tests/test_model_routing.py::test_public_luna_classification_failure_retries_once_on_terra",
        "tests/test_model_routing.py::test_terra_generation_failure_never_starts_a_fresh_sol_generation",
        "tests/test_model_routing.py::test_heal_uses_generation_model_then_allows_one_final_sol_attempt",
        "tests/test_settings.py::test_runtime_defaults_are_gpt_5_6_family_only",
        "tests/test_codex_backend_live.py::test_curated_generate_heal_and_ordinary_qa_stay_sol",
    ),
    "ROUTE-02": (
        "tests/test_routing_evaluation.py::test_bounded_route_report_adopts_terra_only_from_complete_observed_evidence",
        "tests/test_routing_evaluation.py::test_route_decision_cannot_pass_until_runtime_config_matches_it",
        "tests/test_routing_evaluation.py::test_route_report_keeps_direct_sol_and_passes_when_measured_terra_quality_fails",
        "tests/test_routing_evaluation.py::test_route_report_rejects_call_cap_and_cross_model_heal",
        "tests/test_routing_evaluation.py::test_release_validation_rejects_forged_raw_and_report_head",
        "tests/test_routing_evaluation.py::test_release_provenance_accepts_descendant_evidence_commit_but_not_source_drift",
    ),
}
RELEASE_REPORT_PATH = "out/evidence/release-01.json"
ROOT = Path(__file__).parents[1]


def _repository_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or path.parts[0] in {"", "."}
        or ".." in path.parts
        or "\\" in value
    ):
        raise ValueError("expected a repository-relative evidence path")
    return value


EvidencePath = Annotated[str, Field(min_length=1), AfterValidator(_repository_relative_path)]
CommitHash = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmptyText = Annotated[str, Field(min_length=1, max_length=500)]
Status = Literal["not-started", "failing", "passing", "blocked"]


class ClosedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AcceptanceRowEvidence(ClosedEvidence):
    id: str = Field(pattern=r"^[A-Z0-9]+(?:-[A-Z0-9]+)?-\d{2}$")
    status: Status
    evidence_paths: list[EvidencePath] = Field(max_length=20)

    @model_validator(mode="after")
    def require_named_evidence_for_passing_row(self) -> AcceptanceRowEvidence:
        if self.status == "passing" and not self.evidence_paths:
            raise ValueError("passing acceptance row needs named evidence")
        return self


class PytestSuiteEvidence(ClosedEvidence):
    name: Literal["unit_integration", "browser"]
    command: NonEmptyText
    passed: bool
    tests_passed: int = Field(ge=0)
    failures: int = Field(ge=0)
    errors: int = Field(ge=0)
    skipped: int = Field(ge=0)
    skip_explanations: list[NonEmptyText] = Field(max_length=50)
    duration_seconds: float = Field(ge=0)
    junit_path: EvidencePath
    commit: CommitHash

    @model_validator(mode="after")
    def require_one_explanation_per_skip(self) -> PytestSuiteEvidence:
        if len(self.skip_explanations) != self.skipped:
            raise ValueError("skip explanations must match the exact skipped count")
        return self


class CoverageEvidence(ClosedEvidence):
    command: NonEmptyText
    passed: bool
    tests_passed: int = Field(ge=0)
    deselected: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)
    baseline_percent: float = Field(ge=0, le=100)
    baseline_drop_explanation: str = Field(max_length=500)
    json_path: EvidencePath
    commit: CommitHash

    @model_validator(mode="after")
    def explain_baseline_drop(self) -> CoverageEvidence:
        if self.baseline_percent != 90.01:
            raise ValueError("coverage baseline must remain 90.01")
        if self.percent < self.baseline_percent and not self.baseline_drop_explanation.strip():
            raise ValueError("coverage below baseline needs an explanation")
        return self


class AccessibilityEvidence(ClosedEvidence):
    command: NonEmptyText
    passed: bool
    tests_passed: int = Field(ge=0)
    failures: int = Field(ge=0)
    skipped: int = Field(ge=0)
    violations: int = Field(ge=0)
    evidence_path: EvidencePath
    commit: CommitHash


class QualityEvidence(ClosedEvidence):
    ruff_passed: bool
    diff_check_passed: bool
    no_example_specific_runtime_passed: bool
    no_example_specific_runtime_violations: int = Field(ge=0)
    session_provenance_passed: bool
    session_roots: int = Field(ge=0)
    merge_commits: int = Field(ge=0)
    unlinked_commits: int = Field(ge=0)
    evidence_paths: list[EvidencePath] = Field(min_length=2, max_length=20)
    commit: CommitHash


class GoldEvidence(ClosedEvidence):
    passed: bool
    golden_count: int = Field(ge=0)
    locale_journey_count: int = Field(ge=0)
    screenshot_count: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    evidence_path: EvidencePath
    commit: CommitHash


class RoutingEvidence(ClosedEvidence):
    passed: bool
    route_01_passed: bool
    route_02_passed: bool
    decision_applied: bool
    generation_model: Literal["gpt-5.6-terra", "gpt-5.6-sol"]
    cohort_live_calls: int = Field(ge=1, le=10)
    prior_aborted_live_calls: Literal[2]
    total_live_calls: int = Field(ge=3, le=12)
    evidence_path: EvidencePath
    commit: CommitHash

    @model_validator(mode="after")
    def bind_total_call_budget(self) -> RoutingEvidence:
        if self.total_live_calls != (
            self.cohort_live_calls + self.prior_aborted_live_calls
        ):
            raise ValueError("routing total calls must include prior aborted calls")
        return self


class ServiceEvidence(ClosedEvidence):
    passed: bool
    active: bool
    restarted_commit: CommitHash
    healthz_green: bool
    gallery_count: int = Field(ge=0)
    instant_gallery_passed: bool
    health_evidence_path: EvidencePath
    gallery_evidence_path: EvidencePath
    commit: CommitHash


class AssetEvidence(ClosedEvidence):
    passed: bool
    manifest_compatible: bool
    clean_browser_smoke_passed: bool
    bundle_sha256: Sha256
    evidence_path: EvidencePath
    commit: CommitHash


class CleanCheckoutEvidence(ClosedEvidence):
    passed: bool
    tracked_status_clean: bool
    tests_passed: int = Field(ge=0)
    failures: int = Field(ge=0)
    ruff_passed: bool
    evidence_path: EvidencePath
    commit: CommitHash


class OwnerBoundaryEvidence(ClosedEvidence):
    owner_only_actions: list[NonEmptyText] = Field(min_length=1, max_length=20)
    deviations: list[NonEmptyText] = Field(max_length=20)
    risks: list[NonEmptyText] = Field(max_length=20)
    next_actions: list[NonEmptyText] = Field(min_length=1, max_length=20)


class ReleaseEvidence(ClosedEvidence):
    schema_version: Literal["1.0"]
    captured_at_utc: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T.*Z$")
    commit: CommitHash
    acceptance_rows: list[AcceptanceRowEvidence]
    unit_integration: PytestSuiteEvidence
    coverage: CoverageEvidence
    browser: PytestSuiteEvidence
    accessibility: AccessibilityEvidence
    quality: QualityEvidence
    gold: GoldEvidence
    routing: RoutingEvidence
    service: ServiceEvidence
    asset: AssetEvidence
    clean_checkout: CleanCheckoutEvidence
    owner_boundary: OwnerBoundaryEvidence
    evidence_sha256: dict[EvidencePath, Sha256] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_release_contract(self) -> ReleaseEvidence:
        try:
            parsed = datetime.fromisoformat(self.captured_at_utc.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("captured_at_utc must be a valid UTC timestamp") from error
        if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("captured_at_utc must be UTC")

        identifiers = [row.id for row in self.acceptance_rows]
        if identifiers != list(EXPECTED_ACCEPTANCE_ROWS):
            raise ValueError("acceptance row set is not exact")
        return self


def _failure(code: str, *, expected: Any, actual: Any) -> dict[str, Any]:
    return {"code": code, "expected": expected, "actual": actual}


def _append_failure(
    failures: list[dict[str, Any]],
    condition: bool,
    code: str,
    *,
    expected: Any,
    actual: Any,
) -> None:
    if not condition:
        failures.append(_failure(code, expected=expected, actual=actual))


def _component_commits(evidence: ReleaseEvidence) -> dict[str, str]:
    return {
        "unit_integration": evidence.unit_integration.commit,
        "coverage": evidence.coverage.commit,
        "browser": evidence.browser.commit,
        "accessibility": evidence.accessibility.commit,
        "quality": evidence.quality.commit,
        "gold": evidence.gold.commit,
        "routing": evidence.routing.commit,
        "service": evidence.service.commit,
        "asset": evidence.asset.commit,
        "clean_checkout": evidence.clean_checkout.commit,
    }


def _git_capture(repository_root: Path, *arguments: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise ValueError("unable to resolve repository HEAD")
    try:
        completed = subprocess.run(  # noqa: S603 - fixed Git operation in selected repo
            [git, *arguments],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("unable to resolve repository HEAD") from error
    return completed.stdout.strip()


def _repository_head(repository_root: Path) -> str:
    head = _git_capture(repository_root, "rev-parse", "HEAD")
    if len(head) != 40 or any(character not in "0123456789abcdef" for character in head):
        raise ValueError("repository HEAD is not a full commit hash")
    return head


def _repository_tree_sha256(
    repository_root: Path, revision: str = "HEAD"
) -> str:
    tree_oid = _git_capture(repository_root, "rev-parse", f"{revision}^{{tree}}")
    if len(tree_oid) != 40 or any(
        character not in "0123456789abcdef" for character in tree_oid
    ):
        raise ValueError("repository tree is not a full object hash")
    return hashlib.sha256(tree_oid.encode("ascii")).hexdigest()


def _require_release_commit_compatible_with_head(
    repository_root: Path,
    release_commit: str,
    head: str,
) -> None:
    try:
        resolved = _git_capture(repository_root, "rev-parse", f"{release_commit}^{{commit}}")
    except ValueError:
        raise ValueError("release commit does not match HEAD") from None
    if resolved != release_commit:
        raise ValueError("release commit does not match HEAD")
    if release_commit == head:
        return
    git = shutil.which("git")
    if git is None:
        raise ValueError("release commit does not match HEAD")
    ancestor = subprocess.run(  # noqa: S603 - resolved Git and closed revisions
        [git, "merge-base", "--is-ancestor", release_commit, head],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        raise ValueError("release commit does not match HEAD")
    changed = subprocess.run(  # noqa: S603 - resolved Git and closed revisions
        [
            git,
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            release_commit,
            head,
            "--",
        ],
        cwd=repository_root,
        check=True,
        capture_output=True,
    ).stdout
    changed_paths = {
        item.decode("utf-8") for item in changed.split(b"\0") if item
    }
    notebook = "docs/build-spec/g7-continuation/BUILD-NOTEBOOK.md"
    if any(
        not path.startswith("out/evidence/") and path != notebook
        for path in changed_paths
    ):
        raise ValueError("release commit does not match HEAD")


def _git_untracked_paths(
    repository_root: Path,
    *,
    include_ignored: bool = False,
    pathspecs: tuple[str, ...] = (".",),
) -> set[str]:
    git = shutil.which("git")
    if git is None:
        raise ValueError("unable to inspect repository worktree")
    arguments = [git, "ls-files", "--others", "-z"]
    if include_ignored:
        arguments.extend(("--ignored", "--exclude-standard"))
    else:
        arguments.append("--exclude-standard")
    arguments.extend(("--", *pathspecs))
    try:
        completed = subprocess.run(  # noqa: S603 - fixed Git inspection
            arguments,
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("unable to inspect repository worktree") from error
    try:
        return {
            item.decode("utf-8") for item in completed.stdout.split(b"\0") if item
        }
    except UnicodeDecodeError as error:
        raise ValueError("unable to inspect repository worktree") from error


def _require_tracked_source_clean(
    repository_root: Path, *, allowed_untracked_evidence: set[str]
) -> None:
    git = shutil.which("git")
    if git is None:
        raise ValueError("unable to inspect repository worktree")
    try:
        completed = subprocess.run(  # noqa: S603 - fixed Git operation in selected repo
            [
                git,
                "diff",
                "--quiet",
                "--no-ext-diff",
                "HEAD",
                "--",
                ".",
                ":(exclude)out/evidence/**",
            ],
            cwd=repository_root,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise ValueError("unable to inspect repository worktree") from error
    if completed.returncode == 1:
        raise ValueError("tracked source differs from HEAD")
    if completed.returncode != 0:
        raise ValueError("unable to inspect repository worktree")

    untracked = _git_untracked_paths(repository_root)
    undeclared = sorted(untracked - allowed_untracked_evidence)
    if undeclared:
        raise ValueError(f"untracked source or undeclared evidence exists: {undeclared}")

    ignored_candidates = _git_untracked_paths(
        repository_root,
        include_ignored=True,
        pathspecs=(
            "server",
            "sim_shell",
            "web",
            "scripts",
            "tests",
            "deploy",
            ".env",
        ),
    )
    ignored_cache_parts = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
    ignored_source = sorted(
        path
        for path in ignored_candidates
        if not ignored_cache_parts.intersection(PurePosixPath(path).parts)
        and PurePosixPath(path).suffix not in {".pyc", ".pyo"}
    )
    if ignored_source:
        raise ValueError(f"untracked source or runtime config exists: {ignored_source}")


def _safe_evidence_file(repository_root: Path, relative: str) -> Path:
    root = repository_root.resolve()
    candidate = root
    for component in PurePosixPath(relative).parts:
        candidate /= component
        if candidate.is_symlink():
            raise ValueError(f"evidence path uses a symlink: {relative}")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError(f"evidence file is missing: {relative}") from error
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"evidence path escapes repository: {relative}")
    if not resolved.is_file():
        raise ValueError(f"evidence path is not a regular file: {relative}")
    return resolved


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob_sha256(
    repository_root: Path,
    commit: str,
    relative: str,
) -> str:
    _repository_relative_path(relative)
    git = shutil.which("git")
    if git is None:
        raise ValueError("unable to read committed evidence")
    process = subprocess.run(  # noqa: S603 - resolved Git and closed commit/path
        [git, "show", f"{commit}:{relative}"],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if process.returncode != 0:
        raise ValueError("committed evidence is missing")
    return hashlib.sha256(process.stdout).hexdigest()


def _direct_evidence_paths(evidence: ReleaseEvidence) -> set[str]:
    paths = {path for row in evidence.acceptance_rows for path in row.evidence_paths}
    paths.update(
        {
            evidence.unit_integration.junit_path,
            evidence.coverage.json_path,
            evidence.browser.junit_path,
            evidence.accessibility.evidence_path,
            evidence.gold.evidence_path,
            evidence.routing.evidence_path,
            evidence.service.health_evidence_path,
            evidence.service.gallery_evidence_path,
            evidence.asset.evidence_path,
            evidence.clean_checkout.evidence_path,
            *evidence.quality.evidence_paths,
        }
    )
    return paths


def _is_untracked_evidence_path(relative: str) -> bool:
    """Only generated evidence may be untracked while a release is assembled."""

    return PurePosixPath(relative).parts[:2] == ("out", "evidence")


def _verify_evidence_files(evidence: ReleaseEvidence, repository_root: Path) -> None:
    referenced = _direct_evidence_paths(evidence)
    digests = set(evidence.evidence_sha256)
    missing_digests = sorted(referenced - digests)
    if missing_digests:
        raise ValueError(f"evidence sha256 is missing for: {missing_digests}")
    for relative, expected in evidence.evidence_sha256.items():
        path = _safe_evidence_file(repository_root, relative)
        actual = _sha256_file(path)
        if actual != expected:
            raise ValueError(f"evidence sha256 mismatch: {relative}")


def _read_json_evidence(repository_root: Path, relative: str) -> dict[str, Any]:
    path = _safe_evidence_file(repository_root, relative)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON evidence: {relative}") from error
    if not isinstance(document, dict):
        raise ValueError(f"JSON evidence must be an object: {relative}")
    return document


def _junit_counts(repository_root: Path, relative: str) -> dict[str, int]:
    path = _safe_evidence_file(repository_root, relative)
    try:
        root = ET.parse(path).getroot()  # noqa: S314 - local, digest-bound evidence
    except (ET.ParseError, OSError) as error:
        raise ValueError(f"invalid JUnit evidence: {relative}") from error
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError(f"JUnit evidence has no test suite: {relative}")

    def total(attribute: str) -> int:
        try:
            return sum(int(suite.attrib.get(attribute, "0")) for suite in suites)
        except ValueError as error:
            raise ValueError(f"JUnit count is invalid: {relative}") from error

    tests = total("tests")
    declared_failures = total("failures")
    declared_errors = total("errors")
    declared_skipped = total("skipped")
    testcases = [
        element
        for element in root.iter()
        if str(element.tag).rsplit("}", 1)[-1] == "testcase"
    ]
    if len(testcases) != tests:
        raise ValueError(f"JUnit testcase count does not match suite totals: {relative}")
    failures = 0
    errors = 0
    skipped = 0
    for testcase in testcases:
        outcomes = {
            str(child.tag).rsplit("}", 1)[-1]
            for child in testcase
            if str(child.tag).rsplit("}", 1)[-1]
            in {"failure", "error", "skipped"}
        }
        if len(outcomes) > 1:
            raise ValueError(f"JUnit testcase has contradictory outcomes: {relative}")
        failures += int("failure" in outcomes)
        errors += int("error" in outcomes)
        skipped += int("skipped" in outcomes)
    if (failures, errors, skipped) != (
        declared_failures,
        declared_errors,
        declared_skipped,
    ):
        raise ValueError(f"JUnit outcome counts do not match testcase records: {relative}")
    passed = tests - failures - errors - skipped
    if min(tests, failures, errors, skipped, passed) < 0:
        raise ValueError(f"JUnit counts are contradictory: {relative}")
    return {
        "tests_passed": passed,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }


def _junit_passed_nodeids(repository_root: Path, relative: str) -> set[str]:
    path = _safe_evidence_file(repository_root, relative)
    try:
        root = ET.parse(path).getroot()  # noqa: S314 - local, digest-bound evidence
    except (ET.ParseError, OSError) as error:
        raise ValueError(f"invalid JUnit evidence: {relative}") from error
    passed: set[str] = set()
    for testcase in root.iter():
        if str(testcase.tag).rsplit("}", 1)[-1] != "testcase":
            continue
        outcomes = {
            str(child.tag).rsplit("}", 1)[-1]
            for child in testcase
            if str(child.tag).rsplit("}", 1)[-1]
            in {"failure", "error", "skipped"}
        }
        if outcomes:
            continue
        name = testcase.attrib.get("name")
        classname = testcase.attrib.get("classname", "")
        file_attribute = testcase.attrib.get("file")
        if not name:
            continue
        relative_test: str | None = None
        class_suffix: list[str] = []
        if file_attribute:
            try:
                relative_test = _repository_relative_path(file_attribute)
            except ValueError:
                continue
        else:
            class_parts = classname.split(".") if classname else []
            for end in range(len(class_parts), 0, -1):
                candidate = "/".join(class_parts[:end]) + ".py"
                if (repository_root / candidate).is_file():
                    relative_test = candidate
                    class_suffix = class_parts[end:]
                    break
        if relative_test is None:
            continue
        suffix = "::".join([*class_suffix, name])
        passed.add(f"{relative_test}::{suffix}")
    return passed


def _nodeid_is_passed(required: str, passed: set[str]) -> bool:
    return any(
        actual == required or actual.startswith(f"{required}[") for actual in passed
    )


def _pytest_evidence_matches(
    suite: PytestSuiteEvidence, repository_root: Path
) -> bool:
    counts = _junit_counts(repository_root, suite.junit_path)
    return all(
        counts[name] == getattr(suite, name)
        for name in ("tests_passed", "failures", "errors", "skipped")
    )


def _mapping_matches(document: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(document.get(name) == value for name, value in expected.items())


def _coverage_evidence_matches(
    coverage: CoverageEvidence, repository_root: Path
) -> bool:
    document = _read_json_evidence(repository_root, coverage.json_path)
    expected = coverage.model_dump(mode="json")
    return (
        document.get("schema_version") == "1.0"
        and document.get("gate") == "coverage"
        and _mapping_matches(document, expected)
    )


def _accessibility_evidence_matches(
    accessibility: AccessibilityEvidence, repository_root: Path
) -> bool:
    document = _read_json_evidence(repository_root, accessibility.evidence_path)
    expected = accessibility.model_dump(mode="json")
    return (
        document.get("schema_version") == "1.0"
        and document.get("gate") == "accessibility"
        and _mapping_matches(document, expected)
    )


def _quality_evidence_matches(quality: QualityEvidence, repository_root: Path) -> bool:
    report = _read_json_evidence(repository_root, quality.evidence_paths[0])
    provenance = _read_json_evidence(repository_root, quality.evidence_paths[1])
    report_expected = {
        "commit": quality.commit,
        "ruff_passed": quality.ruff_passed,
        "diff_check_passed": quality.diff_check_passed,
        "no_example_specific_runtime_passed": quality.no_example_specific_runtime_passed,
        "no_example_specific_runtime_violations": quality.no_example_specific_runtime_violations,
    }
    provenance_expected = {
        "commit": quality.commit,
        "passed": quality.session_provenance_passed,
        "root_commit_count": quality.session_roots,
        "merge_commit_count": quality.merge_commits,
        "unlinked_commit_count": quality.unlinked_commits,
    }
    return bool(
        report.get("schema_version") == "1.0"
        and report.get("gate") == "quality"
        and _mapping_matches(report, report_expected)
        and provenance.get("schema_version") == "1.0"
        and _mapping_matches(provenance, provenance_expected)
    )


def _acceptance_evidence_mismatches(
    evidence: ReleaseEvidence, repository_root: Path
) -> list[str]:
    junit_paths = {
        evidence.unit_integration.junit_path,
        evidence.browser.junit_path,
    }
    passed_nodeids = {
        relative: _junit_passed_nodeids(repository_root, relative)
        for relative in junit_paths
    }
    mismatches: list[str] = []
    for row in evidence.acceptance_rows:
        if row.id == "RELEASE-01" or row.status != "passing":
            continue
        canonical_nodeids = ACCEPTANCE_ROW_TEST_NODEIDS[row.id]
        if len(row.evidence_paths) != 1:
            mismatches.append(row.id)
            continue
        relative = row.evidence_paths[0]
        if not relative.endswith(".json"):
            mismatches.append(row.id)
            continue
        try:
            document = _read_json_evidence(repository_root, relative)
        except ValueError:
            mismatches.append(row.id)
            continue
        source_hashes = document.get("source_evidence_sha256")
        test_nodeids = document.get("test_nodeids")
        if (
            set(document)
            != {
                "schema_version",
                "gate",
                "passed",
                "commit",
                "test_nodeids",
                "source_evidence_sha256",
            }
            or not isinstance(test_nodeids, list)
            or test_nodeids != list(canonical_nodeids)
            or not isinstance(source_hashes, dict)
            or not source_hashes
            or any(
                not isinstance(source, str) or not isinstance(digest, str)
                for source, digest in source_hashes.items()
            )
        ):
            mismatches.append(row.id)
            continue
        forbidden_sources = {
            relative,
            RELEASE_REPORT_PATH,
        }
        if any(
            source in forbidden_sources
            or source.startswith("out/evidence/acceptance/")
            or source.endswith("release-input.json")
            for source in source_hashes
        ):
            mismatches.append(row.id)
            continue
        if any(
            evidence.evidence_sha256.get(source) != digest
            for source, digest in source_hashes.items()
        ):
            mismatches.append(row.id)
            continue
        selected_junit_paths = junit_paths.intersection(source_hashes)
        selected_passed = set().union(
            *(passed_nodeids[path] for path in selected_junit_paths)
        )
        if not (
            document.get("schema_version") == "1.0"
            and document.get("gate") == row.id
            and document.get("passed") is True
            and document.get("commit") == evidence.commit
            and selected_junit_paths
            and all(
                _nodeid_is_passed(nodeid, selected_passed)
                for nodeid in canonical_nodeids
            )
        ):
            mismatches.append(row.id)
    return mismatches


def _png_dimensions(payload: bytes) -> tuple[int, int] | None:
    signature = b"\x89PNG\r\n\x1a\n"
    if not payload.startswith(signature) or len(payload) > 50 * 1024 * 1024:
        return None
    offset = len(signature)
    width = height = bit_depth = color_type = 0
    saw_header = False
    saw_palette = False
    saw_data = False
    saw_end = False
    compressed = bytearray()
    while offset < len(payload):
        if len(payload) - offset < 12:
            return None
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        kind = payload[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(payload) or not all(
            (65 <= byte <= 90) or (97 <= byte <= 122) for byte in kind
        ):
            return None
        data = payload[offset + 8 : offset + 8 + length]
        recorded_crc = struct.unpack(">I", payload[offset + 8 + length : chunk_end])[0]
        if (zlib.crc32(kind + data) & 0xFFFFFFFF) != recorded_crc:
            return None
        if not saw_header and kind != b"IHDR":
            return None
        if kind == b"IHDR":
            if saw_header or length != 13:
                return None
            width, height, bit_depth, color_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", data)
            )
            allowed_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if (
                width < 1
                or height < 1
                or width > 16384
                or height > 16384
                or width * height > 50_000_000
                or bit_depth not in allowed_depths.get(color_type, set())
                or compression != 0
                or filtering != 0
                or interlace != 0
            ):
                return None
            saw_header = True
        elif kind == b"PLTE":
            palette_entries = length // 3
            if (
                saw_palette
                or saw_data
                or color_type not in {2, 3, 6}
                or length == 0
                or length % 3
                or length > 768
                or (color_type == 3 and palette_entries > 2**bit_depth)
            ):
                return None
            saw_palette = True
        elif kind == b"IDAT":
            if not saw_header or saw_end or length == 0:
                return None
            saw_data = True
            compressed.extend(data)
        elif kind == b"IEND":
            if length != 0 or not saw_data or saw_end:
                return None
            saw_end = True
            offset = chunk_end
            break
        elif 65 <= kind[0] <= 90:
            return None
        offset = chunk_end
    if not saw_header or not saw_data or not saw_end or offset != len(payload):
        return None
    if color_type == 3 and not saw_palette:
        return None
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = (width * channels * bit_depth + 7) // 8
    expected_size = height * (row_bytes + 1)
    if expected_size > 200 * 1024 * 1024:
        return None
    try:
        inflater = zlib.decompressobj()
        raw = inflater.decompress(bytes(compressed), expected_size + 1)
        raw += inflater.flush()
    except zlib.error:
        return None
    if (
        len(raw) != expected_size
        or not inflater.eof
        or inflater.unused_data
        or inflater.unconsumed_tail
        or any(raw[row * (row_bytes + 1)] > 4 for row in range(height))
    ):
        return None
    return width, height


def _gold_evidence_matches(
    gold: GoldEvidence,
    repository_root: Path,
    evidence_sha256: dict[str, str],
) -> bool:
    from server.goldens import GOLDEN_FIXTURE_IDS

    report = _read_json_evidence(repository_root, gold.evidence_path)
    goldens = report.get("goldens")
    manifest_report = report.get("manifest")
    if not isinstance(goldens, list) or not isinstance(manifest_report, dict):
        return False
    expected_identifiers = {
        fixture_id.removesuffix("_ar") for fixture_id in GOLDEN_FIXTURE_IDS
    }
    identifiers = [
        item.get("golden_id") for item in goldens if isinstance(item, dict)
    ]
    if (
        len(identifiers) != 6
        or len(set(identifiers)) != 6
        or set(identifiers) != expected_identifiers
        or any(
            not isinstance(identifier, str)
            or not identifier
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in identifier
            )
            for identifier in identifiers
        )
    ):
        return False

    manifest_relative = manifest_report.get("path")
    if not isinstance(manifest_relative, str) or manifest_relative not in evidence_sha256:
        return False
    try:
        manifest_path = _safe_evidence_file(repository_root, manifest_relative)
        manifest = _read_json_evidence(repository_root, manifest_relative)
    except ValueError:
        return False
    manifest_lessons = manifest.get("lessons")
    if (
        set(manifest) != {"schema_version", "contract_version", "lessons"}
        or manifest.get("schema_version") != "1.0"
        or manifest.get("contract_version") != "1.0"
        or not isinstance(manifest_lessons, list)
        or len(manifest_lessons) != 6
    ):
        return False
    manifest_by_id = {
        item.get("id"): item for item in manifest_lessons if isinstance(item, dict)
    }
    if set(manifest_by_id) != set(identifiers) or len(manifest_by_id) != 6:
        return False
    for item in manifest_by_id.values():
        metadata = item.get("metadata")
        if (
            item.get("instant") is not True
            or item.get("tier") != "A"
            or not isinstance(item.get("artifact_sha256"), str)
            or len(item["artifact_sha256"]) != 64
            or not isinstance(metadata, dict)
            or set(metadata) != {"ar", "en"}
            or not all(
                isinstance(metadata[locale], dict)
                and all(metadata[locale].get(field) for field in ("title", "domain", "summary"))
                for locale in ("ar", "en")
            )
        ):
            return False

    locale_count = 0
    screenshot_paths: list[str] = []
    for item in goldens:
        if not isinstance(item, dict) or item.get("passed") is not True:
            return False
        if item.get("failures", []) != []:
            return False
        nested_gates = [
            item.get("science"),
            item.get("actor_motion"),
            item.get("physics_motion"),
            item.get("shared_state"),
        ]
        if not all(
            isinstance(gate, dict)
            and gate.get("passed") is True
            and gate.get("failures", []) == []
            for gate in nested_gates
        ):
            return False
        locales = item.get("locales")
        screenshots = item.get("screenshots")
        if not isinstance(locales, dict) or set(locales) != {"ar", "en"}:
            return False
        if not all(
            isinstance(locales[locale], dict)
            and locales[locale].get("passed") is True
            and locales[locale].get("lang") == locale
            and locales[locale].get("dir") == ("rtl" if locale == "ar" else "ltr")
            for locale in ("ar", "en")
        ):
            return False
        if not isinstance(screenshots, list) or not all(
            isinstance(record, dict)
            and set(record) == {"path", "sha256", "expected_sha256", "passed"}
            and isinstance(record.get("path"), str)
            and isinstance(record.get("sha256"), str)
            and isinstance(record.get("expected_sha256"), str)
            and record.get("passed") is True
            for record in screenshots
        ):
            return False
        if len(screenshots) != 4 or len({record["path"] for record in screenshots}) != 4:
            return False
        paths_for_golden: list[str] = []
        for record in screenshots:
            relative = record["path"]
            if relative not in evidence_sha256:
                return False
            try:
                screenshot = _safe_evidence_file(repository_root, relative)
            except ValueError:
                return False
            digest = _sha256_file(screenshot)
            if (
                record["sha256"] != digest
                or record["expected_sha256"] != digest
                or evidence_sha256[relative] != digest
                or _png_dimensions(screenshot.read_bytes()) is None
            ):
                return False
            paths_for_golden.append(relative)
        localized_paths: list[str] = []
        identifier = item["golden_id"]
        for locale in ("ar", "en"):
            localized = locales[locale].get("screenshots")
            if (
                not isinstance(localized, list)
                or len(localized) != 2
                or not all(
                    isinstance(record, dict) and isinstance(record.get("path"), str)
                    for record in localized
                )
            ):
                return False
            paths = [record["path"] for record in localized]
            if len(set(paths)) != 2:
                return False
            viewports: set[str] = set()
            for relative in paths:
                name = PurePosixPath(relative).name
                if not name.startswith(f"{identifier}-{locale}-"):
                    return False
                if f"-{locale}-mobile" in name:
                    viewports.add("mobile")
                if f"-{locale}-desktop" in name:
                    viewports.add("desktop")
            if viewports != {"mobile", "desktop"}:
                return False
            localized_paths.extend(paths)
        if len(set(localized_paths)) != 4 or sorted(localized_paths) != sorted(paths_for_golden):
            return False

        manifest_item = manifest_by_id[identifier]
        pinned_relative = f"out/cache/golden/{identifier}.json"
        if pinned_relative not in evidence_sha256:
            return False
        try:
            pinned_path = _safe_evidence_file(repository_root, pinned_relative)
            pinned = _read_json_evidence(repository_root, pinned_relative)
        except ValueError:
            return False
        artifact = pinned.get("artifact")
        if not isinstance(artifact, str):
            return False
        artifact_sha256 = hashlib.sha256(artifact.encode("utf-8")).hexdigest()
        if (
            item.get("pinned") is not True
            or item.get("tier") != "A"
            or item.get("manifest_hash_matches") is not True
            or item.get("artifact_sha256") != artifact_sha256
            or manifest_item.get("artifact_sha256") != artifact_sha256
            or item.get("document_sha256") != _sha256_file(pinned_path)
        ):
            return False
        locale_count += 2
        screenshot_paths.extend(paths_for_golden)
    return bool(
        report.get("schema_version") == "1.0"
        and report.get("gate") == "GOLD-01"
        and report.get("passed") is True
        and report.get("golden_count") == gold.golden_count == len(goldens) == 6
        and report.get("locale_journey_count")
        == gold.locale_journey_count
        == locale_count
        == 12
        and report.get("model_calls") == gold.model_calls == 0
        and isinstance(report.get("check_count"), int)
        and report["check_count"] > 0
        and report.get("screenshot_count") == gold.screenshot_count
        and len(screenshot_paths) == gold.screenshot_count
        and len(set(screenshot_paths)) == gold.screenshot_count
        and manifest_report.get("passed") is True
        and manifest_report.get("golden_count") == 6
        and manifest_report.get("schema_version") == "1.0"
        and manifest_report.get("contract_version") == "1.0"
        and manifest_report.get("sha256") == _sha256_file(manifest_path)
    )


def _routing_evidence_matches(
    routing: RoutingEvidence, repository_root: Path
) -> bool:
    from scripts.evaluate_generation_routing import validate_routing_report

    document = _read_json_evidence(repository_root, routing.evidence_path)
    raw_relative = document.get("raw_evidence_path")
    prior_aborted = document.get("prior_aborted_evidence")
    if not isinstance(raw_relative, str) or not isinstance(prior_aborted, list):
        return False
    try:
        # The measured source commit is intentionally immutable, while raw and
        # final routing evidence are committed afterwards as an evidence-only
        # descendant.  Their bytes therefore bind to the checked HEAD, not to
        # the earlier source commit that the routing report itself attests.
        evidence_commit = _repository_head(repository_root)
        committed_paths = [routing.evidence_path, raw_relative]
        committed_paths.extend(
            record["path"]
            for record in prior_aborted
            if isinstance(record, dict) and isinstance(record.get("path"), str)
        )
        if len(committed_paths) != 4:
            return False
        for relative in committed_paths:
            if _git_blob_sha256(repository_root, evidence_commit, relative) != _sha256_file(
                _safe_evidence_file(repository_root, relative)
            ):
                return False
        report = validate_routing_report(
            document,
            repository_root=repository_root,
            routing_decision_path=repository_root / "server" / "routing_decision.json",
            current_commit=routing.commit,
            require_current_provenance=True,
        )
    except ValueError:
        return False
    decision = report["tier_decision"]
    return bool(
        report["passed"] is True
        and report["cohort_status"] == "complete"
        and report["cohort_live_calls"] == routing.cohort_live_calls
        and report["prior_aborted_live_calls"] == routing.prior_aborted_live_calls
        and report["total_live_calls"] == routing.total_live_calls
        and report["account_observed_usage"]["observed"] is True
        and decision["decision_applied"] is True
        and decision["generation_model"] == routing.generation_model
    )


def _service_evidence_matches(
    service: ServiceEvidence, repository_root: Path
) -> bool:
    from scripts.capture_release_service import (
        validate_gallery_receipt,
        validate_health_receipt,
    )

    try:
        health = validate_health_receipt(
            _read_json_evidence(repository_root, service.health_evidence_path)
        )
        gallery = validate_gallery_receipt(
            _read_json_evidence(repository_root, service.gallery_evidence_path)
        )
        health_url = urlsplit(health.http.url)
        gallery_url = urlsplit(gallery.http.url)
        health_body = json.loads(health.http.body)
        gallery_body = json.loads(gallery.http.body)
        service_properties = {
            line.partition("=")[0]: line.partition("=")[2]
            for line in health.commands.service_show.stdout.splitlines()
        }
    except (ValidationError, ValueError, json.JSONDecodeError):
        return False
    lessons = gallery_body.get("lessons")
    root = str(repository_root.resolve())
    expected_exec = str(repository_root.resolve() / "scripts" / "serve.sh")
    return bool(
        service.passed is True
        and service.active is True
        and service.healthz_green is True
        and service.instant_gallery_passed is True
        and service.commit == service.restarted_commit == health.commit == gallery.commit
        and health_url.port == gallery_url.port
        and isinstance(health_body, dict)
        and health_body.get("status") == "ok"
        and health_body.get("backend") == "codex"
        and isinstance(lessons, list)
        and len(lessons) == service.gallery_count == 6
        and service_properties.get("WorkingDirectory") == root
        and expected_exec in service_properties.get("ExecStart", "")
    )


def _asset_evidence_matches(
    asset: AssetEvidence,
    repository_root: Path,
    evidence_sha256: dict[str, str],
) -> bool:
    from server.static_assets import RUNTIME_ASSETS, load_asset_manifest

    report = _read_json_evidence(repository_root, asset.evidence_path)
    manifest_relative = "web/asset-manifest.json"
    try:
        manifest = load_asset_manifest(
            path=_safe_evidence_file(repository_root, manifest_relative),
            root=repository_root / "web",
        )
    except (RuntimeError, ValueError):
        return False
    browser = report.get("browser")
    if not isinstance(browser, dict):
        return False
    authenticated_assets = {
        f"web/{relative}": manifest["assets"][relative]["sha256"]
        for relative in RUNTIME_ASSETS
    }
    expected = asset.model_dump(mode="json")
    return bool(
        report.get("schema_version") == "1.0"
        and report.get("gate") == "ASSET-01"
        and _mapping_matches(report, expected)
        and manifest.get("schema_version") == "1.0"
        and manifest.get("bundle_version") == asset.bundle_sha256
        and evidence_sha256.get(manifest_relative)
        == _sha256_file(repository_root / manifest_relative)
        and all(
            evidence_sha256.get(relative) == digest
            for relative, digest in authenticated_assets.items()
        )
        and browser.get("passed") is True
        and isinstance(browser.get("response_count"), int)
        and browser["response_count"] >= len(RUNTIME_ASSETS)
        and browser.get("console_errors") == []
    )


def _clean_checkout_evidence_matches(
    clean: CleanCheckoutEvidence,
    repository_root: Path,
    evidence_sha256: dict[str, str],
) -> bool:
    from scripts.verify_clean_checkout import (
        CleanCheckoutError,
        validate_clean_checkout_receipt,
    )

    report = _read_json_evidence(repository_root, clean.evidence_path)
    try:
        receipt = validate_clean_checkout_receipt(
            report,
            repository_root=repository_root,
            expected_commit=clean.commit,
        )
        archive_relative = receipt["archive"]["path"]
        junit_relative = receipt["junit_path"]
        archive_path = _safe_evidence_file(repository_root, archive_relative)
        junit_path = _safe_evidence_file(repository_root, junit_relative)
    except (CleanCheckoutError, ValueError):
        return False
    expected = clean.model_dump(mode="json")
    return bool(
        _mapping_matches(receipt, expected)
        and archive_relative in evidence_sha256
        and junit_relative in evidence_sha256
        and evidence_sha256[archive_relative] == _sha256_file(archive_path)
        and evidence_sha256[junit_relative] == _sha256_file(junit_path)
    )


def _all_evidence_paths(evidence: ReleaseEvidence) -> list[str]:
    paths = {*evidence.evidence_sha256, RELEASE_REPORT_PATH}
    return sorted(paths)


def build_release_report(
    document: dict[str, Any], *, repository_root: Path | None = None
) -> dict[str, Any]:
    evidence = ReleaseEvidence.model_validate(document)
    root = (repository_root or ROOT).resolve()
    head = _repository_head(root)
    _require_release_commit_compatible_with_head(root, evidence.commit, head)
    _require_tracked_source_clean(
        root,
        allowed_untracked_evidence={
            *(
                relative
                for relative in evidence.evidence_sha256
                if _is_untracked_evidence_path(relative)
            ),
            RELEASE_REPORT_PATH,
        },
    )
    _verify_evidence_files(evidence, root)
    failures: list[dict[str, Any]] = []

    acceptance_evidence_mismatches = _acceptance_evidence_mismatches(evidence, root)
    _append_failure(
        failures,
        not acceptance_evidence_mismatches,
        "acceptance_evidence_mismatch",
        expected=[],
        actual=acceptance_evidence_mismatches,
    )

    prerequisite_statuses = {
        row.id: row.status for row in evidence.acceptance_rows if row.id != "RELEASE-01"
    }
    unclosed = {
        identifier: status
        for identifier, status in prerequisite_statuses.items()
        if status != "passing"
    }
    _append_failure(
        failures,
        not unclosed,
        "acceptance_rows_not_all_passing",
        expected={"passing": 29},
        actual=unclosed,
    )

    unit = evidence.unit_integration
    unit_evidence_matches = _pytest_evidence_matches(unit, root)
    _append_failure(
        failures,
        unit.passed
        and unit.tests_passed > 0
        and unit.failures == 0
        and unit.errors == 0
        and unit_evidence_matches,
        "unit_integration_failed",
        expected={
            "passed": True,
            "tests_passed": ">0",
            "failures": 0,
            "errors": 0,
            "evidence_matches": True,
        },
        actual={
            "passed": unit.passed,
            "tests_passed": unit.tests_passed,
            "failures": unit.failures,
            "errors": unit.errors,
            "evidence_matches": unit_evidence_matches,
        },
    )

    coverage = evidence.coverage
    coverage_evidence_matches = _coverage_evidence_matches(coverage, root)
    _append_failure(
        failures,
        coverage.passed
        and coverage.tests_passed > 0
        and coverage.percent >= 80.0
        and coverage_evidence_matches,
        "coverage_below_80",
        expected={
            "passed": True,
            "tests_passed": ">0",
            "percent": ">=80.0",
            "evidence_matches": True,
        },
        actual={
            "passed": coverage.passed,
            "tests_passed": coverage.tests_passed,
            "percent": coverage.percent,
            "evidence_matches": coverage_evidence_matches,
        },
    )

    browser = evidence.browser
    browser_evidence_matches = _pytest_evidence_matches(browser, root)
    _append_failure(
        failures,
        browser.passed
        and browser.tests_passed > 0
        and browser.failures == 0
        and browser.errors == 0
        and browser_evidence_matches,
        "browser_failed",
        expected={
            "passed": True,
            "tests_passed": ">0",
            "failures": 0,
            "errors": 0,
            "evidence_matches": True,
        },
        actual={
            "passed": browser.passed,
            "tests_passed": browser.tests_passed,
            "failures": browser.failures,
            "errors": browser.errors,
            "evidence_matches": browser_evidence_matches,
        },
    )

    a11y = evidence.accessibility
    accessibility_evidence_matches = _accessibility_evidence_matches(a11y, root)
    _append_failure(
        failures,
        a11y.passed
        and a11y.tests_passed > 0
        and a11y.failures == 0
        and a11y.skipped == 0
        and a11y.violations == 0
        and accessibility_evidence_matches,
        "accessibility_failed",
        expected={
            "passed": True,
            "tests_passed": ">0",
            "failures": 0,
            "skipped": 0,
            "violations": 0,
            "evidence_matches": True,
        },
        actual={
            "passed": a11y.passed,
            "tests_passed": a11y.tests_passed,
            "failures": a11y.failures,
            "skipped": a11y.skipped,
            "violations": a11y.violations,
            "evidence_matches": accessibility_evidence_matches,
        },
    )

    quality = evidence.quality
    quality_evidence_matches = _quality_evidence_matches(quality, root)
    _append_failure(
        failures,
        quality_evidence_matches,
        "quality_evidence_mismatch",
        expected=True,
        actual=quality_evidence_matches,
    )
    _append_failure(
        failures,
        quality.ruff_passed,
        "ruff_failed",
        expected=True,
        actual=quality.ruff_passed,
    )
    _append_failure(
        failures,
        quality.diff_check_passed,
        "diff_check_failed",
        expected=True,
        actual=quality.diff_check_passed,
    )
    _append_failure(
        failures,
        quality.no_example_specific_runtime_passed
        and quality.no_example_specific_runtime_violations == 0,
        "example_specific_runtime_detected",
        expected={"passed": True, "violations": 0},
        actual={
            "passed": quality.no_example_specific_runtime_passed,
            "violations": quality.no_example_specific_runtime_violations,
        },
    )
    _append_failure(
        failures,
        quality.session_provenance_passed
        and quality.session_roots == 1
        and quality.merge_commits == 0
        and quality.unlinked_commits == 0,
        "session_provenance_failed",
        expected={"passed": True, "roots": 1, "merges": 0, "unlinked": 0},
        actual={
            "passed": quality.session_provenance_passed,
            "roots": quality.session_roots,
            "merges": quality.merge_commits,
            "unlinked": quality.unlinked_commits,
        },
    )

    gold = evidence.gold
    gold_evidence_matches = _gold_evidence_matches(
        gold, root, evidence.evidence_sha256
    )
    _append_failure(
        failures,
        gold.passed
        and gold.golden_count == 6
        and gold.locale_journey_count == 12
        and gold.screenshot_count >= 24
        and gold.model_calls == 0
        and gold_evidence_matches,
        "gold_release_incomplete",
        expected={
            "passed": True,
            "golden_count": 6,
            "locale_journey_count": 12,
            "screenshot_count": ">=24",
            "model_calls": 0,
            "evidence_matches": True,
        },
        actual={
            **gold.model_dump(exclude={"evidence_path", "commit"}),
            "evidence_matches": gold_evidence_matches,
        },
    )

    routing = evidence.routing
    routing_evidence_matches = _routing_evidence_matches(routing, root)
    _append_failure(
        failures,
        routing.passed
        and routing.route_01_passed
        and routing.route_02_passed
        and routing_evidence_matches,
        "routing_evidence_failed",
        expected={
            "passed": True,
            "route_01_passed": True,
            "route_02_passed": True,
            "evidence_matches": True,
        },
        actual={
            "passed": routing.passed,
            "route_01_passed": routing.route_01_passed,
            "route_02_passed": routing.route_02_passed,
            "evidence_matches": routing_evidence_matches,
        },
    )
    _append_failure(
        failures,
        routing.decision_applied,
        "routing_not_applied",
        expected=True,
        actual=routing.decision_applied,
    )

    service = evidence.service
    service_evidence_matches = _service_evidence_matches(service, root)
    _append_failure(
        failures,
        service.passed
        and service.active
        and service.restarted_commit == evidence.commit
        and service.healthz_green
        and service.gallery_count == 6
        and service.instant_gallery_passed
        and service_evidence_matches,
        "service_not_green",
        expected={
            "passed": True,
            "active": True,
            "restarted_commit": evidence.commit,
            "healthz_green": True,
            "gallery_count": 6,
            "instant_gallery_passed": True,
            "evidence_matches": True,
        },
        actual={
            "passed": service.passed,
            "active": service.active,
            "restarted_commit": service.restarted_commit,
            "healthz_green": service.healthz_green,
            "gallery_count": service.gallery_count,
            "instant_gallery_passed": service.instant_gallery_passed,
            "evidence_matches": service_evidence_matches,
        },
    )

    asset = evidence.asset
    asset_evidence_matches = _asset_evidence_matches(
        asset, root, evidence.evidence_sha256
    )
    _append_failure(
        failures,
        asset.passed
        and asset.manifest_compatible
        and asset.clean_browser_smoke_passed
        and asset_evidence_matches,
        "asset_contract_failed",
        expected={
            "passed": True,
            "manifest_compatible": True,
            "clean_browser_smoke_passed": True,
            "evidence_matches": True,
        },
        actual={
            "passed": asset.passed,
            "manifest_compatible": asset.manifest_compatible,
            "clean_browser_smoke_passed": asset.clean_browser_smoke_passed,
            "evidence_matches": asset_evidence_matches,
        },
    )

    clean = evidence.clean_checkout
    clean_evidence_matches = _clean_checkout_evidence_matches(
        clean, root, evidence.evidence_sha256
    )
    _append_failure(
        failures,
        clean.passed
        and clean.tracked_status_clean
        and clean.tests_passed > 0
        and clean.failures == 0
        and clean.ruff_passed
        and clean_evidence_matches,
        "clean_checkout_failed",
        expected={
            "passed": True,
            "tracked_status_clean": True,
            "tests_passed": ">0",
            "failures": 0,
            "ruff_passed": True,
            "evidence_matches": True,
        },
        actual={
            **clean.model_dump(exclude={"evidence_path", "commit"}),
            "evidence_matches": clean_evidence_matches,
        },
    )

    component_commits = _component_commits(evidence)
    commit_drift = {
        component: commit
        for component, commit in component_commits.items()
        if commit != evidence.commit
    }
    _append_failure(
        failures,
        not commit_drift,
        "evidence_commit_mismatch",
        expected=evidence.commit,
        actual=commit_drift,
    )

    release_status: Status = "passing" if not failures else "failing"
    rows: list[dict[str, Any]] = []
    by_id = {row.id: row for row in evidence.acceptance_rows}
    for identifier in EXPECTED_ACCEPTANCE_ROWS:
        row = by_id[identifier]
        if identifier == "RELEASE-01":
            rows.append(
                {
                    "id": identifier,
                    "status": release_status,
                    "evidence_paths": [RELEASE_REPORT_PATH],
                }
            )
        else:
            rows.append(row.model_dump(mode="json"))
    counts = Counter(row["status"] for row in rows)
    totals = {
        "total": len(rows),
        "passing": counts["passing"],
        "failing": counts["failing"],
        "not-started": counts["not-started"],
        "blocked": counts["blocked"],
    }
    passed = not failures and totals == {
        "total": 30,
        "passing": 30,
        "failing": 0,
        "not-started": 0,
        "blocked": 0,
    }

    return {
        "schema_version": "1.0",
        "gate": "RELEASE-01",
        "captured_at_utc": evidence.captured_at_utc,
        "commit": evidence.commit,
        "passed": passed,
        "acceptance": {"rows": rows, "totals": totals},
        "suites": {
            "unit_integration": unit.model_dump(mode="json"),
            "coverage": coverage.model_dump(mode="json"),
            "browser": browser.model_dump(mode="json"),
            "accessibility": a11y.model_dump(mode="json"),
        },
        "quality": quality.model_dump(mode="json"),
        "gold": gold.model_dump(mode="json"),
        "routing": routing.model_dump(mode="json"),
        "service": service.model_dump(mode="json"),
        "asset": asset.model_dump(mode="json"),
        "clean_checkout": clean.model_dump(mode="json"),
        "owner_boundary": evidence.owner_boundary.model_dump(mode="json"),
        "evidence_sha256": dict(sorted(evidence.evidence_sha256.items())),
        "evidence_paths": _all_evidence_paths(evidence),
        "failures": failures,
    }


def _read_object(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("release evidence input must be a JSON object")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the fail-closed RELEASE-01 report")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / RELEASE_REPORT_PATH)
    args = parser.parse_args()
    try:
        report = build_release_report(_read_object(args.input))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
