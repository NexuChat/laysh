from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_g5_evidence_has_six_reviewed_pinned_goldens_and_two_live_smokes():
    from server.goldens import GOLDEN_FIXTURE_IDS, golden_id_for_fixture, load_golden_fixtures

    fixtures = load_golden_fixtures()
    verdict = json.loads(
        (ROOT / "out" / "evidence" / "g5-verdict.json").read_text(encoding="utf-8")
    )
    smokes = json.loads(
        (ROOT / "out" / "evidence" / "g5-unseen-smokes.json").read_text(encoding="utf-8")
    )
    gallery = json.loads(
        (ROOT / "out" / "evidence" / "g5-gallery-browser.json").read_text(
            encoding="utf-8"
        )
    )

    assert verdict["verdict"] == "pass" and verdict["golden_count"] == 6
    assert verdict["total_live_call_count"] == 41
    assert smokes["passed"] is True and len(smokes["results"]) == 2
    assert {result["locale"] for result in smokes["results"]} == {"ar", "en"}
    assert len(gallery["cards"]) == len(gallery["journeys"]) == 6
    assert gallery["askPosts"] == gallery["externalRequests"] == 0
    assert gallery["consoleErrors"] == []
    for fixture_id in GOLDEN_FIXTURE_IDS:
        golden_id = golden_id_for_fixture(fixture_id)
        pinned = json.loads(
            (ROOT / "out" / "cache" / "golden" / f"{golden_id}.json").read_text(
                encoding="utf-8"
            )
        )
        manual = json.loads(
            (
                ROOT
                / "out"
                / "evidence"
                / "goldens"
                / f"{golden_id}-manual-review.json"
            ).read_text(encoding="utf-8")
        )
        browser = json.loads(
            (
                ROOT
                / "out"
                / "evidence"
                / "goldens"
                / f"{golden_id}-browser.json"
            ).read_text(encoding="utf-8")
        )
        parameter = fixtures[fixture_id]["review_contract"]["primary_parameter"]
        assert pinned["tier"] == "A" and pinned["pinned"] is True
        assert manual["verdict"] == "pass"
        assert [case["value"] for case in browser["cases"]] == [
            parameter["min"],
            parameter["default"],
            parameter["max"],
        ]
        assert browser["runtimeError"] is False
        assert browser["externalRequests"] == 0
        for viewport in ("mobile-390x844", "desktop-1440x900"):
            screenshot = (
                ROOT
                / "out"
                / "evidence"
                / "screens"
                / "goldens"
                / f"{golden_id}-{viewport}.png"
            )
            assert screenshot.stat().st_size > 10_000
