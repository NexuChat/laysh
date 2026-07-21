from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path


def test_motion_evidence_summary_is_bounded_but_keeps_contract_and_hashes():
    from scripts.verify_golden_physics_motion import _bounded_evidence_summary

    raw = {
        "ready": True,
        "runtimeError": False,
        "externalRequests": 0,
        "consoleErrors": [],
        "actorSamples": [{"pixels": list(range(2_000))}] * 4,
        "physicsSamples": [{"outputs": {"value": index}} for index in range(3)],
        "temporalRuns": [{"samples": [{"frame": index} for index in range(8)]}],
        "geometrySamples": [{"bodies": [{"pixels": list(range(2_000))}]}] * 20,
    }

    summary = _bounded_evidence_summary(
        raw,
        actor_profile={"sample_count": 4, "sample_interval_ms": 140},
        physics_profile={"kind": "synthetic", "tolerance": 0.02},
        geometry_profile={"viewport_widths": [320, 390]},
    )

    assert set(summary) == {
        "browser",
        "contracts",
        "sample_counts",
        "evidence_sha256",
    }
    assert summary["sample_counts"] == {
        "actor": 4,
        "physics": 3,
        "temporal_runs": 1,
        "temporal_samples": 8,
        "geometry": 20,
    }
    assert set(summary["evidence_sha256"]) == {
        "actor",
        "physics",
        "temporal",
        "geometry",
    }
    assert len(summary["evidence_sha256"]["geometry"]) == 64
    assert len(__import__("json").dumps(summary)) < 4_000
    serialized = __import__("json").dumps(summary)
    assert "actorSamples" not in serialized
    assert "geometrySamples" not in serialized


def _browser_evidence(screenshot_root: Path) -> dict[str, object]:
    from scripts.verify_golden_release import _current_shell_artifact
    from server.goldens import load_golden_fixtures, load_pinned_golden

    journeys: list[dict[str, object]] = []
    screenshot_directory = screenshot_root / "screens"
    screenshot_directory.mkdir(parents=True, exist_ok=True)
    for fixture_id, fixture in load_golden_fixtures().items():
        golden_id = fixture_id.removesuffix("_ar")
        document = load_pinned_golden(golden_id)
        assert document is not None
        for locale, direction in (("ar", "rtl"), ("en", "ltr")):
            artifact = _current_shell_artifact(document, fixture, locale)
            screenshot_paths = []
            screenshot_hashes = {}
            for viewport in ("mobile-390x844", "desktop-1440x900"):
                screenshot_path = screenshot_directory / (
                    f"{golden_id}-{locale}-{viewport}.png"
                )
                screenshot_path.write_bytes(
                    f"{golden_id}:{locale}:{viewport}".encode()
                )
                relative_path = str(screenshot_path.relative_to(screenshot_root))
                screenshot_paths.append(relative_path)
                screenshot_hashes[relative_path] = hashlib.sha256(
                    screenshot_path.read_bytes()
                ).hexdigest()
            journeys.append(
                {
                    "golden_id": golden_id,
                    "locale": locale,
                    "lang": locale,
                    "dir": direction,
                    "artifact_sha256": hashlib.sha256(
                        artifact.encode("utf-8")
                    ).hexdigest(),
                    "passed": True,
                    "checks": {
                        "actor_visible": True,
                        "primary_control_reachable": True,
                        "pause_stops_motion": True,
                        "resume_restarts_motion": True,
                        "reset_restores_default": True,
                        "reduced_motion_stops_automatic_motion": True,
                        "state_alternative_present": True,
                        "keyboard_controls_named": True,
                        "no_duplicate_ids": True,
                        "no_horizontal_clip": True,
                    },
                    "responsive": [
                        {"name": "mobile-320x844", "passed": True},
                        {"name": "mobile-390x844", "passed": True},
                        {"name": "desktop-1440x900", "passed": True},
                        {"name": "zoom-200", "passed": True},
                    ],
                    "a11y": {
                        "unnamed_interactive_nodes": 0,
                        "duplicate_ids": [],
                        "state_alternative_present": True,
                    },
                    "console_errors": [],
                    "external_requests": 0,
                    "screenshots": screenshot_paths,
                    "screenshot_sha256": screenshot_hashes,
                }
            )
    return {
        "schema_version": "1.0",
        "gate": "golden_browser_review",
        "model_calls": 0,
        "passed": True,
        "journey_count": 12,
        "journeys": journeys,
    }


def _motion_evidence() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    import hashlib

    from server.goldens import load_golden_fixtures, load_pinned_golden

    actor: list[dict[str, object]] = []
    physics: list[dict[str, object]] = []
    shared: list[dict[str, object]] = []
    for fixture_id in load_golden_fixtures():
        golden_id = fixture_id.removesuffix("_ar")
        from server.goldens import _artifact_lesson_and_module

        document = load_pinned_golden(golden_id)
        assert document is not None
        artifact_hash = hashlib.sha256(document["artifact"].encode("utf-8")).hexdigest()
        _, source = _artifact_lesson_and_module(document["artifact"])
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        actor.append(
            {
                "golden_id": golden_id,
                "artifact_sha256": artifact_hash,
                "passed": True,
                "check_count": 7,
                "failures": [],
            }
        )
        physics.append(
            {
                "golden_id": golden_id,
                "artifact_sha256": artifact_hash,
                "passed": True,
                "check_count": 13,
                "failures": [],
            }
        )
        shared.append(
            {
                "golden_id": golden_id,
                "passed": True,
                "check_count": 7,
                "source_sha256": source_hash,
                "failures": [],
            }
        )
    return (
        {"passed": True, "model_calls": 0, "golden_count": 6, "goldens": actor},
        {"passed": True, "model_calls": 0, "golden_count": 6, "goldens": physics},
        {"passed": True, "model_calls": 0, "golden_count": 6, "goldens": shared},
    )


def _build_report(screenshot_root: Path, **kwargs):
    from scripts.verify_golden_release import build_report

    actor, physics, shared = _motion_evidence()
    return build_report(
        browser_evidence=_browser_evidence(screenshot_root),
        actor_motion=actor,
        physics_motion=physics,
        shared_state=shared,
        screenshot_root=screenshot_root,
        **kwargs,
    )


def test_browser_review_artifacts_are_byte_identical_to_served_localizations(
    tmp_path: Path,
):
    from scripts.verify_golden_release import write_current_shell_review_artifacts
    from server.goldens import (
        load_pinned_golden,
        localized_pinned_golden,
    )

    manifest = write_current_shell_review_artifacts(tmp_path)

    assert manifest["artifact_count"] == 12
    for item in manifest["artifacts"]:
        document = load_pinned_golden(item["golden_id"])
        assert document is not None
        served = localized_pinned_golden(document, item["locale"])["artifact"]
        reviewed = (tmp_path / item["filename"]).read_text(encoding="utf-8")
        assert reviewed.encode() == served.encode()
        assert item["artifact_sha256"] == hashlib.sha256(served.encode()).hexdigest()


def test_gold_01_report_covers_six_hash_bound_bilingual_goldens(tmp_path: Path):
    report = _build_report(tmp_path)

    assert report["schema_version"] == "1.0"
    assert report["gate"] == "GOLD-01"
    assert report["model_calls"] == 0
    assert report["passed"] is True
    assert report["golden_count"] == 6
    assert report["locale_journey_count"] == 12
    assert report["manifest"]["passed"] is True
    assert len(report["goldens"]) == 6
    for golden in report["goldens"]:
        assert golden["passed"] is True
        assert golden["manifest_hash_matches"] is True
        assert golden["artifact_sha256"]
        assert golden["document_sha256"]
        assert set(golden["locales"]) == {"ar", "en"}
        assert golden["science"]["passed"] is True
        assert golden["actor_motion"]["passed"] is True
        assert golden["physics_motion"]["passed"] is True
        assert golden["shared_state"]["passed"] is True
        assert all(item["passed"] for item in golden["locales"].values())
        assert len(golden["screenshots"]) == 4
        assert all(len(item["sha256"]) == 64 for item in golden["screenshots"])
    assert report["screenshot_count"] == 24


def test_gold_01_report_fails_closed_on_a_missing_locale_journey(tmp_path: Path):
    from scripts.verify_golden_release import build_report

    evidence = _browser_evidence(tmp_path)
    evidence["journeys"] = evidence["journeys"][:-1]
    evidence["journey_count"] = 11

    actor, physics, shared = _motion_evidence()

    report = build_report(
        browser_evidence=evidence,
        actor_motion=actor,
        physics_motion=physics,
        shared_state=shared,
        screenshot_root=tmp_path,
    )

    assert report["passed"] is False
    assert report["locale_journey_count"] == 11
    assert "missing_browser_locale" in {
        failure["code"]
        for golden in report["goldens"]
        for failure in golden["failures"]
    }


def test_gold_01_report_fails_closed_on_manifest_hash_drift(tmp_path: Path):
    report = _build_report(
        tmp_path, manifest_hash_overrides={"moon_phases": "0" * 64}
    )

    assert report["passed"] is False
    moon = next(item for item in report["goldens"] if item["golden_id"] == "moon_phases")
    assert moon["manifest_hash_matches"] is False
    assert "manifest_artifact_hash_mismatch" in {
        failure["code"] for failure in moon["failures"]
    }


def test_gold_01_report_fails_closed_on_any_browser_or_a11y_failure(tmp_path: Path):
    from scripts.verify_golden_release import build_report

    evidence = _browser_evidence(tmp_path)
    broken = deepcopy(evidence["journeys"][0])
    broken["passed"] = False
    broken["checks"]["keyboard_controls_named"] = False
    evidence["journeys"][0] = broken
    evidence["passed"] = False

    actor, physics, shared = _motion_evidence()

    report = build_report(
        browser_evidence=evidence,
        actor_motion=actor,
        physics_motion=physics,
        shared_state=shared,
        screenshot_root=tmp_path,
    )

    assert report["passed"] is False
    lesson = next(
        item for item in report["goldens"] if item["golden_id"] == broken["golden_id"]
    )
    assert lesson["locales"][broken["locale"]]["passed"] is False
    assert "browser_locale_failed" in {failure["code"] for failure in lesson["failures"]}


def test_gold_01_report_fails_closed_on_missing_screenshot(tmp_path: Path):
    from scripts.verify_golden_release import build_report

    evidence = _browser_evidence(tmp_path)
    missing = tmp_path / evidence["journeys"][0]["screenshots"][0]
    missing.unlink()
    actor, physics, shared = _motion_evidence()

    report = build_report(
        browser_evidence=evidence,
        actor_motion=actor,
        physics_motion=physics,
        shared_state=shared,
        screenshot_root=tmp_path,
    )

    assert report["passed"] is False
    assert "screenshot_missing" in {
        failure["code"]
        for golden in report["goldens"]
        for failure in golden["failures"]
    }


def test_gold_01_report_fails_closed_on_screenshot_hash_drift(tmp_path: Path):
    from scripts.verify_golden_release import build_report

    evidence = _browser_evidence(tmp_path)
    changed = tmp_path / evidence["journeys"][0]["screenshots"][0]
    changed.write_bytes(b"changed after browser evidence was captured")
    actor, physics, shared = _motion_evidence()

    report = build_report(
        browser_evidence=evidence,
        actor_motion=actor,
        physics_motion=physics,
        shared_state=shared,
        screenshot_root=tmp_path,
    )

    assert report["passed"] is False
    assert "screenshot_hash_mismatch" in {
        failure["code"]
        for golden in report["goldens"]
        for failure in golden["failures"]
    }
