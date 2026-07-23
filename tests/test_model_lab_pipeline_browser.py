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
def test_model_lab_controls_and_cascading_rerun_work_in_a_real_browser():
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(  # noqa: S603 - fixed local smoke application
        [
            str(ROOT / ".venv" / "bin" / "uvicorn"),
            "tests.model_lab_pipeline_smoke_app:app",
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
            "LAYSH_MODEL_LAB_ENABLED": "1",
            "LAYSH_MODEL_LAB_IP_COMPARISONS_PER_HOUR": "100",
            "LAYSH_MODEL_LAB_GLOBAL_COMPARISONS_PER_DAY": "100",
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
                    f"{base_url}/model-lab",
                    timeout=0.2,
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("model-lab smoke application did not start")

        completed = subprocess.run(  # noqa: S603 - fixed local browser harness
            [
                "node",
                str(ROOT / "tests" / "check_model_lab_pipeline.mjs"),
                base_url,
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
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
    assert report["stageCount"] == 11
    assert report["modelStageCount"] == 6
    assert report["initialRevisionStages"] == [
        "evidence",
        "understand",
        "physics",
        "plan",
        "visual",
        "verify",
        "browser",
        "repair_1",
        "repair_2",
        "qa",
        "finalize",
    ]
    assert report["rerunRevisionStages"] == [
        "physics",
        "plan",
        "visual",
        "verify",
        "browser",
        "repair_1",
        "repair_2",
        "qa",
        "finalize",
    ]
    assert report["consoleErrors"] == []
    assert report["failedRequests"] == []
