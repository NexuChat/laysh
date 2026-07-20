from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

ACTOR_PROFILE = {
    "actor_region": {"x": 0.2, "y": 0.2, "width": 0.5, "height": 0.5},
    "sample_count": 4,
    "sample_interval_ms": 30,
    "actor_color": {"red": 255, "green": 204, "blue": 0, "tolerance": 4},
}


def _module(kind: str) -> str:
    if kind == "positive":
        actor = "var x = width * (0.25 + value / 360 * 0.34);"
        decoration = ""
    elif kind == "moving_background_only":
        actor = "var x = width * 0.42;"
        decoration = (
            "context.fillStyle = 'rgb(' + (20 + value % 100) + ',30,50)'; "
            "context.fillRect(0, 0, width, height);"
        )
    elif kind == "particles_outside_actor_region":
        actor = "var x = width * 0.42;"
        decoration = (
            "context.fillStyle = '#57d5ff'; "
            "context.fillRect(width * 0.88, value % height, 9, 9);"
        )
    elif kind == "hidden_actor":
        actor = "var x = width * 1.2;"
        decoration = ""
    elif kind == "frame_counter_only":
        actor = "var x = width * 0.42;"
        decoration = ""
    else:  # pragma: no cover - fixed parametrization below
        raise AssertionError(kind)
    return f"""
window.LayshSimulation = (function () {{
  var context = null, width = 1, height = 1, emitFrame = function () {{}}, value = 90;
  function draw() {{
    context.fillStyle = '#091526'; context.fillRect(0, 0, width, height);
    {decoration}
    {actor}
    context.fillStyle = '#ffcc00'; context.fillRect(x, height * 0.43, 22, 22);
    emitFrame();
  }}
  return {{
    version: 1,
    init: function (options) {{
      context = options.context; width = options.width; height = options.height;
      emitFrame = options.emitFrame; draw();
    }},
    setParameter: function (_name, next) {{ value = Number(next); draw(); }},
    test: function (inputs) {{ return {{ lit_fraction: Number(inputs.angle_deg) / 360 }}; }},
    resize: function (nextWidth, nextHeight) {{ width = nextWidth; height = nextHeight; draw(); }},
    destroy: function () {{ context = null; }}
  }};
}}());
"""


def _artifact(kind: str) -> str:
    from server.assemble import assemble_artifact
    from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

    module_output = {**VALID_MODULE_OUTPUT, "module_js": _module(kind)}
    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["primary_parameter"] = {
        "id": "angle_deg",
        "label": "زاوية",
        "unit": "°",
        "min": 0,
        "max": 360,
        "default": 90,
        "step": 1,
    }
    return assemble_artifact(understanding, module_output)


def _browser_actor_samples(tmp_path: Path, kind: str) -> list[dict[str, object]]:
    artifact_path = tmp_path / f"{kind}.html"
    artifact_path.write_text(_artifact(kind), encoding="utf-8")
    profile_path = tmp_path / f"{kind}-profile.json"
    profile_path.write_text(json.dumps(ACTOR_PROFILE), encoding="utf-8")
    report_path = tmp_path / f"{kind}-report.json"
    completed = subprocess.run(  # noqa: S603 - fixed local browser harness and disposable files
        [
            "node",
            str(ROOT / "scripts" / "check_golden.mjs"),
            str(artifact_path),
            str(tmp_path / "screens"),
            kind,
            str(report_path),
            str(profile_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)["actorSamples"]


@pytest.mark.browser
def test_browser_probe_tracks_the_declared_actor_across_four_controlled_samples(tmp_path):
    from server.motion import evaluate_actor_trajectory

    report = evaluate_actor_trajectory(ACTOR_PROFILE, _browser_actor_samples(tmp_path, "positive"))

    assert report["passed"] is True
    assert len(report["evidence"]["actor_signatures"]) == 4


@pytest.mark.browser
@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        ("moving_background_only", "actor_trajectory_static"),
        ("particles_outside_actor_region", "actor_trajectory_static"),
        ("hidden_actor", "actor_not_visible"),
        ("frame_counter_only", "actor_trajectory_static"),
    ],
)
def test_browser_probe_rejects_decorative_or_missing_actor_motion(
    tmp_path, kind: str, expected_code: str
):
    from server.motion import evaluate_actor_trajectory

    report = evaluate_actor_trajectory(ACTOR_PROFILE, _browser_actor_samples(tmp_path, kind))

    assert report["passed"] is False
    assert expected_code in {failure["code"] for failure in report["failures"]}


@pytest.mark.browser
def test_all_six_pinned_goldens_pass_actor_only_browser_tracking(tmp_path):
    from server.golden_motion import verify_golden_actor_motion
    from server.goldens import load_golden_fixtures, load_pinned_golden

    for fixture_id, fixture in load_golden_fixtures().items():
        golden_id = fixture_id.removesuffix("_ar")
        golden = load_pinned_golden(golden_id)
        assert golden is not None

        report = verify_golden_actor_motion(
            artifact=golden["artifact"],
            golden_id=golden_id,
            profile=fixture["review_contract"]["actor_tracking"],
            screenshot_root=tmp_path / golden_id,
        )

        assert report["passed"] is True, report["failures"]
        assert len(report["evidence"]["actorSamples"]) == 4
