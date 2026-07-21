from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main() -> int:
    from server.session_provenance import ProvenanceError, verify_repository

    try:
        report = verify_repository(ROOT)
    except (OSError, ValueError, ProvenanceError) as error:
        print(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "passed": False,
                    "error": str(error),
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
