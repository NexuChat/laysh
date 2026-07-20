from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from server.schemas import CONTRACT_VERSION

ROOT = Path(__file__).parents[1]
FREEZE_REVISION = 2
DEFAULT_OUTPUT = ROOT / "contracts" / f"contracts-frozen-r{FREEZE_REVISION}.json"


def contract_paths() -> list[Path]:
    return sorted(
        [
            *ROOT.glob("server/schemas/*.json"),
            *ROOT.glob("server/prompts/*.md"),
            ROOT / "server" / "schemas.py",
            ROOT / "sim_shell" / "contract.js",
        ]
    )


def build_manifest() -> dict:
    files = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in contract_paths()
    }
    return {
        "schema_version": "1.0",
        "contract_version": CONTRACT_VERSION,
        "freeze_revision": FREEZE_REVISION,
        "algorithm": "sha256",
        "files": files,
    }


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze the current closed Laysh contracts.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    options = parser.parse_args(arguments)
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
