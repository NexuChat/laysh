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
def test_detection_switch_persistence_and_explicit_choice_in_a_real_browser():
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
                    f"{base_url}/healthz",
                    timeout=0.2,
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("local bilingual browser server did not start")
        completed = subprocess.run(  # noqa: S603 - fixed browser harness
            ["node", str(ROOT / "scripts" / "check_bilingual.mjs"), base_url],
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

    assert evidence["detectedEnglish"] == {
        "lang": "en",
        "dir": "ltr",
        "title": "Every curious question deserves an answer you can touch.",
        "lessonIds": [
            "moon_phases_en",
            "buoyancy_en",
            "pendulum_en",
            "simple_circuit_en",
            "sound_pitch_en",
            "day_night_en",
        ],
        "arabicLeaks": [],
        "switchVisible": True,
    }
    assert evidence["selectedArabic"]["lang"] == "ar"
    assert evidence["selectedArabic"]["dir"] == "rtl"
    assert evidence["selectedArabic"]["stored"] == "ar"
    assert evidence["selectedArabic"]["lessonIds"] == [
        "moon_phases",
        "buoyancy",
        "pendulum",
        "simple_circuit",
        "sound_pitch",
        "day_night",
    ]
    assert evidence["persistedArabic"] is True
    assert evidence["detectedArabic"] is True
    assert evidence["explicitEnglishWins"] == {
        "lang": "en",
        "dir": "ltr",
        "stored": "en",
        "lessonIds": [
            "moon_phases_en",
            "buoyancy_en",
            "pendulum_en",
            "simple_circuit_en",
            "sound_pitch_en",
            "day_night_en",
        ],
    }
    assert evidence["consoleErrors"] == []
