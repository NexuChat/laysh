#!/usr/bin/env python3
"""Produce and authenticate RELEASE evidence from an exact Git archive.

The verifier never mutates the source checkout.  It archives an explicit commit,
materializes that archive in a temporary directory, attaches a caller-selected
virtual environment, and runs a fixed offline gate list without a shell.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

EVIDENCE_PATH = "out/evidence/release-clean-checkout.json"
ARCHIVE_PATH = "out/evidence/release-clean-checkout.tar"
JUNIT_PATH = "out/evidence/release-clean-checkout.junit.xml"

_TEMP_JUNIT_ARGUMENT = "../evidence/release-clean-checkout.junit.xml"
_COMMAND_ORDER = (
    "pytest",
    "ruff",
    "static_assets",
    "no_example_specific_runtime",
    "status",
)
_EXACT_COMMANDS: dict[str, tuple[str, ...]] = {
    "pytest": (
        "../venv/bin/python",
        "-m",
        "pytest",
        "-q",
        "-m",
        "not live",
        f"--junitxml={_TEMP_JUNIT_ARGUMENT}",
    ),
    "ruff": ("../venv/bin/ruff", "check", "."),
    "static_assets": (
        "../venv/bin/python",
        "scripts/freeze_static_assets.py",
        "--check",
    ),
    "no_example_specific_runtime": (
        "../venv/bin/python",
        "scripts/check_no_example_specific_runtime.py",
        ".",
    ),
    "status": ("git", "status", "--short", "--untracked-files=all"),
}
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")


class CleanCheckoutError(ValueError):
    """A clean-checkout receipt could not be truthfully produced or verified."""


def _repository_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or path.parts[0] in {"", "."}
    ):
        raise ValueError("expected a repository-relative path")
    return value


EvidencePath = Annotated[str, AfterValidator(_repository_relative)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CommitOid = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ArchiveReceipt(_ClosedModel):
    path: Literal[ARCHIVE_PATH]
    sha256: Sha256
    commit: CommitOid
    tree_oid: CommitOid
    file_count: int = Field(ge=1)


class CommandReceipt(_ClosedModel):
    name: Literal[
        "pytest",
        "ruff",
        "static_assets",
        "no_example_specific_runtime",
        "status",
    ]
    argv: list[str] = Field(min_length=2, max_length=10)
    cwd: Literal["$CLEAN_CHECKOUT"]
    exit_code: int
    duration_seconds: float = Field(ge=0)
    stdout: str = Field(max_length=1_000_000)
    stderr: str = Field(max_length=1_000_000)
    stdout_sha256: Sha256
    stderr_sha256: Sha256

    @model_validator(mode="after")
    def authenticate_output_and_argv(self) -> CommandReceipt:
        if tuple(self.argv) != _EXACT_COMMANDS[self.name]:
            raise ValueError(f"unexpected argv for {self.name}")
        if self.stdout_sha256 != _sha256_text(self.stdout):
            raise ValueError(f"stdout digest mismatch for {self.name}")
        if self.stderr_sha256 != _sha256_text(self.stderr):
            raise ValueError(f"stderr digest mismatch for {self.name}")
        return self


class CleanCheckoutReceipt(_ClosedModel):
    schema_version: Literal["1.0"]
    gate: Literal["clean_checkout"]
    passed: bool
    tracked_status_clean: bool
    tests_passed: int = Field(ge=1)
    failures: int = Field(ge=0)
    ruff_passed: bool
    evidence_path: Literal[EVIDENCE_PATH]
    commit: CommitOid
    source: Literal["git_archive"]
    source_commit: CommitOid
    source_tree_oid: CommitOid
    source_tree_sha256: Sha256
    archive: ArchiveReceipt
    commands: list[CommandReceipt] = Field(min_length=5, max_length=5)
    junit_path: Literal[JUNIT_PATH]
    junit_sha256: Sha256
    junit_nodeids: list[str] = Field(min_length=1)
    model_calls: Literal[0]

    @model_validator(mode="after")
    def require_a_fully_passing_receipt(self) -> CleanCheckoutReceipt:
        if [command.name for command in self.commands] != list(_COMMAND_ORDER):
            raise ValueError("clean-checkout commands are not exact or ordered")
        if not self.passed or not self.tracked_status_clean or not self.ruff_passed:
            raise ValueError("clean-checkout receipt is not passing")
        if self.failures != 0 or any(command.exit_code != 0 for command in self.commands):
            raise ValueError("clean-checkout receipt contains a failed command")
        if self.commands[-1].stdout != "" or self.commands[-1].stderr != "":
            raise ValueError("clean-checkout status is not empty")
        if self.commit != self.source_commit or self.commit != self.archive.commit:
            raise ValueError("clean-checkout source commits disagree")
        if self.source_tree_oid != self.archive.tree_oid:
            raise ValueError("clean-checkout source trees disagree")
        if self.junit_nodeids != sorted(set(self.junit_nodeids)):
            raise ValueError("JUnit nodeids must be unique and sorted")
        try:
            no_example_output = json.loads(self.commands[3].stdout)
        except json.JSONDecodeError as error:
            raise ValueError("no-example gate output is not JSON") from error
        if no_example_output != []:
            raise ValueError("no-example gate reported findings")
        return self


Runner = Callable[[tuple[str, ...], Path], subprocess.CompletedProcess[str]]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _git_executable() -> str:
    executable = shutil.which("git")
    if executable is None:
        raise CleanCheckoutError("git executable is unavailable")
    return executable


def _git(
    repository: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(  # noqa: S603 - resolved Git and closed argv
        [_git_executable(), *arguments],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        raise CleanCheckoutError("git command failed while materializing archive")
    return completed


def _exact_commit_and_tree(repository: Path, commit: str) -> tuple[str, str]:
    if _HEX_40.fullmatch(commit) is None:
        raise CleanCheckoutError("commit must be an exact 40-character lowercase Git oid")
    resolved = _git(repository, "rev-parse", "--verify", f"{commit}^{{commit}}").stdout.strip()
    if resolved != commit:
        raise CleanCheckoutError("commit does not resolve to the exact requested oid")
    tree = _git(repository, "rev-parse", "--verify", f"{commit}^{{tree}}").stdout.strip()
    if _HEX_40.fullmatch(tree) is None:
        raise CleanCheckoutError("source tree oid is invalid")
    return resolved, tree


def _safe_repository_file(repository: Path, relative: str) -> Path:
    _repository_relative(relative)
    candidate = (repository / relative).resolve()
    root = repository.resolve()
    if root not in candidate.parents:
        raise CleanCheckoutError("evidence path escapes the repository")
    return candidate


def _source_is_clean(repository: Path, commit: str) -> bool:
    head = _git(repository, "rev-parse", "HEAD").stdout.strip()
    if head != commit:
        return False
    status = _git(
        repository,
        "status",
        "--short",
        "--untracked-files=all",
    )
    return status.stdout == "" and status.stderr == ""


def _inspect_archive(archive_path: Path, *, extract_to: Path | None = None) -> int:
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            members = archive.getmembers()
            unsafe = [
                member.name
                for member in members
                if not (member.isdir() or member.isfile())
                or PurePosixPath(member.name).is_absolute()
                or ".." in PurePosixPath(member.name).parts
            ]
            if unsafe:
                raise CleanCheckoutError("archive contains unsupported or unsafe entries")
            file_count = sum(member.isfile() for member in members)
            if file_count < 1:
                raise CleanCheckoutError("archive contains no tracked files")
            if extract_to is not None:
                archive.extractall(extract_to, filter="data")
            return file_count
    except (OSError, tarfile.TarError) as error:
        raise CleanCheckoutError("archive is invalid") from error


def _initialize_materialized_repository(checkout: Path, expected_tree: str) -> None:
    _git(checkout, "init", "--quiet")
    _git(checkout, "add", "-A")
    actual_tree = _git(checkout, "write-tree").stdout.strip()
    if actual_tree != expected_tree:
        raise CleanCheckoutError("materialized archive tree does not match source tree")
    _git(
        checkout,
        "-c",
        "user.name=Laysh Clean Checkout",
        "-c",
        "user.email=clean-checkout@example.invalid",
        "commit",
        "--quiet",
        "--no-gpg-sign",
        "-m",
        "clean-checkout snapshot",
    )


def _default_runner(
    argv: tuple[str, ...],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "LAYSH_ALLOW_LIVE": "0",
            "PYTHONHASHSEED": "0",
        }
    )
    return subprocess.run(  # noqa: S603,S607 - exact closed argv and attached venv
        list(argv),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def _command_receipt(
    name: str,
    checkout: Path,
    runner: Runner,
) -> dict[str, object]:
    argv = _EXACT_COMMANDS[name]
    started = time.perf_counter()
    completed = runner(argv, checkout)
    duration = time.perf_counter() - started
    stdout = completed.stdout if isinstance(completed.stdout, str) else ""
    stderr = completed.stderr if isinstance(completed.stderr, str) else ""
    receipt = {
        "name": name,
        "argv": list(argv),
        "cwd": "$CLEAN_CHECKOUT",
        "exit_code": completed.returncode,
        "duration_seconds": duration,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_sha256": _sha256_text(stdout),
        "stderr_sha256": _sha256_text(stderr),
    }
    if completed.returncode != 0:
        raise CleanCheckoutError(f"{name} command failed")
    if name == "status" and (stdout or stderr):
        raise CleanCheckoutError("status command found a dirty materialized checkout")
    return receipt


def _junit_facts(path: Path) -> tuple[int, int, int, int, list[str]]:
    try:
        root = ET.parse(path).getroot()  # noqa: S314 - local generated evidence
    except (OSError, ET.ParseError) as error:
        raise CleanCheckoutError("pytest did not produce valid JUnit evidence") from error
    suites = [root] if root.tag.rsplit("}", 1)[-1] == "testsuite" else [
        child for child in root if child.tag.rsplit("}", 1)[-1] == "testsuite"
    ]
    if not suites:
        raise CleanCheckoutError("JUnit evidence has no test suites")

    def _total(attribute: str) -> int:
        try:
            return sum(int(suite.attrib.get(attribute, "0")) for suite in suites)
        except ValueError as error:
            raise CleanCheckoutError("JUnit suite counts are invalid") from error

    tests = _total("tests")
    declared = (_total("failures"), _total("errors"), _total("skipped"))
    testcases = [
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "testcase"
    ]
    if len(testcases) != tests:
        raise CleanCheckoutError("JUnit testcase count does not match suite totals")
    actual = [0, 0, 0]
    nodeids: list[str] = []
    for testcase in testcases:
        outcomes = {
            child.tag.rsplit("}", 1)[-1]
            for child in testcase
            if child.tag.rsplit("}", 1)[-1] in {"failure", "error", "skipped"}
        }
        if len(outcomes) > 1:
            raise CleanCheckoutError("JUnit testcase has contradictory outcomes")
        actual[0] += int("failure" in outcomes)
        actual[1] += int("error" in outcomes)
        actual[2] += int("skipped" in outcomes)
        if outcomes:
            continue
        file_name = testcase.attrib.get("file")
        name = testcase.attrib.get("name")
        classname = testcase.attrib.get("classname", "")
        if not file_name or not name:
            raise CleanCheckoutError("passing JUnit testcase lacks identity")
        try:
            relative = _repository_relative(file_name)
        except ValueError as error:
            raise CleanCheckoutError("JUnit testcase path is unsafe") from error
        class_parts = classname.split(".") if classname else []
        file_parts = list(PurePosixPath(relative).with_suffix("").parts)
        suffix = (
            class_parts[len(file_parts) :]
            if class_parts[: len(file_parts)] == file_parts
            else []
        )
        nodeids.append(f"{relative}::{'::'.join([*suffix, name])}")
    if tuple(actual) != declared:
        raise CleanCheckoutError("JUnit outcomes disagree with suite totals")
    passed = tests - sum(actual)
    if passed < 1 or actual != [0, 0, 0] or len(set(nodeids)) != len(nodeids):
        raise CleanCheckoutError("clean-checkout JUnit is not fully passing and unique")
    return passed, *actual, sorted(nodeids)


def _write_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(value)
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def capture_clean_checkout_evidence(
    *,
    repository_root: Path,
    commit: str,
    venv_path: Path | None,
    runner: Runner = _default_runner,
) -> dict[str, object]:
    """Run all clean-checkout gates and atomically publish authenticated evidence."""

    repository = repository_root.resolve()
    if not repository.is_dir():
        raise CleanCheckoutError("repository root does not exist")
    exact_commit, tree_oid = _exact_commit_and_tree(repository, commit)
    if not _source_is_clean(repository, exact_commit):
        raise CleanCheckoutError("source repository is not clean at the exact commit")
    if venv_path is None:
        raise CleanCheckoutError("an explicit venv path is required")
    explicit_venv = venv_path.resolve()
    if not all(
        (explicit_venv / "bin" / executable).is_file()
        and os.access(explicit_venv / "bin" / executable, os.X_OK)
        for executable in ("python", "ruff")
    ):
        raise CleanCheckoutError("explicit venv does not provide Python and Ruff")

    with tempfile.TemporaryDirectory(prefix="laysh-clean-checkout-") as temporary:
        temporary_root = Path(temporary)
        checkout = temporary_root / "checkout"
        checkout.mkdir()
        evidence_staging = temporary_root / "evidence"
        evidence_staging.mkdir()
        (temporary_root / "venv").symlink_to(explicit_venv, target_is_directory=True)
        archive_staging = temporary_root / "source.tar"
        _git(
            repository,
            "archive",
            "--format=tar",
            f"--output={archive_staging}",
            exact_commit,
        )
        file_count = _inspect_archive(archive_staging, extract_to=checkout)
        archive_sha256 = _sha256_file(archive_staging)
        _initialize_materialized_repository(checkout, tree_oid)

        commands = [
            _command_receipt(name, checkout, runner)
            for name in _COMMAND_ORDER
        ]
        junit_staging = evidence_staging / Path(JUNIT_PATH).name
        tests_passed, failures, _errors, _skipped, nodeids = _junit_facts(junit_staging)
        if failures:
            raise CleanCheckoutError("clean-checkout JUnit contains failures")
        junit_sha256 = _sha256_file(junit_staging)
        receipt = CleanCheckoutReceipt.model_validate(
            {
                "schema_version": "1.0",
                "gate": "clean_checkout",
                "passed": True,
                "tracked_status_clean": True,
                "tests_passed": tests_passed,
                "failures": failures,
                "ruff_passed": True,
                "evidence_path": EVIDENCE_PATH,
                "commit": exact_commit,
                "source": "git_archive",
                "source_commit": exact_commit,
                "source_tree_oid": tree_oid,
                "source_tree_sha256": _sha256_text(tree_oid),
                "archive": {
                    "path": ARCHIVE_PATH,
                    "sha256": archive_sha256,
                    "commit": exact_commit,
                    "tree_oid": tree_oid,
                    "file_count": file_count,
                },
                "commands": commands,
                "junit_path": JUNIT_PATH,
                "junit_sha256": junit_sha256,
                "junit_nodeids": nodeids,
                "model_calls": 0,
            }
        ).model_dump(mode="json")

        _write_atomic(_safe_repository_file(repository, ARCHIVE_PATH), archive_staging.read_bytes())
        _write_atomic(_safe_repository_file(repository, JUNIT_PATH), junit_staging.read_bytes())
        serialized = json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        _write_atomic(_safe_repository_file(repository, EVIDENCE_PATH), serialized)
    return receipt


def validate_clean_checkout_receipt(
    document: dict[str, object],
    *,
    repository_root: Path,
    expected_commit: str,
) -> dict[str, object]:
    """Authenticate a receipt against Git, the persisted archive, and its JUnit."""

    repository = repository_root.resolve()
    exact_commit, tree_oid = _exact_commit_and_tree(repository, expected_commit)
    try:
        receipt = CleanCheckoutReceipt.model_validate(document)
    except ValidationError as error:
        raise CleanCheckoutError("clean-checkout receipt violates its closed contract") from error
    if receipt.commit != exact_commit or receipt.source_tree_oid != tree_oid:
        raise CleanCheckoutError("clean-checkout receipt targets the wrong commit or tree")
    if receipt.source_tree_sha256 != _sha256_text(tree_oid):
        raise CleanCheckoutError("clean-checkout source tree digest is invalid")

    archive_path = _safe_repository_file(repository, receipt.archive.path)
    if not archive_path.is_file() or _sha256_file(archive_path) != receipt.archive.sha256:
        raise CleanCheckoutError("clean-checkout archive digest is invalid")
    if _inspect_archive(archive_path) != receipt.archive.file_count:
        raise CleanCheckoutError("clean-checkout archive file count is invalid")
    with tempfile.TemporaryDirectory(prefix="laysh-clean-checkout-verify-") as temporary:
        regenerated = Path(temporary) / "source.tar"
        _git(
            repository,
            "archive",
            "--format=tar",
            f"--output={regenerated}",
            exact_commit,
        )
        if regenerated.read_bytes() != archive_path.read_bytes():
            raise CleanCheckoutError("clean-checkout archive does not match git archive")

    junit_path = _safe_repository_file(repository, receipt.junit_path)
    if not junit_path.is_file() or _sha256_file(junit_path) != receipt.junit_sha256:
        raise CleanCheckoutError("clean-checkout JUnit digest is invalid")
    passed, failures, errors, skipped, nodeids = _junit_facts(junit_path)
    if (
        passed != receipt.tests_passed
        or failures != receipt.failures
        or errors != 0
        or skipped != 0
        or nodeids != receipt.junit_nodeids
    ):
        raise CleanCheckoutError("clean-checkout JUnit facts do not match receipt")
    return receipt.model_dump(mode="json")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify an exact commit in a network-dead Git archive checkout."
    )
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--venv", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        receipt = capture_clean_checkout_evidence(
            repository_root=arguments.repository,
            commit=arguments.commit,
            venv_path=arguments.venv,
        )
        validate_clean_checkout_receipt(
            receipt,
            repository_root=arguments.repository,
            expected_commit=arguments.commit,
        )
    except (CleanCheckoutError, ValidationError) as error:
        print(json.dumps({"passed": False, "error": str(error)}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "passed": True,
                "commit": receipt["commit"],
                "tests_passed": receipt["tests_passed"],
                "evidence_path": EVIDENCE_PATH,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
