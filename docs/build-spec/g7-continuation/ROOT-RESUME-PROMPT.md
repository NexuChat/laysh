# Prompt for the original root Codex session

You are continuing the original Laysh root build session. Preserve this Session
ID as the representative build thread:

`019f7998-9378-72b2-b590-ee10e632ce81`

The repository has been restored to the accepted clean G7 boundary:

`828fe4d99dfd516c3fea7a028fc6e4b306199702`

## Preflight before any write

1. Confirm `pwd` is `/home/dev/laysh`.
2. Confirm `git rev-parse HEAD` equals the exact G7 commit above.
3. Confirm `git rev-list --count HEAD` equals `74`.
4. Confirm `git status --short` is empty.
5. Confirm the invocation header reports `gpt-5.6-terra` with high reasoning.
   The header and launcher profile are authoritative; model identity is not
   expected to appear as an environment variable.
6. Run `/home/dev/laysh-briefs/verify-laysh-profile.py` and require exit zero.
   Do not use bare `codex mcp list` or `codex plugin list` for this check: those
   inspect the global installation rather than this launcher's effective
   surface. The active delegation policy forbids subagents for this continuation.
7. Run the existing baseline unit/integration, Ruff, browser/a11y, and
   non-browser coverage suites. Record exact totals, skips, coverage, and
   failures; compare them with `PROVENANCE.md`.
8. If repository identity, history, model, or capability surface does not match,
   stop without changing files.

## Authoritative continuation package

Read every file under `/home/dev/laysh-briefs/build-pack/` except
`MANIFEST.sha256` and `VALIDATION-REPORT.md` first. Verify the manifest when it
exists. Then copy the package into:

`/home/dev/laysh/docs/build-spec/g7-continuation/`

Commit the copied requirements and the initialized build notebook from this
root session before implementation.

Do not inspect archived repositories, later commits, refs outside `HEAD`,
patches, diffs, reflogs, or implementation transcripts. Reimplement the
requirements from this package and failing tests only.

## Execution policy

- Follow `CONTINUATION-BRIEF.md` and `ACCEPTANCE-MATRIX.md` in dependency order.
- Use TDD: add a focused failing test, observe the intended failure, implement
  the minimum correct change, rerun, then refactor while green.
- Use `gpt-5.6-terra` as the default build model. Follow `MODEL-ROUTING.md`; do
  not switch to Sol without a concrete recorded reason.
- Keep all work in this root thread. Do not launch unrelated agent sessions.
- Reconcile the committed `sim-quality` project skill with this package before
  invoking it; its baseline prediction and source-size statements are stale.
- Preserve all G7 security, privacy, safety, verification, cache, and honesty
  contracts.
- Make small conventional commits after passing each coherent gate.
- Never amend, rebase, reset, filter, or otherwise rewrite history.
- Do not push, submit, publish, or modify external services without owner
  authorization.
- Minimize live model spend. Offline tests must pass before every live proof.
- Continue through all 30 acceptance rows. Stop only at completion or a genuine
  blocker that cannot be resolved safely from the repository and package.

## Required final response

Report:

- commits created;
- model/effort changes and reasons;
- tests, lint, browser, accessibility, and golden totals;
- live call counts and timings;
- acceptance rows: total/passing/failing/not-started/blocked;
- evidence paths;
- deviations and owner-only actions.

Do not claim completion while any row is failing, unknown, or silently skipped.
