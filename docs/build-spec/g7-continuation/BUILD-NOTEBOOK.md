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
- **Passing:** BASE-01, BASE-02, TEST-01, CONTRACT-01, TEACH-01, TEACH-02,
  MOTION-01, MOTION-02, MOTION-03
- **Failing:** none
- **Not started:** EVID-01, EVID-02, MOTION-04, VQA-01, VISUAL-01, SHARE-01,
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

- Source commit: `1d5fa01 feat: complete Batch A pedagogy contracts`.

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

#### MOTION-01 — closed actor/action declaration

- Source commit: `672422b feat: require scientific actor actions`.
- The closed understanding contract requires one concept-relevant actor and one
  action for every simulatable lesson. The six curated fixtures and cached
  lessons declare `moon/orbits`, `floating_body/floats_sinks`,
  `pendulum_bob/oscillates`, `charge_carrier/flows`, `wavefront/propagates`,
  and `earth_landmark/rotates`.

#### MOTION-02 — actor-only temporal tracking

- Added a four-sample, actor-region browser contract. It extracts only pixels
  matching the fixture-reviewed actor color inside a normalized actor region;
  canvas-wide hashes and advancing frame counters are evidence only and cannot
  make the gate pass.
- Negative browser fixtures prove rejection for a moving background, particles
  outside the actor region, a hidden/off-canvas actor, and a moving frame
  counter with no actor change. The six pinned artifacts each pass four ordered
  control-driven samples locally.
- Profiles use four samples at 140 ms intervals. The documented color-distance
  tolerances are 28–94 RGB units, selected from the locally rendered actor
  colors rather than from a visual model.
- `scripts/verify_golden_motion.py` produced
  `out/evidence/motion-02.json`: six of six passed, 42 checks, zero model calls.
  The affected suite recorded 20 passed, zero skipped, zero failures in 56.728s;
  Ruff and `node --check scripts/check_golden.mjs` were clean.

#### MOTION-03 — action-specific physics evidence

- Added an offline browser probe that records the module's real
  `test(inputs)` output beside actor-only samples and fixed-interval temporal
  runs. Canvas hashes and frame counts remain diagnostic only; they do not
  satisfy a physics check.
- Moon phases prove the `(1 − cos θ) / 2` output, distinct orbital positions,
  and changing illuminated geometry. Day/night proves the fixed-light
  `cos θ` relation and a moving surface landmark. Buoyancy proves the
  waterline equilibrium at densities 250, 750, and 1200 kg/m³.
- Pendulum evidence uses a shell cadence derived from `period_s`, a 100 ms
  clamped idle step, and five fixed temporal states at 480 ms intervals. Its
  declared direction threshold is 0.007 normalized canvas widths and its
  independent full-cycle endpoint tolerance is 0.025; the check detects a
  reversal from signed horizontal trajectory changes, avoiding a known
  highlight-centroid offset inside the rendered bob.
- Sound evidence samples 16 narrow phase columns (minimum spatial variation
  0.025) so a propagating waveform cannot pass as a whole-wave amplitude
  pulse. Circuit evidence compares two carrier traces against `I = 6/R` with
  a declared 1.1 minimum speed ratio.
- The trusted shell and all six pinned artifacts were reassembled locally via
  `scripts/refresh_pinned_goldens.py`; no model call was made. The final
  deterministic evidence is `out/evidence/motion-03.json`: six of six
  goldens passed, 83 checks, zero model calls.
- Focused physics unit tests: 9 passed in 0.02s. The six-golden browser proof:
  1 passed in 46.12s. The affected suite (physics, actor tracking, trusted
  refresh, and min/default/max browser checks): 27 passed, zero skipped, zero
  failures in 103.269s. `.venv/bin/ruff check .`, `node --check
  scripts/check_golden.mjs`, and `node --check sim_shell/shell.js` were clean.

#### MOTION-04 — one pivotal model state

- Added a bounded static contract requiring exactly one named
  `LAYSH_SHARED_MODEL` function that returns a state object consumed by both
  `test(inputs)` and the render path. A deliberately divergent visual formula,
  a no-op shared-model call beside drift, a scalar model return, and missing
  render/test consumption all fail with machine-readable diagnostics.
- Updated all six pinned goldens through a deterministic local transformer.
  The refresh test replaces `CodexBackend` construction with a hard failure and
  proves the operation is offline and idempotent. No runtime or visual model was
  called.
- `out/evidence/motion-04.json` records six of six goldens passing, 42 checks,
  zero failures, and zero model calls. The independent MOTION-03 browser proof
  was rerun after refresh and remains six of six, 83 checks, zero model calls in
  `out/evidence/motion-03.json`.
- The generation prompt now requires the same shared-state contract while
  retaining the complete visual contract; the rendered fixture prompt is 4,783
  characters against the 4,800-character bound.
- Focused affected suite: 58 passed in 6.38s. Full suite: 238 passed and the
  single opt-in live G4 test skipped in 172.89s. Ruff, `git diff --check`, Python
  compilation, and both JavaScript syntax checks were clean.

Current acceptance ledger after MOTION-04: 10 passing, 0 failing, 20 not
started, and 0 blocked. This is not the final release query.

### EVID-01 — append-only root-session provenance

- The focused test first failed at collection because the provenance module did
  not exist. A second red case proved that merely mentioning a session ID in a
  commit body could spoof the initial parser; the corrected parser accepts the
  exact ID only in the final trailer block.
- `SESSION-PROVENANCE.json` fixes the owner-accepted 74-commit G7 boundary and
  the eight-commit root-session continuation prefix through MOTION-04. The
  copied owner requirements are identified as inputs inside the root-session
  documentation commit, not as Codex-authored implementation.
- Every future commit must carry
  `Laysh-Session: 019f7998-9378-72b2-b590-ee10e632ce81`. The verifier rejects
  multiple roots, merges, changed attested hashes or subjects, missing/wrong
  session trailers, delegated-agent trailers, and co-author trailers. Runtime
  GPT-5.6 thread IDs remain evidence receipts with no implementation authority.
- Pre-commit `scripts/verify_session_provenance.py` result at 82 commits: one
  root, zero merges, eight attested continuation commits, zero unlinked commits.
  Focused provenance tests: 5 passed. Affected tests: 13 passed in 0.11s. Full
  suite: 243 passed and the single opt-in live G4 test skipped in 172.99s. Ruff
  and `git diff --check` were clean.

Current acceptance ledger after EVID-01: 11 passing, 0 failing, 19 not started,
and 0 blocked. This is not the final release query.

### Batch C — sharing, library, localization, and presentation

Not started.

### Batch D — reliability, routing, and release evidence

Not started.
