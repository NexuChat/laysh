# Provenance and continuation boundary

## Package authority

This package is an owner-authorized set of external continuation requirements.
It was prepared outside `/home/dev/laysh` after restoring the trusted baseline.
Its audit observations may be used to write new failing tests, but it contains
no later source code, diff, patch, or implementation transcript.

## Trusted baseline

The continuation starts from Git commit:

`828fe4d99dfd516c3fea7a028fc6e4b306199702`

That commit is the G7 close-out produced in the root Codex build session:

`019f7998-9378-72b2-b590-ee10e632ce81`

The baseline contains 74 commits ending with
`test: close G7 with public runtime evidence`. Before continuation, the build
session must verify that `HEAD` equals the exact commit above and that the
working tree is clean.

The accepted baseline verification on 2026-07-20 was:

- full Pytest: 193 passed, 1 documented opt-in live skip;
- Ruff: passed;
- browser marker: 6 passed, 1 documented opt-in live skip; and
- non-browser coverage: 187 passed, 7 deselected, 90.01% total.

These are starting observations, not permission to freeze test totals. New
tests must increase the applicable totals, no new unexplained skip is allowed,
and final coverage must remain at least 80% with any material drop from 90.01%
explained in the build notebook.

## Implementation boundary

All work described by this package must be implemented again from requirements
and failing tests in the root session. The session must not:

- inspect or copy code from archived repository snapshots;
- inspect later commits, patches, diffs, reflogs, or implementation transcripts;
- cherry-pick or replay later commits;
- attribute unverified work to the root session; or
- rewrite Git history with amend, rebase, reset, or filter operations.

Existing third-party dependencies remain governed by their licenses. The
pre-existing Fahim proof-of-concept boundary already documented in the G7
baseline remains unchanged and must not be obscured.

## Session continuity

The preferred path is `codex exec resume` or `codex resume` using the root
Session ID. A fork is allowed only for a narrowly scoped task that the owner
explicitly authorizes. Every fork must record its parent ID, model, task,
commits, and verification evidence.

Changing between GPT-5.6 Sol, Terra, and Luna does not require a new thread.
Model changes must be recorded in the build notebook with a reason.

## Append-only root-session enforcement

`SESSION-PROVENANCE.json` attests the accepted 74-commit G7 boundary and the
exact continuation prefix through MOTION-04. This is an append-only record: it
does not amend, rebase, or otherwise rewrite an earlier commit.

Every later commit must end with the exact trailer
`Laysh-Session: 019f7998-9378-72b2-b590-ee10e632ce81`. The repository verifier
rejects a second root, a merge, a changed attested hash or subject, a missing or
different session trailer, and delegated/co-author trailers. Run
`python scripts/verify_session_provenance.py` before committing.

The copied build-pack paths are identified separately as owner-authored
requirements inside the root-session documentation commit; they are not
misrepresented as Codex-authored implementation. GPT-5.6 runtime thread IDs in
curated evidence remain subordinate model-call receipts and carry no
implementation authority.
