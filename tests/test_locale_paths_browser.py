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
def test_locale_path_switches_visible_copy_persists_and_serves_shared_pages():
    port = _free_port()
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
                    f"{base_url}/healthz", timeout=0.2
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("local locale-path browser server did not start")

        completed = subprocess.run(  # noqa: S603 - fixed local browser harness
            ["node", str(ROOT / "tests" / "check_locale_paths.mjs"), base_url],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr
        evidence = json.loads(completed.stdout)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    assert evidence["english"] == {
        "lang": "en",
        "dir": "ltr",
        "hero": "Every curious question deserves an answer you can touch.",
        "pressed": ["false", "true"],
        "path": "/en",
        "stored": "en",
    }
    assert evidence["arabic"] == {
        "lang": "ar",
        "dir": "rtl",
        "hero": "كل سؤال فضولي يستحق جوابًا يمكنك لمسه.",
        "pressed": ["true", "false"],
        "path": "/ar",
        "stored": "ar",
    }
    assert evidence["reloadedArabic"] is True
    assert evidence["sharedEnglish"] == {
        "lang": "en",
        "dir": "ltr",
        "hero": "Every curious question deserves an answer you can touch.",
        "path": "/en/sims/golden_moon_phases_en",
        "sharePath": "/en/sims/golden_moon_phases_en",
        "resultVisible": True,
    }
    assert evidence["sharedArabic"] == {
        "lang": "ar",
        "hero": "كل سؤال فضولي يستحق جوابًا يمكنك لمسه.",
        "path": "/ar/sims/golden_moon_phases_en",
        "resultVisible": True,
    }
