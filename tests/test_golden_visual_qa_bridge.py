from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]


class RecordingVisualBackend:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def visual_qa(
        self,
        understanding,
        screenshots,
        gate_outcome,
        *,
        runtime_context,
    ):
        self.calls.append(
            {
                "understanding": understanding,
                "screenshots": screenshots,
                "gate_outcome": gate_outcome,
                "runtime_context": runtime_context,
            }
        )
        return SimpleNamespace(
            data={
                "actor_visible": True,
                "action_performed": True,
                "physically_consistent": True,
                "defects": [],
            },
            model="gpt-5.6-terra",
            elapsed_ms=17,
            thread_id="visual-thread",
        )


def _write_visual_images(root: Path, golden_id: str) -> list[str]:
    root.mkdir(parents=True, exist_ok=True)
    names = [
        f"{golden_id}-visual-qa-initial.png",
        f"{golden_id}-visual-qa-mid-action.png",
        f"{golden_id}-visual-qa-parameter-changed.png",
    ]
    for name in names:
        (root / name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"evidence" * 256)
    return names


@pytest.mark.browser
def test_golden_browser_harness_captures_three_ordered_states_bound_to_artifact(
    tmp_path: Path,
):
    from server.assemble import assemble_artifact

    fixture_source = (ROOT / "tests" / "fixtures" / "moon_phase_module.js").read_text(
        encoding="utf-8"
    )
    fixture_source = fixture_source.replace(
        "let angleDeg = 90;",
        "let angleDeg = 90;\n  let motionPhase = 0;",
    ).replace(
        "const state = moonState(angleDeg);\n    const fraction = state.lit_fraction;",
        "const state = moonState(angleDeg);\n"
        "    motionPhase += 0.45;\n"
        "    const fraction = state.lit_fraction;",
    ).replace(
        "context.arc(width / 2, height / 2, Math.min(width, height) * 0.27,",
        "context.arc(width / 2 + Math.sin(motionPhase) * 24, height / 2, "
        "Math.min(width, height) * 0.27,",
    )
    artifact = assemble_artifact(
        VALID_UNDERSTANDING,
        {**VALID_MODULE_OUTPUT, "module_js": fixture_source},
    )
    artifact_path = tmp_path / "candidate.html"
    artifact_path.write_text(artifact, encoding="utf-8")
    screenshot_root = tmp_path / "screens"

    completed = subprocess.run(  # noqa: S603 - fixed local harness and test artifact
        [
            "node",
            str(ROOT / "scripts" / "check_golden.mjs"),
            str(artifact_path),
            str(screenshot_root),
            "candidate",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence["artifactSha256"] == hashlib.sha256(artifact.encode()).hexdigest()
    assert evidence["visualQaScreenshots"] == [
        "candidate-visual-qa-initial.png",
        "candidate-visual-qa-mid-action.png",
        "candidate-visual-qa-parameter-changed.png",
    ]
    assert evidence["visualQaParameterChanged"] is True
    assert evidence["visualQaMidActionChanged"] is True
    for filename in evidence["visualQaScreenshots"]:
        assert (screenshot_root / filename).stat().st_size > 1_000


@pytest.mark.asyncio
async def test_visual_qa_bridge_uses_ordered_bound_images_and_persists_verdict(
    tmp_path: Path,
):
    from scripts.generate_goldens import _attach_visual_qa

    artifact = "<!doctype html><title>candidate</title>"
    artifact_sha256 = hashlib.sha256(artifact.encode()).hexdigest()
    golden_id = "candidate"
    screenshot_root = tmp_path / "screens"
    screenshot_names = _write_visual_images(screenshot_root, golden_id)
    browser_evidence = {
        "artifactSha256": artifact_sha256,
        "visualQaScreenshots": screenshot_names,
        "visualQaMidActionChanged": True,
        "visualQaParameterChanged": True,
        "ready": True,
        "runtimeError": False,
        "externalRequests": 0,
        "consoleErrors": [],
        "cases": [{"frameChanged": True}] * 3,
    }
    outputs = {
        "understanding": VALID_UNDERSTANDING,
        "verification": {"passed": True, "check_count": 41},
        "browser": {"ready": True},
    }
    backend = RecordingVisualBackend()

    binding = await _attach_visual_qa(
        backend=backend,
        fixture_id="moon_phases_ar",
        golden_id=golden_id,
        artifact=artifact,
        screenshot_root=screenshot_root,
        browser_evidence=browser_evidence,
        builder_outputs=outputs,
    )

    assert outputs["visual_qa"] == {
        "actor_visible": True,
        "action_performed": True,
        "physically_consistent": True,
        "defects": [],
    }
    assert binding == {
        "artifact_sha256": artifact_sha256,
        "screenshots": screenshot_names,
    }
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert tuple(path.name for path in call["screenshots"]) == tuple(screenshot_names)
    assert call["gate_outcome"] == {
        "passed": True,
        "check_count": 41,
        "gate_names": ["deterministic", "browser"],
    }
    assert call["runtime_context"].public is False
    assert call["runtime_context"].evidence_fixture_id == "moon_phases_ar"


@pytest.mark.asyncio
async def test_visual_qa_bridge_never_calls_model_before_both_gates_pass(tmp_path: Path):
    from scripts.generate_goldens import _attach_visual_qa

    artifact = "candidate"
    artifact_sha256 = hashlib.sha256(artifact.encode()).hexdigest()
    screenshot_root = tmp_path / "screens"
    names = _write_visual_images(screenshot_root, "candidate")
    evidence = {
        "artifactSha256": artifact_sha256,
        "visualQaScreenshots": names,
        "visualQaMidActionChanged": True,
        "visualQaParameterChanged": True,
    }
    backend = RecordingVisualBackend()

    with pytest.raises(ValueError, match="passing deterministic and browser gates"):
        await _attach_visual_qa(
            backend=backend,
            fixture_id="moon_phases_ar",
            golden_id="candidate",
            artifact=artifact,
            screenshot_root=screenshot_root,
            browser_evidence=evidence,
            builder_outputs={
                "understanding": VALID_UNDERSTANDING,
                "verification": {"passed": False, "check_count": 40},
                "browser": {},
            },
        )
    assert backend.calls == []


def test_stale_browser_or_visual_evidence_cannot_promote(tmp_path: Path):
    from scripts.generate_goldens import _verify_bound_visual_evidence

    artifact = "verified candidate"
    artifact_sha256 = hashlib.sha256(artifact.encode()).hexdigest()
    screenshot_root = tmp_path / "screens"
    names = _write_visual_images(screenshot_root, "candidate")
    browser_report = {
        "artifactSha256": artifact_sha256,
        "visualQaScreenshots": names,
    }
    binding = {"artifact_sha256": artifact_sha256, "screenshots": names}

    _verify_bound_visual_evidence(
        artifact=artifact,
        golden_id="candidate",
        screenshot_root=screenshot_root,
        browser_report=browser_report,
        visual_qa_evidence=binding,
    )

    with pytest.raises(ValueError, match="stale browser evidence"):
        _verify_bound_visual_evidence(
            artifact=artifact,
            golden_id="candidate",
            screenshot_root=screenshot_root,
            browser_report={**browser_report, "artifactSha256": "0" * 64},
            visual_qa_evidence=binding,
        )
    with pytest.raises(ValueError, match="stale visual QA evidence"):
        _verify_bound_visual_evidence(
            artifact=artifact,
            golden_id="candidate",
            screenshot_root=screenshot_root,
            browser_report=browser_report,
            visual_qa_evidence={**binding, "artifact_sha256": "f" * 64},
        )


def test_generate_cli_enforces_two_attempt_maximum(monkeypatch):
    from scripts.generate_goldens import parse_args

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_goldens.py",
            "generate",
            "--fixture",
            "moon_phases_ar",
            "--attempt",
            "3",
        ],
    )
    with pytest.raises(SystemExit):
        parse_args()
