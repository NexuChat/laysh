from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.browser
def test_all_six_pinned_goldens_prove_their_declared_physics_in_browser(tmp_path: Path):
    from server.golden_physics_motion import verify_golden_physics_motion
    from server.goldens import load_golden_fixtures, load_pinned_golden

    for fixture_id, fixture in load_golden_fixtures().items():
        golden_id = fixture_id.removesuffix("_ar")
        golden = load_pinned_golden(golden_id)

        assert golden is not None
        report = verify_golden_physics_motion(
            artifact=golden["artifact"],
            golden_id=golden_id,
            actor_profile=fixture["review_contract"]["actor_tracking"],
            physics_profile=fixture["review_contract"]["physics_motion"],
            geometry_profile=fixture["review_contract"].get("body_geometry"),
            screenshot_root=tmp_path / golden_id,
        )

        assert report["passed"] is True, report["failures"]
        assert report["evidence"]["actorSamples"]
        if fixture["review_contract"]["physics_motion"].get("temporal_runs"):
            assert report["evidence"]["temporalRuns"]
        if fixture["review_contract"].get("body_geometry"):
            assert len(report["evidence"]["geometrySamples"]) == 4 * 361
            assert report["minimum_clearance_px"] > 0
