import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]
FIXTURE_MODULE = ROOT / "tests" / "fixtures" / "moon_phase_module.js"


def module_output() -> dict:
    return {**VALID_MODULE_OUTPUT, "module_js": FIXTURE_MODULE.read_text(encoding="utf-8")}


def test_assembled_artifact_is_single_self_contained_document():
    from server.assemble import PORTABLE_CSP, assemble_artifact

    artifact = assemble_artifact(VALID_UNDERSTANDING, module_output())

    assert artifact.count("<!doctype html>") == 1
    assert artifact.count("window.LayshSimulation =") == 1
    assert PORTABLE_CSP in artifact
    assert "connect-src 'none'" in artifact
    assert "allow-same-origin" not in artifact
    assert "http://" not in artifact and "https://" not in artifact
    assert "@@" not in artifact
    assert "data:image/svg+xml" in artifact


def test_assembly_escapes_model_controlled_text_and_script_boundaries():
    from server.assemble import assemble_artifact

    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["title"] = "</script><img src=x onerror=alert(1)>"
    understanding["tldr"] = "<b>not markup</b>"

    artifact = assemble_artifact(understanding, module_output())

    assert "<img src=x" not in artifact
    assert "<b>not markup</b>" not in artifact
    assert "\\u003c/script\\u003e" in artifact


def test_shell_owns_bilingual_teaching_and_accessibility_states():
    shell = (ROOT / "sim_shell" / "shell.html").read_text(encoding="utf-8")
    shell_js = (ROOT / "sim_shell" / "shell.js").read_text(encoding="utf-8")

    assert 'id="prediction"' not in shell
    assert "prediction" not in shell_js.lower()
    assert 'id="primary-control"' in shell
    assert 'id="state-description"' in shell
    assert 'aria-live="polite"' in shell
    assert 'id="reset"' in shell and 'id="play-pause"' in shell
    assert '<section class="step" id="explain"' in shell
    assert 'id="explain"' in shell and 'id="explain" hidden' not in shell
    assert "prefers-reduced-motion" in shell_js
    assert "SIM_RUNTIME_ERROR" in shell_js
    assert "postMessage" in shell_js
    assert "dir === \"rtl\"" in shell_js


def test_slider_is_always_free_and_shell_owns_play_pause_and_parameter_sweep():
    shell = (ROOT / "sim_shell" / "shell.html").read_text(encoding="utf-8")
    shell_js = (ROOT / "sim_shell" / "shell.js").read_text(encoding="utf-8")
    shell_css = (ROOT / "sim_shell" / "shell.css").read_text(encoding="utf-8")

    assert '<input id="primary-control" type="range">' in shell
    assert 'id="prediction-comparison"' not in shell
    assert "control.disabled" not in shell_js
    assert "parameter.sweep_mode === \"cyclic\"" in shell_js
    assert "SWEEP_CYCLE_SECONDS" in shell_js
    assert "SWEEP_HALF_CYCLE_SECONDS" in shell_js
    assert "state.value" in shell_js
    assert "state.interacting" in shell_js
    assert 'addEventListener("pointerdown"' in shell_js
    assert 'addEventListener("pointerup"' in shell_js
    assert "إيقاف المسح التلقائي" in shell_js
    assert "متابعة المسح التلقائي" in shell_js
    assert "Pause auto-sweep" in shell_js and "Resume auto-sweep" in shell_js
    assert "prediction" not in shell_css


def test_shell_advances_phenomenon_clock_independently_of_paused_sweep():
    shell_js = (ROOT / "sim_shell" / "shell.js").read_text(encoding="utf-8")

    assert "sweepPaused: reducedMotion" in shell_js
    assert "sweepElapsedTime: 0" in shell_js
    assert "phenomenonElapsedTime: 0" in shell_js
    assert "state.phenomenonElapsedTime += deltaSeconds" in shell_js
    assert "if (!state.sweepPaused && !state.interacting)" in shell_js
    assert ": state.phenomenonElapsedTime;" in shell_js
    assert (
        "function beginInteraction() {\n"
        "    state.interacting = true;\n"
        "    state.lastTimestamp = null;\n"
        "  }"
    ) in shell_js


def test_shell_uses_a_taller_mobile_canvas_and_reports_resizes_to_the_module():
    shell_js = (ROOT / "sim_shell" / "shell.js").read_text(encoding="utf-8")

    assert "MOBILE_CANVAS_BREAKPOINT = 430" in shell_js
    assert "MOBILE_CANVAS_ASPECT_RATIO = 0.76" in shell_js
    assert "DESKTOP_CANVAS_ASPECT_RATIO = 0.56" in shell_js
    assert "function responsiveCanvasSize" in shell_js
    assert "const initialSize = responsiveCanvasSize();" in shell_js
    assert "width: initialSize.width" in shell_js
    assert "height: initialSize.height" in shell_js
    assert "simulation.resize(size.width, size.height);" in shell_js


def test_shell_reports_content_height_over_the_existing_parent_channel():
    shell_js = (ROOT / "sim_shell" / "shell.js").read_text(encoding="utf-8")

    assert 'type: "content-height"' in shell_js
    assert "document.documentElement.scrollHeight" in shell_js
    assert "new ResizeObserver" in shell_js


@pytest.mark.parametrize(
    "source",
    [
        "window.LayshSimulation={}; fetch('/leak')",
        "window.LayshSimulation={}; localStorage.setItem('x','y')",
        "window.LayshSimulation={}; new Function('return 1')()",
        "<html><script>window.LayshSimulation={}</script></html>",
        "window.LayshSimulation={}; location.href='https://example.test'",
    ],
)
def test_generated_module_forbidden_capabilities_are_rejected(source):
    from server.verify import ModuleSecurityError, verify_module_source

    with pytest.raises(ModuleSecurityError):
        verify_module_source(source)


def test_script_breakout_markup_is_rejected_before_assembly():
    from server.verify import ModuleSecurityError, verify_module_source

    with pytest.raises(ModuleSecurityError):
        verify_module_source(
            "window.LayshSimulation={}; </script><script>globalThis.compromised=true</script>"
        )


def test_artifact_contract_reports_security_pedagogy_language_and_a11y_details():
    from server.verify import verify_artifact_contract

    broken = "<!doctype html><html lang=\"en\" dir=\"ltr\"><script></script></html>"
    failures, check_count = verify_artifact_contract(
        broken,
        VALID_UNDERSTANDING,
        module_output()["module_js"],
    )

    assert check_count >= 8
    by_gate = {failure["gate"]: failure for failure in failures}
    assert by_gate["assembly"]["actual"]["script_count"] == 1
    assert by_gate["security"]["expected"]["portable_csp"]
    assert by_gate["pedagogy"]["actual"]["missing_element_ids"]
    assert by_gate["language_a11y"]["expected"]["lang"] == "ar"


def test_hand_authored_module_passes_source_and_node_contract_checks():
    from server.verify import verify_module_source, verify_module_with_node

    source = FIXTURE_MODULE.read_text(encoding="utf-8")
    assert verify_module_source(source)["source_size_bytes"] < 40 * 1024
    report = verify_module_with_node(source, VALID_UNDERSTANDING)
    assert report["passed"] is True
    assert report["fixture_count"] == 3
    assert report["first_frame"] is True


@pytest.mark.browser
def test_portable_artifact_plays_from_file_without_network(tmp_path):
    from server.assemble import assemble_artifact

    artifact_path = tmp_path / "lesson.html"
    artifact_path.write_text(
        assemble_artifact(VALID_UNDERSTANDING, module_output()),
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["node", str(ROOT / "scripts" / "check_artifact.mjs"), str(artifact_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert {key: evidence[key] for key in (
        "ready", "controlChanged", "frameChanged", "runtimeError", "externalRequests"
    )} == {
        "ready": True,
        "controlChanged": True,
        "frameChanged": True,
        "runtimeError": False,
        "externalRequests": 0,
    }
    assert evidence["idleMotionSubjectChangedPixelRatio"] >= 0.01
    assert evidence["idleMotionWholeCanvasChangedPixelRatio"] >= 0.001
    assert evidence["idleMotionCaptureIntervalMs"] >= 1000
    assert evidence["autoAdvanceValueChanged"] is True
    assert evidence["sliderTrackedAnimation"] is True
    assert evidence["controlAlwaysEnabled"] is True
    assert evidence["pauseHeldValue"] is True
    assert evidence["sliderInteractionYielded"] is True
    assert evidence["reducedMotionStartedPaused"] is True
    assert evidence["reducedMotionPlayOptInWorked"] is True
    assert evidence["renderOutputSweep"]["samples"]


@pytest.mark.browser
def test_browser_control_gate_accepts_range_value_sanitized_to_step_grid(tmp_path):
    from server.assemble import assemble_artifact

    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["primary_parameter"] = {
        **understanding["primary_parameter"],
        "min": 0,
        "max": 29.53,
        "default": 0,
        "step": 0.25,
    }
    artifact_path = tmp_path / "unaligned-range.html"
    artifact_path.write_text(
        assemble_artifact(understanding, module_output()),
        encoding="utf-8",
    )

    completed = subprocess.run(
        ["node", str(ROOT / "scripts" / "check_artifact.mjs"), str(artifact_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence["controlChanged"] is True
    assert evidence["controlAlwaysEnabled"] is True
