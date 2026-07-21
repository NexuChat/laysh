from copy import deepcopy
from pathlib import Path

import pytest

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

GOOD_MODULE_OUTPUT = {
    **VALID_MODULE_OUTPUT,
    "module_js": (Path(__file__).parent / "fixtures" / "moon_phase_module.js").read_text(
        encoding="utf-8"
    ),
}


def test_interface_failure_reports_full_abi_and_exact_export_difference():
    from server.verify import PERMITTED_ABI, verify_candidate

    source = GOOD_MODULE_OUTPUT["module_js"].replace(
        "version: 1,",
        "version: 1,\n    draw() {},",
        1,
    )
    result = verify_candidate(
        {**GOOD_MODULE_OUTPUT, "module_js": source},
        VALID_UNDERSTANDING,
    )
    failure = next(item for item in result.failures if item["gate"] == "interface")

    assert failure["code"] == "exported_keys_mismatch"
    assert failure["expected"]["permitted_abi"] == list(PERMITTED_ABI)
    assert failure["actual"]["unexpected_keys"] == ["draw"]
    assert failure["actual"]["missing_keys"] == []
    assert failure["actual"]["exported_keys"] == sorted([*PERMITTED_ABI, "draw"])


def test_numeric_fixture_failure_reports_id_inputs_expected_actual_and_tolerance():
    from server.verify import verify_candidate

    source = GOOD_MODULE_OUTPUT["module_js"].replace(
        "return { lit_fraction: state.lit_fraction };",
        "return { lit_fraction: 0 };",
    )
    result = verify_candidate(
        {**GOOD_MODULE_OUTPUT, "module_js": source},
        VALID_UNDERSTANDING,
    )
    failure = next(
        item
        for item in result.failures
        if item["gate"] == "invariant" and item.get("fixture_id") == "quarter_phase"
    )

    assert failure["code"] == "numeric_fixture_mismatch"
    assert failure["inputs"] == [{"name": "angle_deg", "value": 90}]
    assert failure["expected"] == {"output": "lit_fraction", "value": 0.5, "tolerance": 0.01}
    assert failure["actual"] == {"output": "lit_fraction", "value": 0}


def test_relation_contradiction_after_passing_numeric_checks_is_suspect_fixture():
    from server.verify import verify_candidate

    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["checks"].append(
        {
            "id": "contradictory_relation",
            "kind": "relation",
            "left_inputs": [{"name": "angle_deg", "value": 90}],
            "right_inputs": [{"name": "angle_deg", "value": 45}],
            "output": "lit_fraction",
            "relation": "right_gt_left",
            "minimum_ratio": 1.5,
        }
    )

    result = verify_candidate(GOOD_MODULE_OUTPUT, understanding)
    failure = next(
        item
        for item in result.failures
        if item["fixture_id"] == "contradictory_relation"
    )

    assert failure["gate"] == "fixture_integrity"
    assert failure["code"] == "suspect_relation_fixture"
    assert failure["expected"]["relation"] == "right_gt_left"
    assert failure["actual"]["left_value"] == pytest.approx(0.5)
    assert failure["actual"]["right_value"] < failure["actual"]["left_value"]
    assert failure["numeric_cross_check"] == {
        "output": "lit_fraction",
        "passing_fixture_ids": ["new_phase", "quarter_phase", "full_phase"],
    }


def test_security_failure_names_the_forbidden_capability_without_echoing_source():
    from server.verify import verify_candidate

    source = GOOD_MODULE_OUTPUT["module_js"].replace(
        '"use strict";',
        '"use strict"; fetch("/blocked");',
    )
    result = verify_candidate(
        {**GOOD_MODULE_OUTPUT, "module_js": source},
        VALID_UNDERSTANDING,
    )
    failure = next(item for item in result.failures if item["gate"] == "security")

    assert failure["code"] == "forbidden_capability"
    assert "network_fetch" in failure["actual"]["capabilities"]
    assert "module_js" not in str(failure)
    assert "/blocked" not in str(failure)


def test_anonymous_functions_and_arrows_are_not_dynamic_code():
    from server.verify import verify_candidate

    source = GOOD_MODULE_OUTPUT["module_js"].replace(
        '"use strict";',
        '"use strict"; const add = function (a, b) { return a + b; }; '
        "const double = (value) => value * 2; void add; void double;",
    )

    result = verify_candidate(
        {**GOOD_MODULE_OUTPUT, "module_js": source},
        VALID_UNDERSTANDING,
    )

    assert result.passed is True
    assert not any(failure["gate"] == "security" for failure in result.failures)


def test_local_layout_identifiers_do_not_trigger_navigation_security():
    from server.verify import verify_candidate

    source = GOOD_MODULE_OUTPUT["module_js"].replace(
        '"use strict";',
        '"use strict"; const top = 12; const parent = { x: top }; void parent;',
    )

    result = verify_candidate(
        {**GOOD_MODULE_OUTPUT, "module_js": source},
        VALID_UNDERSTANDING,
    )

    assert result.passed is True
    assert not any(failure["gate"] == "security" for failure in result.failures)


@pytest.mark.parametrize("construct", ["top.location", "document.body", "location.href"])
def test_actual_dom_or_navigation_access_fails_security(construct):
    from server.verify import verify_candidate

    source = GOOD_MODULE_OUTPUT["module_js"].replace(
        '"use strict";',
        f'"use strict"; const forbidden = () => {construct}; void forbidden;',
    )
    result = verify_candidate(
        {**GOOD_MODULE_OUTPUT, "module_js": source},
        VALID_UNDERSTANDING,
    )
    failure = next(item for item in result.failures if item["gate"] == "security")

    assert failure["actual"] == {"capabilities": ["dom_or_navigation"]}


@pytest.mark.parametrize("construct", ["new Function('a', 'return a')", "eval('1 + 1')"])
def test_actual_dynamic_code_constructs_fail_with_exact_diagnostic(construct):
    from server.verify import verify_candidate

    source = GOOD_MODULE_OUTPUT["module_js"].replace(
        '"use strict";',
        f'"use strict"; const forbidden = () => {construct}; void forbidden;',
    )
    result = verify_candidate(
        {**GOOD_MODULE_OUTPUT, "module_js": source},
        VALID_UNDERSTANDING,
    )
    failure = next(item for item in result.failures if item["gate"] == "security")

    assert failure == {
        "gate": "security",
        "code": "forbidden_capability",
        "expected": {"forbidden_capabilities": []},
        "actual": {"capabilities": ["dynamic_code"]},
    }


def test_source_size_failure_reports_limit_and_actual_bytes():
    from server.verify import MAX_SOURCE_BYTES, verify_candidate

    source = "window.LayshSimulation = {};/*" + ("x" * MAX_SOURCE_BYTES) + "*/"
    result = verify_candidate(
        {**VALID_MODULE_OUTPUT, "module_js": source},
        VALID_UNDERSTANDING,
    )
    failure = next(item for item in result.failures if item["gate"] == "source_size")

    assert failure["expected"] == {"maximum_bytes": MAX_SOURCE_BYTES}
    assert failure["actual"]["source_size_bytes"] > MAX_SOURCE_BYTES


def test_syntax_failure_reports_vm_expectation_and_error_type():
    from server.verify import verify_candidate

    source = "window.LayshSimulation = (() => {"
    result = verify_candidate(
        {**VALID_MODULE_OUTPUT, "module_js": source},
        VALID_UNDERSTANDING,
    )
    failure = next(item for item in result.failures if item["gate"] == "syntax_runtime")

    assert failure["code"] == "module_evaluation_failed"
    assert failure["expected"] == {"evaluates_in_disposable_vm": True}
    assert failure["actual"] == {"error_type": "SyntaxError"}


def test_runtime_init_failure_reports_exact_trusted_option_names():
    from server.verify import verify_candidate

    source = GOOD_MODULE_OUTPUT["module_js"].replace(
        "({ canvas, context, width, height, emitFrame } = options);",
        'throw new TypeError("broken init");',
    )
    result = verify_candidate(
        {**GOOD_MODULE_OUTPUT, "module_js": source},
        VALID_UNDERSTANDING,
    )
    failure = next(item for item in result.failures if item["gate"] == "runtime_init")

    assert failure["code"] == "init_failed"
    assert failure["expected"]["accepts_trusted_options"] == [
        "canvas",
        "context",
        "width",
        "height",
        "locale",
        "reducedMotion",
        "emitFrame",
    ]
    assert failure["actual"] == {"error_type": "TypeError"}


def test_assembly_failure_reports_expected_shell_and_sanitized_error_type(monkeypatch):
    from server import assemble
    from server.verify import verify_candidate

    def fail_assembly(*_args, **_kwargs):
        raise ValueError("PRIVATE-ASSEMBLY-DETAIL")

    monkeypatch.setattr(assemble, "assemble_artifact", fail_assembly)
    result = verify_candidate(GOOD_MODULE_OUTPUT, VALID_UNDERSTANDING)
    failure = next(item for item in result.failures if item["gate"] == "assembly")

    assert failure["expected"] == {"trusted_shell_assembled": True}
    assert failure["actual"] == {"error_type": "ValueError"}
    assert "PRIVATE-ASSEMBLY-DETAIL" not in str(failure)


def test_valid_candidate_returns_artifact_and_no_failures():
    from server.verify import verify_candidate

    result = verify_candidate(GOOD_MODULE_OUTPUT, VALID_UNDERSTANDING)

    assert result.passed is True
    assert result.failures == []
    assert result.artifact
    assert result.check_count >= len(VALID_UNDERSTANDING["checks"])


@pytest.mark.parametrize(
    ("formula", "identifiers", "uses_ascii_hyphen_minus"),
    [
        (
            "illuminated_fraction = (1 - cos(2π * lunar_day / 29.53)) / 2",
            ["illuminated_fraction", "lunar_day"],
            True,
        ),
        (
            "period_seconds = 2π * sqrt(length_m / gravity_m_s2)",
            ["gravity_m_s2", "length_m", "period_seconds"],
            False,
        ),
    ],
)
def test_formula_presentation_gate_rejects_code_identifiers_with_exact_diagnostics(
    formula,
    identifiers,
    uses_ascii_hyphen_minus,
):
    from server.verify import verify_candidate

    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["key_formula"] = formula
    result = verify_candidate(GOOD_MODULE_OUTPUT, understanding)
    failure = next(item for item in result.failures if item["gate"] == "formula_presentation")

    assert failure["code"] == "code_identifier_in_key_formula"
    assert failure["expected"] == {
        "display_math": True,
        "code_identifiers": [],
        "minus_sign": "−",
    }
    assert failure["actual"]["code_identifiers"] == identifiers
    assert failure["actual"]["uses_ascii_hyphen_minus"] is uses_ascii_hyphen_minus


@pytest.mark.parametrize(
    "formula",
    [
        "f = (1 − cos θ) / 2",
        "T = 2π√(L/g)",
        "I = V/R",
        "Fᵦ = ρVg",
    ],
)
def test_formula_presentation_gate_accepts_short_display_math(formula):
    from server.verify import verify_candidate

    understanding = deepcopy(VALID_UNDERSTANDING)
    understanding["key_formula"] = formula
    result = verify_candidate(GOOD_MODULE_OUTPUT, understanding)

    assert not any(failure["gate"] == "formula_presentation" for failure in result.failures)
