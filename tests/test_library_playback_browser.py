from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.browser
def test_six_pinned_lesson_modules_self_play_and_yield_to_controls(tmp_path):
    from server.assemble import assemble_artifact
    from server.goldens import _artifact_lesson_and_module, list_pinned_goldens

    artifact_root = tmp_path / "library"
    artifact_root.mkdir()
    for document in list_pinned_goldens():
        lesson, module_js = _artifact_lesson_and_module(document["artifact"])
        artifact = assemble_artifact(
            lesson,
            {
                "module_js": module_js,
                "output_names": lesson["module_spec"]["outputs"],
                "brief_summary": "offline LIB-01 trusted-shell probe",
                "assumptions": document["review"]["reference_contract"]["assumptions"],
            },
        )
        (artifact_root / f'{document["golden_id"]}.html').write_text(
            artifact,
            encoding="utf-8",
        )

    completed = subprocess.run(  # noqa: S603 - fixed local browser harness and artifacts
        [
            "node",
            str(ROOT / "tests" / "check_library_playback.mjs"),
            str(artifact_root),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["lessonCount"] == 6
    assert report["passed"] is True, {
        lesson["id"]: {
            **{key: value for key, value in lesson["normal"]["checks"].items() if not value},
            **{key: value for key, value in lesson["reduced"]["checks"].items() if not value},
        }
        for lesson in report["lessons"]
        if not lesson["passed"]
    }
