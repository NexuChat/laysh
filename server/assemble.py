from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from server.schemas import validate_module_output, validate_understanding

ROOT = Path(__file__).parents[1]
SHELL_DIR = ROOT / "sim_shell"
PORTABLE_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'"
)


def _safe_script_json(value: dict[str, Any]) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def assemble_artifact(understanding: dict[str, Any], module_output: dict[str, Any]) -> str:
    validate_understanding(understanding)
    validate_module_output(module_output)
    direction = "rtl" if understanding["lang"] == "ar" else "ltr"
    replacements = {
        "@@LANG@@": understanding["lang"],
        "@@DIR@@": direction,
        "@@CSP@@": PORTABLE_CSP,
        "@@TITLE@@": html.escape(understanding["title"], quote=True),
        "@@SHELL_CSS@@": (SHELL_DIR / "shell.css").read_text(encoding="utf-8"),
        "@@LESSON_JSON@@": _safe_script_json(understanding),
        "@@CONTRACT_JS@@": (SHELL_DIR / "contract.js").read_text(encoding="utf-8"),
        "@@MODULE_JS@@": module_output["module_js"],
        "@@SHELL_JS@@": (SHELL_DIR / "shell.js").read_text(encoding="utf-8"),
    }
    artifact = (SHELL_DIR / "shell.html").read_text(encoding="utf-8")
    for marker, value in replacements.items():
        artifact = artifact.replace(marker, value)
    if "@@" in artifact:
        raise ValueError("unresolved trusted-shell marker")
    return artifact

