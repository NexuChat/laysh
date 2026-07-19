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


@pytest.mark.live
@pytest.mark.browser
@pytest.mark.skipif(os.getenv("LAYSH_RUN_LIVE_G4") != "1", reason="opt-in live G4 job")
def test_one_real_arabic_result_reaches_mobile_and_desktop_ui():
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    screenshots = ROOT / "out" / "evidence" / "screens"
    environment = {
        **os.environ,
        "LAYSH_CODEX_BACKEND": "codex",
        "LAYSH_RECORD_RUNTIME": "0",
        "LAYSH_PUBLIC_JOB_TIMEOUT_SECONDS": "180",
        "LAYSH_CACHE_KEY_SECRET": "",
        "LAYSH_UNDERSTAND_MODEL": "gpt-5.6-luna",
        "LAYSH_GENERATE_MODEL": "gpt-5.6-sol",
        "LAYSH_HEAL_MODEL": "gpt-5.6-sol",
        "LAYSH_QA_MODEL": "gpt-5.6-sol",
    }
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
        env=environment,
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
            raise AssertionError("live M4 server did not start")

        completed = subprocess.run(  # noqa: S603 - fixed browser harness
            [
                "node",
                str(ROOT / "scripts" / "check_live_product.mjs"),
                base_url,
                str(screenshots),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=220,
        )
        assert completed.returncode == 0, completed.stderr
        evidence = json.loads(completed.stdout)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    assert evidence["liveJobCount"] == 1
    assert evidence["answerObservedBeforeResult"] is True
    assert evidence["resultVisible"] is True
    assert evidence["sandbox"] == "allow-scripts"
    assert evidence["checkCount"] >= 1
    assert evidence["effectiveModel"].startswith("gpt-5.6-")
    assert evidence["consoleErrors"] == []
    assert (screenshots / "g4-live-mobile-390x844.png").stat().st_size > 20_000
    assert (screenshots / "g4-live-desktop-1440x900.png").stat().st_size > 20_000
