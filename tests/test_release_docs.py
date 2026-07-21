from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAN_CHECKOUT = ROOT / "docs" / "CLEAN_CHECKOUT.md"
OWNER_CHECKLIST = ROOT / "docs" / "submission" / "owner-checklist.md"
RELEASE_DOCS = (CLEAN_CHECKOUT, OWNER_CHECKLIST)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_docs_describe_v11_without_the_rejected_v100_release() -> None:
    for path in RELEASE_DOCS:
        document = _read(path)
        assert "v1.0.0" not in document, path
        assert "v1.1" in document, path


def test_clean_checkout_verifies_an_exact_commit_without_requiring_a_tag() -> None:
    document = _read(CLEAN_CHECKOUT)
    assert "<FINAL-RELEASE-COMMIT>" in document
    assert "git checkout --detach <FINAL-RELEASE-COMMIT>" in document
    assert re.search(r"git\s+(?:checkout|switch)\s+v\d", document) is None


def test_clean_checkout_does_not_install_empty_javascript_dependencies() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package.get("dependencies", {}) == {}
    assert package.get("devDependencies", {}) == {}

    document = _read(CLEAN_CHECKOUT)
    assert re.search(r"\bnpm\s+(?:install|i|ci)\b", document) is None
    assert "zero JavaScript dependencies" in document


def test_release_actions_remain_explicitly_owner_only_and_unchecked() -> None:
    document = _read(OWNER_CHECKLIST)
    assert "owner-only" in document.casefold()
    assert "explicit owner approval" in document.casefold()
    assert re.search(r"^- \[ \].*\btag\b", document, re.IGNORECASE | re.MULTILINE)
    assert re.search(r"^- \[ \].*\bpush\b", document, re.IGNORECASE | re.MULTILINE)
    assert re.search(r"^- \[ \].*\bsubmit\b", document, re.IGNORECASE | re.MULTILINE)
    assert re.search(r"^- \[[xX]\]", document, re.MULTILINE) is None


def test_release_docs_disclose_share_retention_and_expiry() -> None:
    for path in RELEASE_DOCS:
        document = _read(path)
        assert re.search(r"\b30[- ]day\b", document, re.IGNORECASE), path
        assert re.search(r"\bexpir(?:e|es|ed|y)\b", document, re.IGNORECASE), path
