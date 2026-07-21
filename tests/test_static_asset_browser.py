from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _free_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


@pytest.mark.browser
def test_versioned_assets_load_immutably_in_a_fresh_browser_profile():
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(  # noqa: S603 - fixed local smoke application
        [
            str(ROOT / ".venv" / "bin" / "uvicorn"),
            "tests.static_asset_smoke_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                import urllib.request

                with urllib.request.urlopen(base_url, timeout=0.2) as response:  # noqa: S310
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("static asset smoke application did not start")
        completed = subprocess.run(  # noqa: S603 - fixed local browser harness
            [
                "node",
                str(ROOT / "tests" / "check_static_assets.mjs"),
                base_url,
                str(ROOT / "web" / "asset-manifest.json"),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["passed"] is True, report
    assert report["responseCount"] >= 6
