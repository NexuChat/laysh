import json

import pytest


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
    assert evidence["browser"]["idleMotionSubjectChangedPixelRatio"] >= 0.01
    assert evidence["browser"]["idleMotionWholeCanvasChangedPixelRatio"] >= 0.001
    assert evidence["browser"]["controlEnabledBeforePrediction"] is True
    assert evidence["cache"]["entry_count"] == 1
    assert evidence["cache"]["receipt"]["failed_gate_count"] == 0
    assert evidence["cache"]["receipt"]["browser_passed"] is True
    assert "module_js" not in json.dumps(evidence)
