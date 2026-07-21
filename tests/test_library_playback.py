from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_trusted_shell_exposes_bilingual_playback_controls_and_state():
    shell = (ROOT / "sim_shell" / "shell.html").read_text(encoding="utf-8")
    source = (ROOT / "sim_shell" / "shell.js").read_text(encoding="utf-8")

    assert 'id="play-pause"' in shell
    assert 'id="playback-status"' in shell
    assert 'aria-live="polite"' in shell
    for copy in ("إيقاف الحركة", "استئناف الحركة", "Pause motion", "Resume motion"):
        assert copy in source
    assert 'dataset.playbackState' in source
    assert 'dataset.reducedMotion' in source


def test_trusted_shell_yields_autoplay_to_direct_control_and_resets_deterministically():
    source = (ROOT / "sim_shell" / "shell.js").read_text(encoding="utf-8")

    assert 'pausePlayback("user-control")' in source
    assert 'resetSimulation()' in source
    assert 'cancelAnimationFrame(idleFrameId)' in source
    assert 'simulation.destroy()' in source
    assert "index < 32" not in source
    assert 'if (reducedMotion) pausePlayback("reduced-motion")' in source


def test_trusted_shell_uses_a_generic_periodic_motion_cadence():
    source = (ROOT / "sim_shell" / "shell.js").read_text(encoding="utf-8")

    assert "pendulum" not in source.casefold()
    assert "model.period_s" not in source
    assert "lesson.module_spec.outputs.find" in source


def test_six_library_shells_reassemble_deterministically_without_model_calls(monkeypatch):
    import server.codex_backend
    from server.assemble import assemble_artifact
    from server.goldens import _artifact_lesson_and_module, list_pinned_goldens

    monkeypatch.setattr(
        server.codex_backend.CodexBackend,
        "__init__",
        lambda *_args, **_kwargs: pytest.fail("LIB-01 must not call a model"),
    )
    first: dict[str, str] = {}
    second: dict[str, str] = {}
    for document in list_pinned_goldens():
        lesson, module_js = _artifact_lesson_and_module(document["artifact"])
        module_output = {
            "module_js": module_js,
            "output_names": lesson["module_spec"]["outputs"],
            "brief_summary": "offline LIB-01 trusted-shell probe",
            "assumptions": document["review"]["reference_contract"]["assumptions"],
        }
        first[document["golden_id"]] = assemble_artifact(lesson, module_output)
        second[document["golden_id"]] = assemble_artifact(lesson, module_output)

    assert len(first) == 6
    assert first == second
    assert all('id="play-pause"' in artifact for artifact in first.values())
