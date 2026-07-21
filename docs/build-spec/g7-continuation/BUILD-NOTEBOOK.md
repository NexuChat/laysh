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

#### VQA-01 — closed curated semantic visual QA

- The first focused run failed six tests because no visual-verdict schema,
  image-capable evidence adapter, Terra route, promotion authority check, or
  model setting existed. The implemented contract is closed and requires only
  `actor_visible`, `action_performed`, `physically_consistent`, and a bounded
  `defects` list.
- Curated visual QA accepts exactly three allowlisted repository screenshots,
  keeps the prompt on stdin, and attaches images only as argument-array paths.
  Public learner jobs and non-allowlisted, missing, oversized, wrong-count, or
  wrong-type evidence are rejected before process creation.
- Added a distinct `gpt-5.6-terra` / low route because this is the bounded
  semantic screenshot review specified by `MODEL-ROUTING.md`; ordinary healed-
  module QA remains on `gpt-5.6-sol` / medium. No Sol escalation and no live
  model call occurred in VQA-01.
- Promotion recomputes authoritative deterministic verification before reading
  the model verdict. A passing visual verdict cannot override a deterministic
  or browser failure; the actual promotion-path regression test proves the
  failure stops before cache construction.
- The reconciled `sim-quality` skill already carries the 96 KiB UTF-8 limit,
  unlocked prediction control, concept actor/action, one pivotal model state,
  and reduced-motion contract, so no stale rule was invoked.
- Evidence: `out/evidence/vqa-01.json`. Focused: 7 passed. Affected: 76 passed
  in 3.39s. Full: 250 passed and the single opt-in live G4 test skipped in
  191.34s. Ruff and `git diff --check` were clean.

Current acceptance ledger after VQA-01: 12 passing, 0 failing, 18 not started,
and 0 blocked. This is not the final release query.

#### VISUAL-01 — readable small deltas and honest visual scale

- The retained package RED evidence records four baseline failures: no shared
  measurement formatter, no `readout_visibility` gate, fixed two-decimal shell
  output, and no disclosed magnification-factor policy. The package applied
  cleanly at this root-session HEAD as seven files with 288 insertions and 10
  deletions; no three-way application was needed.
- The trusted shell now selects the smallest precision from two through eight
  fractional digits that distinguishes declared extreme numeric fixtures. The
  measured thermal endpoints therefore render as `1.000` and `1.002` rather
  than the identical `1.00` and `1.00`, without changing model outputs or units.
- Deterministic verification now emits the structured `readout_visibility` /
  `formatted_endpoints_indistinguishable` failure when both formatted extremes
  remain equal at the eight-digit cap. The report includes the parameter,
  output, inputs, and both formatted values.
- Generation requires an on-canvas numeric factor whenever geometry is
  magnified, and QA rejects undisclosed visual distortion. The previously
  inspected thermal artifact remains a regeneration/promotion concern; this
  package did not deploy or restart a service.
- Locally measured verification: focused/affected contract suite, 8 passed in
  0.22s; full suite, 254 passed and the single opt-in live G4 test skipped in
  172.77s. Ruff, `git diff --check`, and syntax checks for `contract.js`,
  `shell.js`, and `verify_module.mjs` were clean.

Current acceptance ledger after VISUAL-01: 13 passing, 0 failing, 17 not
started, and 0 blocked. This is not the final release query.

#### MOTION-03 follow-up — collision-safe Moon geometry

- The retained package RED evidence reproduces the owner-reported defect across
  the complete four-viewport, one-degree sweep: 118 rejected states, a first
  Sun–Moon overlap of 18.391 px at 320×844 (canvas 280×157, angle 0°), and a
  worst clearance of −19.025 px. This retained baseline is distinguished from
  the locally measured post-patch evidence below.
- The Moon top view now derives the orbit, Earth, Moon, Sun, clearance, and Sun
  placement from one scene scale. The scientific `moonState` relation and
  `(1 − cos θ) / 2` output remain unchanged. Rendered body geometry is exposed
  only to the trusted browser probe, whose structured diagnostics name both
  bodies, viewport, canvas size, parameter value, and measured overlap.
- The package applied cleanly as ten files with 524 insertions and 7 deletions;
  no three-way application was needed. The pinned Moon was then refreshed
  locally through deterministic and browser gates. Because this required-order
  integration follows VISUAL-01, its deterministic count is 31 rather than the
  package's independent-base count of 30; the additional check is the new
  `readout_visibility` gate. The final artifact and manifest both record SHA-256
  `140220caf395d3a76dfae77fda91f89836ea19a5e3b19d56629e001e9db34aec`.
- Locally measured `/tmp/motion-03-moon-geometry.json` evidence records all six
  goldens passing 4,415 checks with zero model calls. The Moon accounts for
  4,345 checks over 1,444 geometry samples and has a minimum clearance of
  4.725 px with no failures. Focused physics tests: 14 passed in 0.42s. Full
  suite: 259 passed and the single opt-in live test skipped in 233.26s. Ruff,
  `git diff --check`, and JavaScript syntax checks were clean.

MOTION-03 remains passing with the stronger collision invariant. The acceptance
ledger remains 13 passing, 0 failing, 17 not started, and 0 blocked; this closes
the Moon-geometry defect without double-counting an already accepted row.

### Batch C — sharing, library, localization, and presentation

Not started.

### Batch D — reliability, routing, and release evidence

Not started.
