from __future__ import annotations

import json

from server.goldens import refresh_pinned_golden_teaching_shells


def main() -> int:
    reports = refresh_pinned_golden_teaching_shells()
    print(json.dumps({"refreshed": reports}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
