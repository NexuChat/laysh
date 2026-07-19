from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.settings import ALLOWED_RUNTIME_MODELS  # noqa: E402

DEFAULT_REPORT = ROOT / "out" / "preflight.json"


def _version(command: str, *arguments: str) -> str:
    executable = shutil.which(command)
    if not executable:
        return "unavailable"
    completed = subprocess.run(  # noqa: S603
        [executable, *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    output = (completed.stdout or completed.stderr).strip().splitlines()
    return output[0] if output else f"exit {completed.returncode}"


def _authenticated() -> bool:
    executable = shutil.which("codex")
    if not executable:
        return False
    completed = subprocess.run(  # noqa: S603
        [executable, "login", "status"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    return completed.returncode == 0


def probe_environment() -> dict:
    usage = shutil.disk_usage(ROOT)
    browser_path = shutil.which("google-chrome") or shutil.which("chromium") or "unavailable"
    return {
        "codex_path": shutil.which("codex") or "unavailable",
        "codex_version": _version("codex", "--version"),
        "codex_authenticated": _authenticated(),
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "node": _version("node", "--version").removeprefix("v"),
        "npm": _version("npm", "--version"),
        "browser_path": browser_path,
        "browser": (
            _version(browser_path, "--version") if browser_path != "unavailable" else "unavailable"
        ),
        "cloudflared": _version("cloudflared", "--version"),
        "systemd": _version("systemctl", "--version").split()[1],
        "disk_available_gib": round(usage.free / 1024**3),
        "disk_use_percent": round((usage.used / usage.total) * 100),
    }


def _validate_gpt56_routing(report: dict) -> None:
    routing = report.get("routing", {})
    configured_models = [
        value
        for key, value in routing.items()
        if key.endswith("_model") and isinstance(value, str)
    ]
    if not configured_models or any(
        model not in ALLOWED_RUNTIME_MODELS for model in configured_models
    ):
        raise ValueError("every configured runtime model must be in the approved GPT-5.6 family")


def update_preflight(
    report_path: Path,
    *,
    primary_session_id: str | None = None,
    environment_probe: Callable[[], dict] = probe_environment,
) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("sanitized") is not True:
        raise ValueError("preflight report must remain sanitized")
    _validate_gpt56_routing(report)
    existing_session = report.setdefault("competition", {}).get("primary_build_thread")
    selected_session = primary_session_id or existing_session
    if not selected_session or "pending" in selected_session:
        raise ValueError("primary build Session ID is required for release preflight")
    report["competition"]["primary_build_thread"] = selected_session
    report["environment"] = environment_probe()
    report["last_rechecked_at_utc"] = datetime.now(UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    report.setdefault("release_confirmations", {})["asset_licenses"] = (
        "MIT application code; GNU FreeFont under GPLv3+ with Font Exception"
    )
    report["release_confirmations"]["repository_visibility_for_judging"] = (
        "owner will create and push the public repository after G6"
    )
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Recheck sanitized Laysh release prerequisites")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--primary-session-id")
    arguments = parser.parse_args()
    report = update_preflight(
        arguments.report,
        primary_session_id=arguments.primary_session_id,
    )
    summary = {
        "sanitized": report["sanitized"],
        "last_rechecked_at_utc": report["last_rechecked_at_utc"],
        "primary_build_thread": report["competition"]["primary_build_thread"],
        "runtime_family_policy": report["routing"]["runtime_family_policy"],
        "environment": report["environment"],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
