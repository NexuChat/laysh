from __future__ import annotations

import json
import os
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
def test_ar_en_snapshots_direction_and_locale_control_event_scope(tmp_path):
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    screenshots = tmp_path / "i18n-snapshots"
    server = subprocess.Popen(
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

                with urllib.request.urlopen(f"{base_url}/healthz", timeout=0.2) as response:  # noqa: S310
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("local I18N server did not start")

        completed = subprocess.run(
            [
                "node",
                str(ROOT / "tests" / "check_continuation_i18n.mjs"),
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

    assert evidence["arabic"] == {"lang": "ar", "dir": "rtl", "landing": True}
    assert evidence["english"]["lang"] == "en"
    assert evidence["english"]["dir"] == "ltr"
    assert evidence["english"]["landing"] is True
    assert evidence["english"]["gallery"] is True
    assert evidence["english"]["golden"] == {
        "title": "How do the Moon's phases change?",
        "direction": True,
        "lesson": True,
    }
    assert evidence["english"]["build"] is True
    assert evidence["english"]["result"] is True
    assert evidence["english"]["receipt"] is True
    assert evidence["english"]["failure"] is True
    assert evidence["english"]["artifactDirection"] is True
    assert evidence["requestLocales"] == ["en", "en"]
    assert evidence["eventScope"] == {
        "beforeControl": "ar",
        "afterOutsideClicks": "ar",
        "outsideWrites": [],
        "afterControl": "en",
        "controlWrites": [["laysh-locale", "en"]],
        "persistedAfterReload": "en",
    }
    assert evidence["consoleErrors"] == []
    assert evidence["networkFailures"] == []
    for name in (
        "i18n-ar-landing.png",
        "i18n-en-landing.png",
        "i18n-en-golden.png",
        "i18n-en-result.png",
    ):
        assert (screenshots / name).stat().st_size > 20_000
