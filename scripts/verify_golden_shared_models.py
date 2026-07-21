from __future__ import annotations

import hashlib
import json
from pathlib import Path

from server.goldens import GOLDEN_ROOT, _artifact_lesson_and_module, list_pinned_goldens
from server.shared_state import shared_model_report

ROOT = Path(__file__).parents[1]
EVIDENCE_PATH = ROOT / "out" / "evidence" / "motion-04.json"


def verify_pinned_shared_models(*, root: Path = GOLDEN_ROOT) -> dict[str, object]:
    reports: list[dict[str, object]] = []
    for document in list_pinned_goldens(root=root):
        _, source = _artifact_lesson_and_module(document["artifact"])
        report = shared_model_report(source)
        reports.append(
            {
                "golden_id": document["golden_id"],
                "passed": report["passed"],
                "check_count": report["check_count"],
                "model_function": report["model_function"],
                "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "failures": report["failures"],
            }
        )
    return {
        "schema_version": "1.0",
        "gate": "MOTION-04",
        "model_calls": 0,
        "golden_count": len(reports),
        "passed": all(report["passed"] for report in reports),
        "check_count": sum(int(report["check_count"]) for report in reports),
        "goldens": reports,
    }


def main() -> int:
    evidence = verify_pinned_shared_models()
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
