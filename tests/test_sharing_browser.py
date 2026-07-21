from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _free_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


@contextmanager
def _running_app(port: int, share_root: Path):
    process = subprocess.Popen(  # noqa: S603 - fixed local application command
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
            "LAYSH_SHARE_ROOT": str(share_root),
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
                    f"http://127.0.0.1:{port}/healthz",
                    timeout=0.2,
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("local sharing server did not start")
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _browser(mode: str, base_url: str, value: str = "") -> dict:
    completed = subprocess.run(  # noqa: S603 - fixed local browser harness
        [
            "node",
            str(ROOT / "tests" / "check_sharing.mjs"),
            mode,
            base_url,
            value,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.browser
def test_keyboard_copy_is_localized_and_shared_artifact_recovers_after_restart(tmp_path):
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    share_root = tmp_path / "durable-shares"

    with _running_app(port, share_root):
        created = _browser("create", base_url)

    with _running_app(port, share_root):
        recovered = _browser("recover", base_url, created["copiedUrl"])

    assert created["keyboardActivated"] is True
    assert created["arabicFeedback"] == "نُسخ رابط التجربة."
    assert created["englishFailure"] == "Could not copy the link. Try again."
    assert created["sharePath"].startswith("/s/sh_")
    assert "private-browser-question-7391" not in created["copiedUrl"]
    assert recovered == {
        "artifactReady": True,
        "scientificCanvas": True,
        "rawQuestionAbsent": True,
        "consoleErrors": [],
        "networkFailures": [],
    }
