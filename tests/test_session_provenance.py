from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from server.session_provenance import (
    CommitRecord,
    ProvenanceError,
    validate_history,
    verify_repository,
)

ROOT = Path(__file__).parents[1]
SESSION_ID = "019f7998-9378-72b2-b590-ee10e632ce81"


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "representative_session_id": SESSION_ID,
        "accepted_g7": {"commit": "b" * 40, "commit_count": 2},
        "attested_through": "c" * 40,
        "attested_continuation": [
            {
                "commit": "c" * 40,
                "subject": "feat: root work",
                "classification": "root_session_implementation",
            }
        ],
        "future_commit_policy": {
            "required_trailer": "Laysh-Session",
            "forbidden_trailers": ["Co-authored-by", "Delegated-Agent"],
        },
    }


def _linear_history(*, future_message: str | None = None) -> list[CommitRecord]:
    commits = [
        CommitRecord("a" * 40, (), "chore: root"),
        CommitRecord("b" * 40, ("a" * 40,), "test: accepted boundary"),
        CommitRecord("c" * 40, ("b" * 40,), "feat: root work"),
    ]
    if future_message is not None:
        commits.append(CommitRecord("d" * 40, ("c" * 40,), future_message))
    return commits


def test_root_session_manifest_matches_the_current_linear_history():
    manifest_path = (
        ROOT
        / "docs"
        / "build-spec"
        / "g7-continuation"
        / "SESSION-PROVENANCE.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    package_commit = manifest["attested_continuation"][0]

    report = verify_repository(ROOT, manifest=manifest)

    assert report["passed"] is True
    assert report["representative_session_id"] == SESSION_ID
    assert report["merge_commit_count"] == 0
    assert report["root_commit_count"] == 1
    assert report["unlinked_commit_count"] == 0
    assert package_commit["classification"] == "root_session_documentation"
    assert (
        "docs/build-spec/g7-continuation/BUILD-NOTEBOOK.md"
        not in package_commit["owner_requirement_paths"]
    )


def test_future_commit_requires_the_exact_root_session_trailer():
    report = validate_history(
        _manifest(),
        _linear_history(
            future_message=(
                "feat: linked work\n\n"
                f"Laysh-Session: {SESSION_ID}"
            )
        ),
    )

    assert report["passed"] is True
    assert report["trailer_linked_commit_count"] == 1

    with pytest.raises(ProvenanceError, match="missing_session_trailer"):
        validate_history(
            _manifest(),
            _linear_history(future_message="feat: unlinked work"),
        )

    with pytest.raises(ProvenanceError, match="wrong_session_trailer"):
        validate_history(
            _manifest(),
            _linear_history(
                future_message=(
                    "feat: foreign work\n\n"
                    "Laysh-Session: 00000000-0000-0000-0000-000000000000"
                )
            ),
        )

    with pytest.raises(ProvenanceError, match="missing_session_trailer"):
        validate_history(
            _manifest(),
            _linear_history(
                future_message=(
                    "feat: body spoof\n\n"
                    f"Laysh-Session: {SESSION_ID}\n\n"
                    "This final paragraph is not a trailer block."
                )
            ),
        )


def test_provenance_rejects_merges_and_delegated_authorship():
    merged = _linear_history(
        future_message=f"feat: merge\n\nLaysh-Session: {SESSION_ID}"
    )
    merged[-1] = CommitRecord("d" * 40, ("c" * 40, "9" * 40), merged[-1].message)
    with pytest.raises(ProvenanceError, match="non_linear_history"):
        validate_history(_manifest(), merged)

    delegated = _linear_history(
        future_message=(
            "feat: delegated work\n\n"
            f"Laysh-Session: {SESSION_ID}\n"
            "Delegated-Agent: independent-session"
        )
    )
    with pytest.raises(ProvenanceError, match="forbidden_authorship_trailer"):
        validate_history(_manifest(), delegated)


def test_attested_prefix_cannot_be_silently_changed():
    changed = _linear_history()
    changed[-1] = CommitRecord("e" * 40, ("b" * 40,), "feat: root work")
    with pytest.raises(ProvenanceError, match="attested_commit_mismatch"):
        validate_history(_manifest(), changed)

    changed_subject = deepcopy(_linear_history())
    changed_subject[-1] = CommitRecord(
        "c" * 40,
        ("b" * 40,),
        "feat: silently changed subject",
    )
    with pytest.raises(ProvenanceError, match="attested_subject_mismatch"):
        validate_history(_manifest(), changed_subject)


def test_repository_instructions_require_future_session_linkage():
    instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert f"Laysh-Session: {SESSION_ID}" in instructions
    assert "scripts/verify_session_provenance.py" in instructions
