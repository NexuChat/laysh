from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SESSION_MANIFEST = Path("docs/build-spec/g7-continuation/SESSION-PROVENANCE.json")
_HASH = re.compile(r"^[0-9a-f]{40}$")
_SESSION = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_CLASSIFICATIONS = {
    "owner_authorized_requirements",
    "root_session_documentation",
    "root_session_evidence",
    "root_session_implementation",
}


class ProvenanceError(ValueError):
    """Raised when committed history cannot satisfy the root-session policy."""


@dataclass(frozen=True)
class CommitRecord:
    commit_hash: str
    parents: tuple[str, ...]
    message: str

    @property
    def subject(self) -> str:
        return self.message.splitlines()[0] if self.message else ""


def _fail(code: str, detail: str) -> None:
    raise ProvenanceError(f"{code}: {detail}")


def _trailer_values(message: str, key: str) -> list[str]:
    pattern = re.compile(rf"^{re.escape(key)}:\s*(\S.*?)\s*$", re.MULTILINE)
    return pattern.findall(message)


def _footer_trailer_values(message: str, key: str) -> list[str]:
    stripped = message.rstrip()
    if "\n\n" not in stripped:
        return []
    footer = stripped.rsplit("\n\n", 1)[1]
    trailer_line = re.compile(r"^[A-Za-z][A-Za-z0-9-]*:\s+\S.*$")
    lines = footer.splitlines()
    if not lines or any(not trailer_line.fullmatch(line) for line in lines):
        return []
    pattern = re.compile(rf"^{re.escape(key)}:\s*(\S.*?)\s*$")
    return [match.group(1) for line in lines if (match := pattern.fullmatch(line))]


def _validate_manifest_shape(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != "1.0":
        _fail("unsupported_manifest", "schema_version must be 1.0")
    session_id = manifest.get("representative_session_id")
    if not isinstance(session_id, str) or not _SESSION.fullmatch(session_id):
        _fail("invalid_session_id", "representative_session_id must be a UUID")
    accepted = manifest.get("accepted_g7")
    if not isinstance(accepted, dict):
        _fail("invalid_manifest", "accepted_g7 must be an object")
    if not isinstance(accepted.get("commit_count"), int) or accepted["commit_count"] < 1:
        _fail("invalid_manifest", "accepted_g7.commit_count must be positive")
    if not isinstance(accepted.get("commit"), str) or not _HASH.fullmatch(
        accepted["commit"]
    ):
        _fail("invalid_manifest", "accepted_g7.commit must be a full Git hash")
    attested = manifest.get("attested_continuation")
    if not isinstance(attested, list) or not attested:
        _fail("invalid_manifest", "attested_continuation must not be empty")
    for entry in attested:
        if not isinstance(entry, dict):
            _fail("invalid_manifest", "attested continuation entries must be objects")
        if not isinstance(entry.get("commit"), str) or not _HASH.fullmatch(entry["commit"]):
            _fail("invalid_manifest", "attested commit must be a full Git hash")
        if entry.get("classification") not in _CLASSIFICATIONS:
            _fail("invalid_manifest", "unknown attested classification")
        if not isinstance(entry.get("subject"), str) or not entry["subject"]:
            _fail("invalid_manifest", "attested subject must be non-empty")
        paths = entry.get("owner_requirement_paths")
        if entry["classification"] == "owner_authorized_requirements" or paths is not None:
            if not isinstance(paths, list) or not paths or not all(
                isinstance(path, str) and path.startswith("docs/build-spec/")
                for path in paths
            ):
                _fail(
                    "invalid_manifest",
                    "owner-authorized requirements need their documentation paths",
                )
    if manifest.get("attested_through") != attested[-1]["commit"]:
        _fail("invalid_manifest", "attested_through must equal the last attested commit")
    policy = manifest.get("future_commit_policy")
    if not isinstance(policy, dict) or policy.get("required_trailer") != "Laysh-Session":
        _fail("invalid_manifest", "future commits must use the Laysh-Session trailer")
    forbidden = policy.get("forbidden_trailers")
    if not isinstance(forbidden, list) or not all(isinstance(item, str) for item in forbidden):
        _fail("invalid_manifest", "forbidden_trailers must be a string list")


def validate_history(
    manifest: dict[str, Any], commits: list[CommitRecord]
) -> dict[str, Any]:
    """Validate one HEAD ancestry against the append-only session attestation."""

    _validate_manifest_shape(manifest)
    if not commits:
        _fail("empty_history", "HEAD has no commits")

    roots = [commit for commit in commits if not commit.parents]
    merges = [commit for commit in commits if len(commit.parents) > 1]
    if len(roots) != 1 or merges:
        _fail(
            "non_linear_history",
            f"roots={len(roots)} merges={len(merges)}",
        )
    for index, commit in enumerate(commits):
        if index == 0:
            continue
        if commit.parents != (commits[index - 1].commit_hash,):
            _fail("non_linear_history", f"unexpected parent at {commit.commit_hash}")

    accepted = manifest["accepted_g7"]
    accepted_index = accepted["commit_count"] - 1
    if accepted_index >= len(commits) or commits[accepted_index].commit_hash != accepted["commit"]:
        _fail("accepted_boundary_mismatch", "G7 boundary or commit count changed")

    attested = manifest["attested_continuation"]
    start = accepted_index + 1
    end = start + len(attested)
    if end > len(commits):
        _fail("attested_commit_mismatch", "history ends before the attested prefix")
    for expected, actual in zip(attested, commits[start:end], strict=True):
        if actual.commit_hash != expected["commit"]:
            _fail(
                "attested_commit_mismatch",
                f"expected {expected['commit']} got {actual.commit_hash}",
            )
        if actual.subject != expected["subject"]:
            _fail(
                "attested_subject_mismatch",
                f"unexpected subject at {actual.commit_hash}",
            )

    policy = manifest["future_commit_policy"]
    forbidden = policy["forbidden_trailers"]
    continuation = commits[start:]
    for commit in continuation:
        for key in forbidden:
            if _trailer_values(commit.message, key):
                _fail(
                    "forbidden_authorship_trailer",
                    f"{key} present at {commit.commit_hash}",
                )

    session_id = manifest["representative_session_id"]
    future = commits[end:]
    linked = 0
    for commit in future:
        values = _footer_trailer_values(commit.message, policy["required_trailer"])
        if not values:
            _fail("missing_session_trailer", commit.commit_hash)
        if values != [session_id]:
            _fail("wrong_session_trailer", commit.commit_hash)
        linked += 1

    return {
        "schema_version": "1.0",
        "passed": True,
        "representative_session_id": session_id,
        "history_commit_count": len(commits),
        "root_commit_count": len(roots),
        "merge_commit_count": len(merges),
        "attested_commit_count": len(attested),
        "trailer_linked_commit_count": linked,
        "unlinked_commit_count": 0,
        "accepted_g7_commit": accepted["commit"],
        "attested_through": manifest["attested_through"],
    }


async def _git_log(repo_root: Path, git_executable: str) -> str:
    process = await asyncio.create_subprocess_exec(
        git_executable,
        "log",
        "--reverse",
        "--format=%H%x00%P%x00%B%x1e",
        "HEAD",
        cwd=repo_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise OSError(f"git log failed: {detail}")
    return stdout.decode("utf-8")


def _read_history(repo_root: Path) -> list[CommitRecord]:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise OSError("git executable is unavailable")
    history = asyncio.run(_git_log(repo_root, git_executable))
    commits: list[CommitRecord] = []
    for encoded in history.split("\x1e"):
        encoded = encoded.strip("\n")
        if not encoded:
            continue
        commit_hash, parent_text, message = encoded.split("\x00", 2)
        parents = tuple(parent_text.split()) if parent_text else ()
        commits.append(CommitRecord(commit_hash, parents, message.rstrip("\n")))
    return commits


def verify_repository(
    repo_root: Path, *, manifest: dict[str, Any] | None = None
) -> dict[str, Any]:
    root = repo_root.resolve()
    selected = manifest
    if selected is None:
        selected = json.loads((root / SESSION_MANIFEST).read_text(encoding="utf-8"))
    return validate_history(selected, _read_history(root))
