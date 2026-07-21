from __future__ import annotations

import json

from server.goldens import refresh_pinned_golden_shared_model_states


def main() -> int:
    reports = refresh_pinned_golden_shared_model_states()
    print(json.dumps({"model_calls": 0, "reports": reports}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
