# G7 continuation build notebook

## Session identity

- **Representative root session:** `019f7998-9378-72b2-b590-ee10e632ce81`
- **Parent session:** none; this is the original root continuation.
- **Builder model / effort:** `gpt-5.6-terra` / `high` (launcher-profile verified).
- **Started (UTC):** `2026-07-20T21:57:44Z`
- **Starting commit:** `828fe4d99dfd516c3fea7a028fc6e4b306199702`
- **Starting history count:** 74
- **Branch:** `main`

## Preflight record

The repository identity, clean worktree, and expected 74-commit G7 boundary were
confirmed before this notebook was created. The effective Laysh launcher profile
reported `gpt-5.6-terra`, high reasoning, and the approved local skill/MCP
surface. No unavailable integration or delegated agent was used.

| Check | Command | Result |
| --- | --- | --- |
| Offline unit/integration | `.venv/bin/pytest -q -m 'not browser and not live'` | 187 passed, 7 deselected, 3.88s |
| Non-browser coverage | `.venv/bin/coverage run -m pytest -q -m 'not browser and not live' && .venv/bin/coverage report` | 187 passed, 7 deselected, 90.01% total coverage |
| Ruff | `.venv/bin/ruff check .` | all checks passed |
| Browser/a11y | `.venv/bin/pytest -q -m browser` | 6 passed, 1 skipped, 187 deselected, 80.56s |
| Package manifest | `sha256sum -c MANIFEST.sha256` | 9 required package files OK |

These results match `PROVENANCE.md`: 193 total pytest tests with the single
opt-in live skip, six browser passes plus its live skip, and coverage above the
90% floor.

## Acceptance ledger at initialization

- **Rows total:** 30
- **Passing:** BASE-01, BASE-02, TEST-01, CONTRACT-01, TEACH-01, TEACH-02
- **Failing:** none
-- **Not started:** EVID-01, EVID-02, MOTION-01, MOTION-02, MOTION-03, MOTION-04, VQA-01, VISUAL-01, SHARE-01,
  SHARE-02, LIB-01, I18N-01, I18N-02, UI-01, UI-02, ASSET-01, REL-01, REL-02,
  GEN-01, EXP-01, GOLD-01, ROUTE-01, ROUTE-02, RELEASE-01
- **Blocked:** none

## Build log

### Initialization

The authoritative continuation package was read before implementation, its
manifest was verified, and the package was copied into this directory. The
project `sim-quality` skill will be reconciled with the package before it is
invoked: its old 40 KiB source-size and prediction-gating statements are not
valid for this continuation.

### Batch A — pedagogy contracts

Completed locally; source changes and this evidence record are committed together.

- Reconciled the 96 KiB UTF-8 source limit in the schema, generation prompt,
  verifier, quality checklist, boundary tests, and frozen-contract manifest.
- Added a deterministic AR/EN misconception correction shape. The trusted shell
  now displays a localized warning-label and never disables the primary control
  before a prediction.
- Added a deterministic refresh for the six pinned artifacts. It uses only the
  allowlisted cache, fixture contracts, deterministic verification, and browser
  verification; `CodexBackend` construction is forbidden by its unit test.
  The refresh is idempotent and stages all writes until every artifact passes.
- `scripts/refresh_pinned_goldens.py` refreshed the six cached artifacts twice
  (14,967 ms and 15,446 ms, zero model calls). The final artifacts record the
  explicit-correction automated review and deterministic/browser check counts.
  See `out/evidence/batch-a-pedagogy-refresh.json`.
- Focused: 6 passed. Affected: 76 passed. Full: 206 passed, 1 skipped in
  86.49s. Non-browser coverage: 200 passed, 7 deselected, 90%. Browser/a11y:
  6 passed, 1 skipped, 200 deselected in 80.56s. Ruff: clean.

### Batch B — actor motion and visual QA

Not started.

### Batch C — sharing, library, localization, and presentation

Not started.

### Batch D — reliability, routing, and release evidence

Not started.
