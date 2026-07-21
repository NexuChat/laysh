from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from server.golden_physics_motion import verify_golden_physics_motion
from server.goldens import load_golden_fixtures, load_pinned_golden

ROOT = Path(__file__).parents[1]


def build_report(*, screenshot_root: Path | None = None) -> dict[str, object]:
    reports: list[dict[str, object]] = []
    for fixture_id, fixture in load_golden_fixtures().items():
        golden_id = fixture_id.removesuffix("_ar")
        golden = load_pinned_golden(golden_id)
        if golden is None:
            reports.append(
                {
                    "golden_id": golden_id,
                    "passed": False,
                    "check_count": 1,
                    "failures": [
                        {
                            "gate": "physics_motion_browser",
                            "code": "pinned_golden_unavailable",
                            "expected": {"pinned_tier_a_golden": True},
                            "actual": {"pinned_tier_a_golden": False},
                        }
                    ],
                    "evidence": {},
                }
            )
            continue
        report = verify_golden_physics_motion(
            artifact=golden["artifact"],
            golden_id=golden_id,
            actor_profile=fixture["review_contract"]["actor_tracking"],
            physics_profile=fixture["review_contract"]["physics_motion"],
            geometry_profile=fixture["review_contract"].get("body_geometry"),
            screenshot_root=(screenshot_root / golden_id) if screenshot_root else None,
        )
        reports.append(
            {
                "golden_id": golden_id,
                "artifact_sha256": hashlib.sha256(golden["artifact"].encode()).hexdigest(),
                "actor": fixture["review_contract"]["actor"],
                "action": fixture["review_contract"]["action"],
                **report,
            }
        )
    return {
        "schema_version": "1.0",
        "gate": "MOTION-03",
        "model_calls": 0,
        "golden_count": len(reports),
        "passed": all(report["passed"] for report in reports),
        "check_count": sum(int(report["check_count"]) for report in reports),
        "goldens": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic action-specific physics probes for pinned goldens."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "out" / "evidence" / "motion-03.json",
    )
    parser.add_argument(
        "--screens",
        type=Path,
        help="Optional directory for browser captures produced during the probe.",
    )
    arguments = parser.parse_args()
    report = build_report(screenshot_root=arguments.screens)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"passed": report["passed"], "output": str(arguments.output)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
