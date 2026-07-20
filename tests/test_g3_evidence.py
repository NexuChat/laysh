import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.browser
@pytest.mark.asyncio
async def test_repeatable_g3_demo_proves_heal_reverify_browser_and_cache(tmp_path):
    from scripts.g3_demo import run_demo

    evidence = await run_demo(tmp_path / "cache")

    assert evidence["gate_g3_passed"] is True
    assert evidence["status"] == "complete"
    assert evidence["heal_count"] == 1
    assert evidence["verify_heal_reverify"] is True
    assert {failure["gate"] for failure in evidence["heal_received_failures"]} >= {
        "interface",
        "security",
    }
    assert {key: evidence["browser"][key] for key in (
        "ready", "controlChanged", "frameChanged", "runtimeError", "externalRequests"
    )} == {
        "ready": True,
        "controlChanged": True,
        "frameChanged": True,
        "runtimeError": False,
        "externalRequests": 0,
    }
    assert evidence["browser"]["idleMotionChangedPixelRatio"] >= 0.005
    assert evidence["browser"]["predictionHintBehavior"] is True
    assert evidence["cache"]["entry_count"] == 1
    assert evidence["cache"]["receipt"]["failed_gate_count"] == 0
    assert evidence["cache"]["receipt"]["browser_passed"] is True
    assert "module_js" not in json.dumps(evidence)


def test_frozen_contract_manifest_is_historical_and_current_contracts_are_closed():
    from scripts.freeze_contracts import build_manifest

    expected = json.loads(
        (ROOT / "out" / "evidence" / "contracts-frozen.json").read_text(encoding="utf-8")
    )

    current = build_manifest()

    # The submission evidence is intentionally immutable; source contracts may advance afterward.
    assert expected["contract_version"] == "1.0"
    assert current["contract_version"] == "1.0"
    assert set(current["files"]) == set(expected["files"])
    assert current["files"] != expected["files"]
