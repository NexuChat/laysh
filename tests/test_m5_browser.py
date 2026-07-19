from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.browser
def test_golden_harness_exercises_min_default_max_and_captures_both_viewports(tmp_path):
    from server.assemble import assemble_artifact
    from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

    module_output = {
        **VALID_MODULE_OUTPUT,
        "module_js": (ROOT / "tests" / "fixtures" / "moon_phase_module.js").read_text(
            encoding="utf-8"
        ),
    }
    artifact_path = tmp_path / "golden.html"
    artifact_path.write_text(
        assemble_artifact(VALID_UNDERSTANDING, module_output),
        encoding="utf-8",
    )
    screenshot_root = tmp_path / "screens"

    completed = subprocess.run(  # noqa: S603 - fixed local browser harness and test artifact
        [
            "node",
            str(ROOT / "scripts" / "check_golden.mjs"),
            str(artifact_path),
            str(screenshot_root),
            "moon_phases",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence["ready"] is True
    assert evidence["runtimeError"] is False
    assert evidence["lang"] == "ar" and evidence["dir"] == "rtl"
    assert [case["value"] for case in evidence["cases"]] == [0, 90, 360]
    assert all(case["frameChanged"] for case in evidence["cases"])
    assert evidence["alternative"]
    assert evidence["externalRequests"] == 0
    assert evidence["consoleErrors"] == []
    for filename in evidence["screenshots"]:
        assert (screenshot_root / filename).stat().st_size > 10_000
