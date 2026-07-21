from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from tests.golden_cases import VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    ("language", "correction"),
    [
        ("ar", "تصحيح: أطوار القمر تنتج من زاوية الشمس والأرض والقمر، لا من ظل الأرض."),
        ("en", "Correction: Moon phases come from the Sun-Earth-Moon angle, not Earth's shadow."),
    ],
)
def test_misconceptions_require_an_explicit_localized_correction(language, correction):
    from server.schemas import ContractError, validate_understanding

    corrected = deepcopy(VALID_UNDERSTANDING)
    corrected["lang"] = language
    corrected["misconception"] = correction
    assert validate_understanding(corrected)["misconception"] == correction

    uncorrected = deepcopy(corrected)
    uncorrected["misconception"] = (
        "ظل الأرض هو سبب أطوار القمر" if language == "ar" else "Earth's shadow causes phases."
    )
    with pytest.raises(ContractError, match="explicit correction"):
        validate_understanding(uncorrected)


def test_trusted_shell_labels_misconceptions_and_never_locks_the_primary_control():
    shell = (ROOT / "sim_shell/shell.html").read_text(encoding="utf-8")
    script = (ROOT / "sim_shell/shell.js").read_text(encoding="utf-8")

    assert 'id="primary-control" type="range"' in shell
    assert 'id="primary-control" type="range" disabled' not in shell
    assert 'id="misconception-label"' in shell
    assert 'role="note"' in shell
    assert "control.disabled" not in script
    assert "فكرة شائعة تحتاج إلى تصحيح" in script
    assert "Common misconception" in script


def test_curated_review_rejects_an_uncorrected_misconception():
    from server.goldens import review_golden_candidate

    uncorrected = deepcopy(VALID_UNDERSTANDING)
    uncorrected["misconception"] = "ظل الأرض هو سبب أطوار القمر"
    review = review_golden_candidate(
        fixture=json.loads((ROOT / "server/fixtures/moon_phases_ar.json").read_text("utf-8")),
        understanding=uncorrected,
        module_output={
            "module_js": (ROOT / "tests/fixtures/moon_phase_module.js").read_text("utf-8"),
            "output_names": ["lit_fraction"],
            "brief_summary": "fixture",
            "assumptions": [],
        },
    )

    assert review["checks"]["misconception_explicitly_corrected"] is False
    assert "misconception_not_corrected" in review["failure_codes"]


def _passing_browser(_artifact):
    from server.browser_verify import BrowserVerificationResult

    return BrowserVerificationResult.passing()


def test_legacy_pinned_goldens_cannot_refresh_without_shared_scene_evidence(
    tmp_path, monkeypatch
):
    import server.codex_backend
    from server.goldens import refresh_pinned_golden_teaching_shells

    monkeypatch.setattr(
        server.codex_backend.CodexBackend,
        "__init__",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("model call is forbidden")),
    )
    source_root = ROOT / "out/cache/golden"
    golden_root = tmp_path / "golden"
    shutil.copytree(source_root, golden_root)
    before = {path.name: path.read_bytes() for path in golden_root.glob("*.json")}

    with pytest.raises(ValueError, match="deterministic refresh verification"):
        refresh_pinned_golden_teaching_shells(
            root=golden_root, browser_verifier=_passing_browser
        )

    assert {path.name: path.read_bytes() for path in golden_root.glob("*.json")} == before


def test_pinned_golden_refresh_stops_before_browser_when_scene_evidence_is_missing(
    tmp_path,
):
    from server.goldens import refresh_pinned_golden_teaching_shells

    golden_root = tmp_path / "golden"
    shutil.copytree(ROOT / "out/cache/golden", golden_root)
    before = {path.name: path.read_bytes() for path in golden_root.glob("*.json")}
    calls = 0

    def recording_browser(_artifact):
        nonlocal calls
        calls += 1
        return _passing_browser(_artifact)

    with pytest.raises(ValueError, match="deterministic refresh verification"):
        refresh_pinned_golden_teaching_shells(
            root=golden_root, browser_verifier=recording_browser
        )

    assert calls == 0
    assert {path.name: path.read_bytes() for path in golden_root.glob("*.json")} == before
