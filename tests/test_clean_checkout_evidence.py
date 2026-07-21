from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.verify_clean_checkout import (
    ARCHIVE_PATH,
    EVIDENCE_PATH,
    JUNIT_PATH,
    CleanCheckoutError,
    capture_clean_checkout_evidence,
    validate_clean_checkout_receipt,
)


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _initialize_repository(repository: Path) -> str:
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.name", "Clean Checkout Test")
    _git(repository, "config", "user.email", "clean-checkout@example.invalid")
    tracked = {
        ".gitignore": "__pycache__/\n.pytest_cache/\n.ruff_cache/\n",
        "source.txt": "archive-only source\n",
        "scripts/freeze_static_assets.py": "raise SystemExit(0)\n",
        "scripts/check_no_example_specific_runtime.py": "raise SystemExit(0)\n",
        "tests/test_sample.py": "def test_sample():\n    assert True\n",
    }
    for relative, source in tracked.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "--quiet", "-m", "test: source snapshot")
    return _git(repository, "rev-parse", "HEAD")


def _fake_venv(root: Path) -> Path:
    venv = root / "explicit-venv"
    for name in ("python", "ruff"):
        executable = venv / "bin" / name
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    return venv


class RecordingRunner:
    def __init__(self, *, failure: str | None = None, dirty_status: bool = False):
        self.failure = failure
        self.dirty_status = dirty_status
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    def __call__(
        self,
        argv: tuple[str, ...],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, cwd))
        name = _command_name(argv)
        return_code = 9 if name == self.failure else 0
        stdout = f"{name} passed\n"
        if name == "pytest":
            junit_argument = next(
                value.removeprefix("--junitxml=")
                for value in argv
                if value.startswith("--junitxml=")
            )
            junit_path = (cwd / junit_argument).resolve()
            junit_path.parent.mkdir(parents=True, exist_ok=True)
            junit_path.write_text(
                '<testsuite tests="2" failures="0" errors="0" skipped="0">'
                '<testcase file="tests/test_sample.py" classname="tests.test_sample" '
                'name="test_first" />'
                '<testcase file="tests/test_sample.py" classname="tests.test_sample" '
                'name="test_second" />'
                "</testsuite>\n",
                encoding="utf-8",
            )
        elif name == "status":
            stdout = "?? unexpected.txt\n" if self.dirty_status else ""
        elif name == "no_example_specific_runtime":
            stdout = "[]\n"
        return subprocess.CompletedProcess(
            list(argv),
            return_code,
            stdout=stdout,
            stderr="" if return_code == 0 else f"{name} failed\n",
        )


def _command_name(argv: tuple[str, ...]) -> str:
    if "pytest" in argv:
        return "pytest"
    if argv[0].endswith("/ruff"):
        return "ruff"
    if "scripts/freeze_static_assets.py" in argv:
        return "static_assets"
    if "scripts/check_no_example_specific_runtime.py" in argv:
        return "no_example_specific_runtime"
    if argv[:2] == ("git", "status"):
        return "status"
    raise AssertionError(f"unexpected command: {argv!r}")


@pytest.fixture
def captured_receipt(tmp_path: Path) -> tuple[Path, str, dict[str, object], RecordingRunner]:
    repository = tmp_path / "repository"
    commit = _initialize_repository(repository)
    runner = RecordingRunner()
    receipt = capture_clean_checkout_evidence(
        repository_root=repository,
        commit=commit,
        venv_path=_fake_venv(tmp_path),
        runner=runner,
    )
    return repository, commit, receipt, runner


def test_capture_uses_a_real_archive_and_the_five_fixed_fail_closed_commands(
    captured_receipt: tuple[Path, str, dict[str, object], RecordingRunner],
) -> None:
    repository, commit, receipt, runner = captured_receipt

    validated = validate_clean_checkout_receipt(
        receipt,
        repository_root=repository,
        expected_commit=commit,
    )

    assert validated["passed"] is True
    assert validated["source"] == "git_archive"
    assert validated["tracked_status_clean"] is True
    assert validated["tests_passed"] == 2
    assert validated["failures"] == 0
    assert validated["model_calls"] == 0
    assert [command["name"] for command in validated["commands"]] == [
        "pytest",
        "ruff",
        "static_assets",
        "no_example_specific_runtime",
        "status",
    ]
    assert len({cwd for _, cwd in runner.calls}) == 1
    assert runner.calls[-1][0] == (
        "git",
        "status",
        "--short",
        "--untracked-files=all",
    )
    assert validated["commands"][-1]["stdout"] == ""
    assert validated["archive"]["file_count"] == 5
    assert (repository / ARCHIVE_PATH).is_file()
    assert (repository / JUNIT_PATH).is_file()
    assert json.loads((repository / EVIDENCE_PATH).read_text(encoding="utf-8")) == receipt


@pytest.mark.parametrize(
    "mutation",
    [
        lambda receipt: receipt.update({"fabricated": True}),
        lambda receipt: receipt.update({"source": "detached_git_worktree"}),
        lambda receipt: receipt.update({"source_tree_oid": "0" * 40}),
        lambda receipt: receipt["commands"][0].update({"stdout_sha256": "0" * 64}),
        lambda receipt: receipt["archive"].update({"file_count": 99}),
    ],
    ids=["unknown-field", "non-archive", "wrong-tree", "output-hash", "file-count"],
)
def test_validator_rejects_fabricated_non_archive_and_wrong_tree_receipts(
    captured_receipt: tuple[Path, str, dict[str, object], RecordingRunner],
    mutation,
) -> None:
    repository, commit, receipt, _runner = captured_receipt
    forged = copy.deepcopy(receipt)
    mutation(forged)

    with pytest.raises((CleanCheckoutError, ValueError)):
        validate_clean_checkout_receipt(
            forged,
            repository_root=repository,
            expected_commit=commit,
        )


def test_validator_regenerates_the_archive_instead_of_trusting_its_claimed_hash(
    captured_receipt: tuple[Path, str, dict[str, object], RecordingRunner],
) -> None:
    repository, commit, receipt, _runner = captured_receipt
    archive = repository / ARCHIVE_PATH
    archive.write_bytes(archive.read_bytes() + b"fabricated trailing bytes")
    forged = copy.deepcopy(receipt)
    forged["archive"]["sha256"] = __import__("hashlib").sha256(
        archive.read_bytes()
    ).hexdigest()

    with pytest.raises(CleanCheckoutError, match="archive"):
        validate_clean_checkout_receipt(
            forged,
            repository_root=repository,
            expected_commit=commit,
        )


@pytest.mark.parametrize(
    "failure",
    ["pytest", "ruff", "static_assets", "no_example_specific_runtime"],
)
def test_capture_fails_closed_when_any_gate_command_fails(
    tmp_path: Path,
    failure: str,
) -> None:
    repository = tmp_path / "repository"
    commit = _initialize_repository(repository)

    with pytest.raises(CleanCheckoutError, match=failure):
        capture_clean_checkout_evidence(
            repository_root=repository,
            commit=commit,
            venv_path=_fake_venv(tmp_path),
            runner=RecordingRunner(failure=failure),
        )

    assert not (repository / EVIDENCE_PATH).exists()


def test_capture_fails_closed_when_the_materialized_checkout_is_dirty(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    commit = _initialize_repository(repository)

    with pytest.raises(CleanCheckoutError, match="status"):
        capture_clean_checkout_evidence(
            repository_root=repository,
            commit=commit,
            venv_path=_fake_venv(tmp_path),
            runner=RecordingRunner(dirty_status=True),
        )


def test_capture_requires_an_explicit_usable_venv(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    commit = _initialize_repository(repository)

    with pytest.raises(CleanCheckoutError, match="explicit venv"):
        capture_clean_checkout_evidence(
            repository_root=repository,
            commit=commit,
            venv_path=None,
            runner=RecordingRunner(),
        )


def test_capture_rejects_a_dirty_source_instead_of_silently_archiving_head(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    commit = _initialize_repository(repository)
    (repository / "source.txt").write_text("dirty source\n", encoding="utf-8")

    with pytest.raises(CleanCheckoutError, match="source repository is not clean"):
        capture_clean_checkout_evidence(
            repository_root=repository,
            commit=commit,
            venv_path=_fake_venv(tmp_path),
            runner=RecordingRunner(),
        )


def test_capture_rejects_a_revision_name_instead_of_an_exact_commit(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _initialize_repository(repository)

    with pytest.raises(CleanCheckoutError, match="40-character"):
        capture_clean_checkout_evidence(
            repository_root=repository,
            commit="HEAD",
            venv_path=_fake_venv(tmp_path),
            runner=RecordingRunner(),
        )


def test_receipt_paths_never_embed_the_host_repository_or_venv(
    captured_receipt: tuple[Path, str, dict[str, object], RecordingRunner],
) -> None:
    repository, _commit, receipt, _runner = captured_receipt
    serialized = json.dumps(receipt, sort_keys=True)

    assert str(repository) not in serialized
    assert os.environ.get("HOME", "/home/dev") not in serialized
