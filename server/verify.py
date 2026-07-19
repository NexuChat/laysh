from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class ModuleSecurityError(ValueError):
    """The generated source requests a capability outside the module contract."""


FORBIDDEN_PATTERNS = [
    r"<\s*!?doctype\b",
    r"<\s*html\b",
    r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b",
    r"\b(?:localStorage|sessionStorage|indexedDB|document|location)\b",
    r"\b(?:parent|top|opener|navigator|Worker|SharedWorker)\b",
    r"\b(?:eval|Function|importScripts)\s*\(",
    r"\bimport\s*\(",
    r"\b(?:cookie|clipboard|microphone|camera)\b",
    r"(?:https?|wss?):\/\/",
]


def verify_module_source(source: str) -> dict[str, Any]:
    encoded_size = len(source.encode("utf-8"))
    if encoded_size > 40 * 1024:
        raise ModuleSecurityError("module exceeds the 40 KiB source limit")
    if source.count("window.LayshSimulation") != 1:
        raise ModuleSecurityError("module must assign window.LayshSimulation exactly once")
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, source, flags=re.IGNORECASE):
            raise ModuleSecurityError("module contains a forbidden capability")
    return {"source_size_bytes": encoded_size, "forbidden_capabilities": 0}


def verify_module_with_node(source: str, understanding: dict[str, Any]) -> dict[str, Any]:
    verify_module_source(source)
    verifier = Path(__file__).parents[1] / "scripts" / "verify_module.mjs"
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js is required for module verification")
    with tempfile.TemporaryDirectory(prefix="laysh-verify-") as temporary:
        temporary_path = Path(temporary)
        source_path = temporary_path / "module.js"
        contract_path = temporary_path / "understanding.json"
        source_path.write_text(source, encoding="utf-8")
        contract_path.write_text(json.dumps(understanding, ensure_ascii=False), encoding="utf-8")
        completed = subprocess.run(  # noqa: S603 - fixed executable; candidate is a VM input file
            [node, str(verifier), str(source_path), str(contract_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    if completed.returncode != 0:
        raise ValueError("module failed the bounded Node contract check")
    return json.loads(completed.stdout)
