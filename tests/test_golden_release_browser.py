from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

@pytest.mark.browser
def test_gold_01_reviews_six_goldens_in_arabic_and_english(tmp_path: Path):
    from scripts.verify_golden_release import write_current_shell_review_artifacts

    output = tmp_path / "gold-01-browser.json"
    screenshots = tmp_path / "screens"
    artifacts = tmp_path / "artifacts"
    artifact_manifest = write_current_shell_review_artifacts(artifacts)
    assert artifact_manifest["artifact_count"] == 12

    completed = subprocess.run(  # noqa: S603 - fixed local browser harness
        [
            "node",
            str(ROOT / "scripts" / "check_golden_release.mjs"),
            str(artifacts),
            str(screenshots),
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))

    assert report["schema_version"] == "1.0"
    assert report["gate"] == "golden_browser_review"
    assert report["model_calls"] == 0
    assert report["passed"] is True
    assert report["journey_count"] == 12
    assert {(item["golden_id"], item["locale"]) for item in report["journeys"]} == {
        (golden_id, locale)
        for golden_id in (
            "buoyancy",
            "day_night",
            "moon_phases",
            "pendulum",
            "simple_circuit",
            "sound_pitch",
        )
        for locale in ("ar", "en")
    }
    for journey in report["journeys"]:
        assert journey["passed"] is True, journey
        assert set(journey["checks"].values()) == {True}
        assert {item["name"] for item in journey["responsive"]} == {
            "mobile-320x844",
            "mobile-390x844",
            "desktop-1440x900",
            "zoom-200",
        }
        assert all(item["passed"] for item in journey["responsive"])
        assert journey["a11y"]["unnamed_interactive_nodes"] == 0
        assert journey["a11y"]["duplicate_ids"] == []
        assert journey["console_errors"] == []
        assert journey["external_requests"] == 0
        assert len(journey["screenshots"]) == 2
        assert all(
            (ROOT / path).is_file() or (screenshots / Path(path).name).is_file()
            for path in journey["screenshots"]
        )
