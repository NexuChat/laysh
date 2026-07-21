from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.goldens import refresh_curated_pinned_shells

ROOT = Path(__file__).parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh reviewed pinned lessons with the current trusted shell."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "out" / "evidence" / "curated-shell-refresh.json",
    )
    arguments = parser.parse_args()
    report = refresh_curated_pinned_shells()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
