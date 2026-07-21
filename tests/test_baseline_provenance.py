from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
RECORD_DIR = Path("docs/build-spec/g7-continuation")
BASELINE_COMMIT = "828fe4d99dfd516c3fea7a028fc6e4b306199702"
BASELINE_COMMIT_COUNT = 74
ROOT_SESSION_ID = "019f7998-9378-72b2-b590-ee10e632ce81"
BASELINE_FULL_PASSED = 193
BASELINE_LIVE_SKIPPED = 1
BASELINE_BROWSER_PASSED = 6
BASELINE_NON_BROWSER_PASSED = 187
BASELINE_DESELECTED = 7
BASELINE_COVERAGE_PERCENT = 90.01


@dataclass(frozen=True)
class BaselineRecord:
    commit: str
    commit_count: int
    session_id: str
    full_passed: int
    live_skipped: int
    browser_passed: int
    non_browser_passed: int
    deselected: int
    coverage_percent: float
    ruff_passed: bool


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"(?ms)^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)",
        text,
    )
    assert match is not None, f"missing documented section: {heading}"
    return match.group(1)


def _inline_code_after(text: str, label: str) -> str:
    _, separator, remainder = text.partition(label)
    assert separator, f"missing documented field: {label}"
    match = re.search(r"`([^`]+)`", remainder)
    assert match is not None, f"missing inline-code value after: {label}"
    return match.group(1)


def _labeled_bullets(section: str) -> dict[str, str]:
    return {
        label.strip(): value.strip().rstrip(";")
        for label, value in re.findall(
            r"(?m)^- (?:\*\*)?([^:*]+?):(?:\*\*)?\s*(.+)$",
            section,
        )
    }


def _markdown_table(section: str) -> dict[str, dict[str, str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and not all(set(cell) <= {"-", ":"} for cell in cells):
            rows.append(cells)
    assert rows, "missing documented preflight table"
    header = rows[0]
    return {row[0]: dict(zip(header[1:], row[1:], strict=True)) for row in rows[1:]}


def _passed_and_skipped(value: str) -> tuple[int, int]:
    passed = re.search(r"(\d+) passed", value)
    skipped = re.search(
        r"(\d+)(?:\s+documented\s+opt-in\s+live)?\s+skip(?:ped)?",
        value,
    )
    assert passed is not None and skipped is not None, value
    return int(passed.group(1)), int(skipped.group(1))


def _passed_deselected_coverage(value: str) -> tuple[int, int, float]:
    match = re.search(
        r"(\d+) passed, (\d+) deselected, ([0-9]+(?:\.[0-9]+)?)% total",
        value,
    )
    assert match is not None, value
    return int(match.group(1)), int(match.group(2)), float(match.group(3))


def _provenance_record(path: Path) -> BaselineRecord:
    trusted = _section(path.read_text(encoding="utf-8"), "Trusted baseline")
    bullets = _labeled_bullets(trusted)
    full_passed, live_skipped = _passed_and_skipped(bullets["full Pytest"])
    browser_passed, browser_skipped = _passed_and_skipped(
        bullets["browser marker"]
    )
    assert browser_skipped == live_skipped, "baseline skip counts disagree"
    non_browser, deselected, coverage = _passed_deselected_coverage(
        bullets["non-browser coverage"]
    )
    commit_count_match = re.search(r"baseline contains (\d+) commits", trusted)
    assert commit_count_match is not None, "missing baseline commit count"
    return BaselineRecord(
        commit=_inline_code_after(trusted, "Git commit:"),
        commit_count=int(commit_count_match.group(1)),
        session_id=_inline_code_after(trusted, "root Codex build session:"),
        full_passed=full_passed,
        live_skipped=live_skipped,
        browser_passed=browser_passed,
        non_browser_passed=non_browser,
        deselected=deselected,
        coverage_percent=coverage,
        ruff_passed=bullets["Ruff"].casefold() == "passed",
    )


def _notebook_record(path: Path) -> BaselineRecord:
    text = path.read_text(encoding="utf-8")
    identity = _labeled_bullets(_section(text, "Session identity"))
    table = _markdown_table(_section(text, "Preflight record"))
    offline_passed = int(
        re.search(r"(\d+) passed", table["Offline unit/integration"]["Result"])[1]
    )
    browser_passed, live_skipped = _passed_and_skipped(
        table["Browser/a11y"]["Result"]
    )
    non_browser, deselected, coverage = _passed_deselected_coverage(
        table["Non-browser coverage"]["Result"]
    )
    return BaselineRecord(
        commit=identity["Starting commit"].strip("`"),
        commit_count=int(identity["Starting history count"]),
        session_id=identity["Representative root session"].strip("`"),
        full_passed=offline_passed + browser_passed,
        live_skipped=live_skipped,
        browser_passed=browser_passed,
        non_browser_passed=non_browser,
        deselected=deselected,
        coverage_percent=coverage,
        ruff_passed=table["Ruff"]["Result"].casefold() == "all checks passed",
    )


def _manifest_identity(path: Path) -> tuple[str, int, str]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    accepted = manifest["accepted_g7"]
    return (
        accepted["commit"],
        accepted["commit_count"],
        manifest["representative_session_id"],
    )


def _assert_locked_baseline(root: Path) -> None:
    record_dir = root / RECORD_DIR
    provenance = _provenance_record(record_dir / "PROVENANCE.md")
    notebook = _notebook_record(record_dir / "BUILD-NOTEBOOK.md")
    manifest_identity = _manifest_identity(record_dir / "SESSION-PROVENANCE.json")
    expected = BaselineRecord(
        commit=BASELINE_COMMIT,
        commit_count=BASELINE_COMMIT_COUNT,
        session_id=ROOT_SESSION_ID,
        full_passed=BASELINE_FULL_PASSED,
        live_skipped=BASELINE_LIVE_SKIPPED,
        browser_passed=BASELINE_BROWSER_PASSED,
        non_browser_passed=BASELINE_NON_BROWSER_PASSED,
        deselected=BASELINE_DESELECTED,
        coverage_percent=BASELINE_COVERAGE_PERCENT,
        ruff_passed=True,
    )
    assert provenance == notebook, "baseline records disagree"
    assert provenance == expected, "PROVENANCE.md baseline contract drifted"
    assert manifest_identity == (
        expected.commit,
        expected.commit_count,
        expected.session_id,
    ), "SESSION-PROVENANCE.json baseline identity drifted"


def test_locked_baseline_identity_counts_and_coverage_agree():
    _assert_locked_baseline(ROOT)


@pytest.mark.parametrize(
    ("relative_path", "old", "new"),
    [
        (
            "SESSION-PROVENANCE.json",
            BASELINE_COMMIT,
            "0" * 40,
        ),
        ("SESSION-PROVENANCE.json", '"commit_count": 74', '"commit_count": 75'),
        ("BUILD-NOTEBOOK.md", "90.01% total coverage", "89.99% total coverage"),
        ("PROVENANCE.md", "90.01% total", "89.99% total"),
    ],
)
def test_locked_baseline_rejects_mutated_record(
    tmp_path: Path,
    relative_path: str,
    old: str,
    new: str,
):
    target = tmp_path / RECORD_DIR
    shutil.copytree(ROOT / RECORD_DIR, target)
    record = target / relative_path
    text = record.read_text(encoding="utf-8")
    assert old in text
    record.write_text(text.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(
        AssertionError,
        match=r"baseline (?:records disagree|identity drifted)",
    ):
        _assert_locked_baseline(tmp_path)


def test_locked_baseline_rejects_matching_coverage_drift_in_both_records(
    tmp_path: Path,
):
    target = tmp_path / RECORD_DIR
    shutil.copytree(ROOT / RECORD_DIR, target)
    for relative_path, old, new in (
        ("BUILD-NOTEBOOK.md", "90.01% total coverage", "89.99% total coverage"),
        ("PROVENANCE.md", "90.01% total", "89.99% total"),
    ):
        record = target / relative_path
        text = record.read_text(encoding="utf-8")
        assert old in text
        record.write_text(text.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(AssertionError, match="baseline contract drifted"):
        _assert_locked_baseline(tmp_path)
