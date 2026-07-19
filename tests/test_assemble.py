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

    assert 'id="prediction"' in shell
    assert 'id="primary-control"' in shell
    assert 'id="state-description"' in shell
    assert 'aria-live="polite"' in shell
    assert 'id="reset"' in shell and 'id="replay"' in shell
    assert "prefers-reduced-motion" in shell_js
    assert "SIM_RUNTIME_ERROR" in shell_js
    assert "postMessage" in shell_js
    assert "dir === \"rtl\"" in shell_js


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
    assert report["fixture_count"] == 2
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
    assert evidence == {
        "ready": True,
        "controlChanged": True,
        "frameChanged": True,
        "runtimeError": False,
        "externalRequests": 0,
    }


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
