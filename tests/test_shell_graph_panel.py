from __future__ import annotations

import json
import socket
import subprocess
import time
from copy import deepcopy
from pathlib import Path

import pytest

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]


def _free_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _synthetic_module(scene_pattern: str) -> str:
    source = """
window.LayshSimulation = (() => {
  let canvas, context, width = 1, height = 1, emitFrame = () => {}, value = 5;
  function draw() {
    context.fillStyle = '#071520'; context.fillRect(0, 0, width, height);
    context.fillStyle = '#ffc247';
    context.fillRect(width * (0.15 + value / 100), height * .42, 28, 28);
    emitFrame();
  }
  const simulation = {
    version: 1,
    init(options) { ({ canvas, context, width, height, emitFrame } = options); draw(); },
    setParameter(name, next) { if (name === 'control_value') { value = Number(next); draw(); } },
    test(inputs) { return { response_value: Number(inputs.control_value) * 2 + 1 }; },
    resize(nextWidth, nextHeight) {
      width = nextWidth; height = nextHeight; canvas.width = width; canvas.height = height; draw();
    },
    destroy() { canvas = null; context = null; },
  };
  Object.defineProperty(simulation, 'spec', {
    value: Object.freeze({ representation: { scene_pattern: '@@SCENE_PATTERN@@' } }),
    enumerable: false,
  });
  return simulation;
})();
"""
    return source.replace("@@SCENE_PATTERN@@", scene_pattern)


def _artifact(scene_pattern: str) -> str:
    from server.assemble import assemble_artifact

    lesson = deepcopy(VALID_UNDERSTANDING)
    lesson.update(
        lang="en",
        title="Synthetic graph lesson",
        tldr="A synthetic lesson for the trusted shell.",
        misconception="Correction: the response is not independent of the control.",
        primary_parameter={
            "id": "control_value",
            "label": "Control value",
            "unit": "N",
            "min": 0,
            "max": 10,
            "default": 5,
            "step": 1,
        },
        prediction={"prompt": "What changes?", "choices": ["It rises", "It falls"]},
        module_spec={"outputs": ["response_value"], "actor": "visible_body", "action": "rotates"},
        checks=[
            {
                "id": "low", "kind": "numeric", "inputs": [{"name": "control_value", "value": 0}],
                "output": "response_value", "expected": 1, "tolerance": 0.01, "unit": "J",
            },
            {
                "id": "middle",
                "kind": "numeric",
                "inputs": [{"name": "control_value", "value": 5}],
                "output": "response_value", "expected": 11, "tolerance": 0.01, "unit": "J",
            },
            {
                "id": "high", "kind": "numeric", "inputs": [{"name": "control_value", "value": 10}],
                "output": "response_value", "expected": 21, "tolerance": 0.01, "unit": "J",
            },
        ],
    )
    artifact = assemble_artifact(
        lesson,
        {
            **VALID_MODULE_OUTPUT,
            "module_js": _synthetic_module(scene_pattern),
            "output_names": ["response_value"],
        },
    )
    return artifact


@pytest.mark.browser
def test_shell_graph_panel_is_opt_in_and_stays_usable_on_narrow_viewports(tmp_path: Path):
    (tmp_path / "world-only.html").write_text(_artifact("world_only"), encoding="utf-8")
    (tmp_path / "world-plus-graph.html").write_text(
        _artifact("world_plus_graph"), encoding="utf-8"
    )
    (tmp_path / "fixture_server.py").write_text(
        "from fastapi import FastAPI\nfrom fastapi.staticfiles import StaticFiles\n"
        "app = FastAPI()\napp.mount('/', StaticFiles(directory='.', html=True), name='fixture')\n",
        encoding="utf-8",
    )
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(  # noqa: S603 - fixed local uvicorn fixture command
        [
            str(ROOT / ".venv" / "bin" / "uvicorn"),
            "fixture_server:app",
            "--app-dir",
            str(tmp_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                import urllib.request

                with urllib.request.urlopen(  # noqa: S310 - fixed loopback fixture URL
                    f"{base_url}/world-only.html", timeout=0.2
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("local graph fixture server did not start")

        completed = subprocess.run(  # noqa: S603 - fixed local browser harness
            ["node", str(ROOT / "tests" / "check_shell_graph_panel.mjs"), base_url],
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

    assert evidence["worldOnly"] == {"graph": False, "sceneLayout": False}
    assert evidence["graph"]["exists"] is True
    assert evidence["graph"]["markerMoved"] is True
    assert "response value" in evidence["graph"]["ariaLabel"].lower()
    assert "increases" in evidence["graph"]["ariaLabel"].lower()
    assert all(
        item["stacked"] and item["predictionChoicesInsideViewport"]
        for item in evidence["mobile"]
    )
