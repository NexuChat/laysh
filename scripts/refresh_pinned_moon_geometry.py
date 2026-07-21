from __future__ import annotations

import json

from server.golden_geometry import refresh_pinned_moon_geometry


def main() -> int:
    reports = refresh_pinned_moon_geometry()
    print(json.dumps({"refreshed": reports}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
