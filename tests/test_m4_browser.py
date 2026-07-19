import json
import os
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
def test_g4_mock_journeys_accessibility_and_accepted_screenshots(tmp_path):
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    screenshots = tmp_path / "screens"
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
        env=os.environ
        | {
            "LAYSH_IP_GENERATIONS_PER_HOUR": "100",
            "LAYSH_GLOBAL_GENERATIONS_PER_DAY": "100",
        },
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
            raise AssertionError("local M4 server did not start")

        completed = subprocess.run(  # noqa: S603 - fixed browser harness
            [
                "node",
                str(ROOT / "scripts" / "check_product.mjs"),
                base_url,
                str(screenshots),
            ],
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

    assert evidence["success"]["answerPinned"] is True
    assert evidence["success"]["resultVisible"] is True
    assert evidence["success"]["sandbox"] == "allow-scripts"
    assert evidence["success"]["receiptChecks"] >= 1
    assert evidence["failures"] == {
        "answerOnly": True,
        "unsafeRedirect": True,
        "generationFailed": True,
        "runtimeError": True,
        "backendDown": True,
        "cancelled": True,
    }
    assert evidence["buildStates"]["queued"] is True
    assert evidence["buildStates"]["reconnecting"] is True
    assert evidence["buildStates"]["stillTesting"] is True
    assert evidence["historyBack"] is True
    assert evidence["accessibility"]["unnamedInteractiveNodes"] == 0
    assert evidence["accessibility"]["duplicateIds"] == []
    assert evidence["accessibility"]["focusVisible"] is True
    assert evidence["accessibility"]["keyboardSequence"][:3] == [
        "question",
        "safe-example",
        "ask-submit",
    ]
    assert evidence["accessibility"]["smallTargets"] == []
    assert evidence["accessibility"]["strayEnglish"] == []
    assert evidence["responsive"]["overflow320"] is False
    assert evidence["responsive"]["overflowAt200Percent"] is False
    assert evidence["responsive"]["reducedMotion"] is True
    assert evidence["consoleErrors"] == []
    assert evidence["networkFailures"] == []
    assert (screenshots / "g4-result-mobile-390x844.png").stat().st_size > 20_000
    accepted = ROOT / "out" / "evidence" / "screens"
    assert (accepted / "g4-mobile-390x844.png").stat().st_size > 20_000
    assert (accepted / "g4-desktop-1440x900.png").stat().st_size > 20_000
    assert (screenshots / "g4-result-desktop-1440x900.png").stat().st_size > 20_000
