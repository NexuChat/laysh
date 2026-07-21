import json
import subprocess
from copy import deepcopy
from pathlib import Path

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]
MOON_MODULE = (ROOT / "tests/fixtures/moon_phase_module.js").read_text(encoding="utf-8")


def _format_with_trusted_helper(understanding: dict, values: list[float]) -> dict:
    script = """
import fs from "node:fs";
import vm from "node:vm";
const source = fs.readFileSync(process.argv[1], "utf8");
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const sandbox = { window: {} };
vm.createContext(sandbox);
new vm.Script(source).runInContext(sandbox);
const formatter = sandbox.window.LayshReadout.forLesson(payload.understanding);
process.stdout.write(JSON.stringify({
  precision: formatter.precision,
  formatted: payload.values.map((value) => formatter.format(value)),
}));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(ROOT / "sim_shell/contract.js")],
        input=json.dumps({"understanding": understanding, "values": values}),
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _thermal_understanding() -> dict:
    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["primary_parameter"] = {
        "id": "temperature",
        "label": "درجة الحرارة",
        "unit": "°C",
        "min": 20,
        "max": 200,
        "default": 20,
        "step": 1,
    }
    understanding["module_spec"] = {
        "outputs": ["length"],
        "actor": "metal_rod",
        "action": "responds",
    }
    understanding["checks"] = [
        {
            "id": "low_temperature",
            "kind": "numeric",
            "inputs": [{"name": "temperature", "value": 20}],
            "output": "length",
            "expected": 1,
            "tolerance": 1e-6,
            "unit": "m",
        },
        {
            "id": "middle_temperature",
            "kind": "numeric",
            "inputs": [{"name": "temperature", "value": 110}],
            "output": "length",
            "expected": 1.00108,
            "tolerance": 1e-6,
            "unit": "m",
        },
        {
            "id": "high_temperature",
            "kind": "numeric",
            "inputs": [{"name": "temperature", "value": 200}],
            "output": "length",
            "expected": 1.00216,
            "tolerance": 1e-6,
            "unit": "m",
        },
    ]
    return understanding


def test_trusted_readout_precision_distinguishes_thermal_expansion_endpoints():
    result = _format_with_trusted_helper(_thermal_understanding(), [1, 1.00216])

    assert result == {"precision": 3, "formatted": ["1.000", "1.002"]}


def test_verification_rejects_outputs_that_remain_dead_at_the_precision_cap():
    from server.verify import verify_candidate

    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["checks"][0]["expected"] = 1
    understanding["checks"][0]["tolerance"] = 1e-12
    understanding["checks"][1]["inputs"][0]["value"] = 180
    understanding["checks"][1]["expected"] = 1.00000000005
    understanding["checks"][1]["tolerance"] = 1e-12
    understanding["checks"][2]["inputs"][0]["value"] = 360
    understanding["checks"][2]["expected"] = 1.0000000001
    understanding["checks"][2]["tolerance"] = 1e-12
    source = MOON_MODULE.replace(
        "lit_fraction: (1 - Math.cos((angle * Math.PI) / 180)) / 2,",
        "lit_fraction: 1 + angle / 3600000000000,",
    )
    result = verify_candidate(
        {**VALID_MODULE_OUTPUT, "module_js": source},
        understanding,
    )

    failure = next(item for item in result.failures if item["gate"] == "readout_visibility")
    assert result.passed is False
    assert failure["code"] == "formatted_endpoints_indistinguishable"
    assert failure["parameter"] == "angle_deg"
    assert failure["actual"] == {
        "minimum_input": 0,
        "maximum_input": 360,
        "minimum_formatted": "1.00000000",
        "maximum_formatted": "1.00000000",
    }
    assert "angle_deg" in failure["message"]
    assert failure["message"].count('"1.00000000"') == 2


def test_shell_uses_the_shared_readout_formatter_without_changing_unit_suffixes():
    shell_js = (ROOT / "sim_shell/shell.js").read_text(encoding="utf-8")

    assert "window.LayshReadout.forLesson(lesson)" in shell_js
    assert "readout.format(observed)" in shell_js
    assert "Number(observed).toFixed(2)" not in shell_js
    assert "${parameter.unit}" in shell_js


def test_generation_prompt_requires_a_visible_factor_for_amplified_geometry():
    from server.codex_backend import CodexBackend

    prompt = CodexBackend._render_prompt("generate_module.md", _thermal_understanding())
    qa_prompt = CodexBackend._render_prompt("qa.md", {"module_source": "amplified geometry"})
    normalized_prompt = " ".join(prompt.split())
    normalized_qa_prompt = " ".join(qa_prompt.split())

    assert "If geometry is amplified" in normalized_prompt
    assert "label its numeric factor" in normalized_prompt
    assert "on-canvas" in normalized_prompt
    assert "never distort silently" in normalized_prompt
    assert "Reject amplified geometry" in normalized_qa_prompt
    assert "on-canvas label states its numeric factor" in normalized_qa_prompt
    assert "silent visual distortion cannot be approved" in normalized_qa_prompt
