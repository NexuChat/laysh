from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def free_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


@pytest.mark.browser
def test_six_pinned_gallery_cards_open_instantly_without_generation():
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(  # noqa: S603 - fixed local application command
        [
            str(ROOT / ".venv" / "bin" / "uvicorn"),
            "server.app:create_app",
            "--factory",
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

                with urllib.request.urlopen(  # noqa: S310 - fixed loopback URL
                    f"{base_url}/healthz",
                    timeout=0.2,
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("local M5 server did not start")
        completed = subprocess.run(  # noqa: S603 - fixed local browser harness
            ["node", str(ROOT / "scripts" / "check_g5_gallery.mjs"), base_url],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert completed.returncode == 0, completed.stderr
        evidence = json.loads(completed.stdout)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    assert len(evidence["cards"]) == len(evidence["journeys"]) == 6
    assert all(card["badge"] == "فوري" and card["enabled"] for card in evidence["cards"])
    assert all(journey["visible"] and journey["src"] for journey in evidence["journeys"])
    assert all("فئة أ" in journey["tier"] for journey in evidence["journeys"])
    assert evidence["askPosts"] == 0
    assert evidence["externalRequests"] == 0
    assert evidence["consoleErrors"] == []
