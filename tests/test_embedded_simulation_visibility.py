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
def test_every_gallery_simulation_is_visible_and_unclipped_at_supported_sizes():
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
            raise AssertionError("local embedded-simulation server did not start")

        completed = subprocess.run(  # noqa: S603 - fixed local browser harness
            ["node", str(ROOT / "tests" / "check_embedded_simulations.mjs"), base_url],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stderr
        evidence = json.loads(completed.stdout)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    measurements = evidence["measurements"]
    assert len(measurements) == 24
    failures = [
        {
            "cardId": item["cardId"],
            "viewport": item["viewport"],
            "iframeHeight": item["parent"]["iframeHeight"],
            "documentHeight": item["child"]["documentHeight"],
            "viewportWidth": item["child"]["viewportWidth"],
            "viewportHeight": item["child"]["viewportHeight"],
            "checks": item["checks"],
            "parent": item["parent"],
            "panel": item["child"]["panel"],
            "canvas": item["child"]["canvas"],
            "control": item["child"]["control"],
            "childFocus": item["childFocus"],
            "childKeyboard": item["childKeyboard"],
            "parentFocus": item["parentFocus"],
            "parentKeyboard": item["parentKeyboard"],
            "parentActiveAfterChildKeyboard": item["parentActiveAfterChildKeyboard"],
        }
        for item in measurements
        if not item["passed"]
    ]
    assert all(item["passed"] for item in measurements), json.dumps(
        failures,
        ensure_ascii=False,
        indent=2,
    )
    resize_measurements = evidence["resizeMeasurements"]
    assert len(resize_measurements) == 2
    resize_failures = [
        {
            "cardId": item["cardId"],
            "viewport": item["viewport"],
            "checks": item["checks"],
            "parent": item["parent"],
            "childFocus": item["childFocus"],
            "parentFocus": item["parentFocus"],
            "childKeyboard": item["childKeyboard"],
            "parentKeyboard": item["parentKeyboard"],
        }
        for item in resize_measurements
        if not item["passed"]
    ]
    assert all(item["passed"] for item in resize_measurements), json.dumps(
        resize_failures,
        ensure_ascii=False,
        indent=2,
    )

    required_viewports = {"narrow-mobile-320x844", "modern-mobile-390x844", "zoom-200pct"}
    required_measurements = [
        item for item in measurements if item["viewport"] in required_viewports
    ]
    assert len(required_measurements) == 18
    css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
    controller = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "height: 150px" not in css
    assert 'style.height = "150px"' not in controller
    assert all("150px" not in item["initialHeightWrites"] for item in required_measurements)
    assert all(item["checks"]["keyboardFocus"] for item in required_measurements)
    assert all(
        [step["selector"] for step in item["childKeyboard"]]
        == ["#play-pause", "#reset", "#replay"]
        for item in required_measurements
    )
    assert all(
        step["actualActiveId"] == step["selector"].removeprefix("#")
        and step["targetTabIndex"] == 0
        and not step["targetDisabled"]
        for item in required_measurements
        for step in item["childKeyboard"]
    )
    assert all(
        [step["selector"] for step in item["parentKeyboard"]]
        == ["#share-result", "#download", "#ask-another"]
        for item in required_measurements
    )
    assert all(
        step["actualActiveId"] == step["selector"].removeprefix("#")
        and step["targetTabIndex"] == 0
        and not step["targetDisabled"]
        for item in required_measurements
        for step in item["parentKeyboard"]
    )

    clocks = {item["slug"]: item for item in evidence["clocks"]}
    assert set(clocks) == {"pendulum", "sound_pitch"}
    for clock in clocks.values():
        assert clock["before"]["clock"]["now"] == 0
        assert clock["afterParameter"]["clock"]["now"] == 0
        assert clock["afterParameter"]["clock"]["executed"] == 0
        assert clock["afterParameter"]["value"] != clock["before"]["value"]
        assert clock["afterClock"]["clock"]["now"] == 96
        assert clock["afterClock"]["resumed"]["queued"] > 0
        assert clock["afterClock"]["playbackState"] == "running"
        assert clock["afterClock"]["clock"]["executed"] > 0, clock
        assert clock["afterClock"]["value"] == clock["afterParameter"]["value"]
