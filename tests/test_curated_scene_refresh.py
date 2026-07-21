from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

ACTOR_ID = "tracked_actor"
ACTOR_REGION = {"x": 0.2, "y": 0.15, "width": 0.6, "height": 0.7}


def _legacy_body_source(*, contact: bool = False) -> str:
    source = (ROOT / "tests" / "fixtures" / "moon_phase_module.js").read_text(
        encoding="utf-8"
    )
    source, count = re.subn(
        r"\n    canvas\.__layshSceneGeometry = \[\{.*?\n    \}\];",
        "",
        source,
        count=1,
        flags=re.DOTALL,
    )
    assert count == 1
    if contact:
        body = """
    canvas.__layshBodyGeometry = [
      {name: "actor", shape: "circle", x: width / 2 - 20, y: height / 2,
       radius: 20, contacts: ["reference"]},
      {name: "reference", shape: "circle", x: width / 2 + 20, y: height / 2,
       radius: 20, contacts: ["actor"]},
    ];
"""
    else:
        body = """
    canvas.__layshBodyGeometry = [
      {name: "actor", shape: "circle", x: width * 0.25, y: height / 2,
       radius: 20, contacts: []},
      {name: "reference", shape: "circle", x: width * 0.75, y: height / 2,
       radius: 20, contacts: []},
    ];
"""
    return source.replace("    emitFrame();", f"{body}    emitFrame();")


def _module_output(source: str) -> dict[str, object]:
    return {
        "module_js": source,
        "output_names": ["lit_fraction"],
        "brief_summary": "fixture",
        "assumptions": ["مدار دائري مبسط"],
    }


def test_curated_body_transform_keeps_legacy_rejected_but_emits_closed_scene_contract():
    from server.curated_scene import attach_curated_scene_contract
    from server.verify import verify_candidate
    from tests.golden_cases import VALID_UNDERSTANDING

    source = _legacy_body_source()
    legacy = verify_candidate(_module_output(source), VALID_UNDERSTANDING)

    transformed_source = attach_curated_scene_contract(
        source,
        actor_id=ACTOR_ID,
        actor_region=ACTOR_REGION,
    )
    transformed = verify_candidate(_module_output(transformed_source), VALID_UNDERSTANDING)

    assert legacy.passed is False
    assert {failure["code"] for failure in legacy.failures} == {"scene_samples_missing"}
    assert transformed.passed is True
    assert transformed.artifact is not None
    assert "LAYSH_CURATED_SCENE_ADAPTER_V1" in transformed_source
    assert transformed_source.count("window.LayshSimulation =") == 1


def test_curated_body_transform_defaults_to_forbid_and_allows_only_declared_contact():
    from server.curated_scene import attach_curated_scene_contract
    from server.verify import _run_node_report
    from tests.golden_cases import VALID_UNDERSTANDING

    forbidden = _run_node_report(
        attach_curated_scene_contract(
            _legacy_body_source(),
            actor_id=ACTOR_ID,
            actor_region=ACTOR_REGION,
        ),
        VALID_UNDERSTANDING,
    )
    declared = _run_node_report(
        attach_curated_scene_contract(
            _legacy_body_source(contact=True),
            actor_id=ACTOR_ID,
            actor_region=ACTOR_REGION,
        ),
        VALID_UNDERSTANDING,
    )

    assert forbidden["passed"] is True
    relation = forbidden["scene_geometry_samples"][0]["relations"][0]
    assert relation["overlapPolicy"] == relation["contactPolicy"] == "forbid"
    assert declared["passed"] is True
    relation = declared["scene_geometry_samples"][0]["relations"][0]
    assert relation["overlapPolicy"] == relation["contactPolicy"] == "allow"


def test_curated_body_transform_fails_closed_without_body_evidence():
    from server.curated_scene import attach_curated_scene_contract

    with pytest.raises(ValueError, match="valid reviewed actor contract"):
        attach_curated_scene_contract(
            "window.LayshSimulation = {};",
            actor_id="",
            actor_region=ACTOR_REGION,
        )


def test_curated_actor_contract_emits_post_fit_geometry_without_body_metadata():
    from server.curated_scene import attach_curated_scene_contract
    from server.verify import _run_node_report
    from tests.golden_cases import VALID_UNDERSTANDING

    source = _legacy_body_source().replace("canvas.__layshBodyGeometry", "canvas.ignored")
    transformed_source = attach_curated_scene_contract(
        source,
        actor_id=ACTOR_ID,
        actor_region=ACTOR_REGION,
    )

    report = _run_node_report(transformed_source, VALID_UNDERSTANDING)

    assert report["passed"] is True
    assert report["scene_geometry_samples"]
    assert {sample["phase"] for sample in report["scene_geometry_samples"]} == {
        "post_fit"
    }
    objects = report["scene_geometry_samples"][0]["objects"]
    assert objects == [
        {
            "id": ACTOR_ID,
            "scientific": True,
            "clippingPolicy": "forbid",
            "geometry": {
                "type": "circle",
                "cx": 360,
                "cy": 200,
                "radius": 140,
            },
        }
    ]


def test_curated_pin_refresh_is_atomic_idempotent_and_model_free(tmp_path: Path):
    from server.browser_verify import BrowserVerificationResult
    from server.goldens import GOLDEN_ROOT, refresh_curated_pinned_shells

    root = tmp_path / "golden"
    shutil.copytree(GOLDEN_ROOT, root)

    first = refresh_curated_pinned_shells(
        root=root,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    first_bytes = {path.name: path.read_bytes() for path in sorted(root.glob("*.json"))}
    second = refresh_curated_pinned_shells(
        root=root,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
    )
    second_bytes = {path.name: path.read_bytes() for path in sorted(root.glob("*.json"))}

    assert first == second
    assert first["model_calls"] == 0
    assert first["golden_count"] == 6
    assert first["passed"] is True
    assert first_bytes == second_bytes
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["lessons"]) == 6
    for item in manifest["lessons"]:
        document = json.loads((root / f"{item['id']}.json").read_text(encoding="utf-8"))
        assert item["artifact_sha256"] == document["artifact_sha256"]
        assert item["artifact_sha256"] == hashlib.sha256(
            document["artifact"].encode("utf-8")
        ).hexdigest()
        assert 'id="play-pause"' in document["artifact"]
        assert "LAYSH_CURATED_SCENE_ADAPTER_V1" in document["artifact"]
    assert all(item["shared_scene_adapter"] is True for item in first["goldens"])
    assert all(item["legacy_scene_failure_only"] is False for item in first["goldens"])


def test_curated_pin_refresh_writes_nothing_when_any_browser_gate_fails(tmp_path: Path):
    from server.browser_verify import BrowserVerificationResult
    from server.goldens import GOLDEN_ROOT, refresh_curated_pinned_shells

    root = tmp_path / "golden"
    shutil.copytree(GOLDEN_ROOT, root)
    before = {path.name: path.read_bytes() for path in sorted(root.glob("*.json"))}
    calls = 0

    def browser(artifact: str) -> BrowserVerificationResult:
        nonlocal calls
        calls += 1
        if calls == 3:
            return BrowserVerificationResult(False, 1, [{"code": "fixture_failure"}], {})
        return BrowserVerificationResult.passing()

    with pytest.raises(ValueError, match="browser refresh verification"):
        refresh_curated_pinned_shells(root=root, browser_verifier=browser)

    after = {path.name: path.read_bytes() for path in sorted(root.glob("*.json"))}
    assert before == after
