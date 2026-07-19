from __future__ import annotations

import hashlib
from pathlib import Path

from server.schemas import CONTRACT_VERSION

ROOT = Path(__file__).parents[1]


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
        "algorithm": "sha256",
        "files": files,
    }
