# Laysh post-G7 continuation brief

## Goal

Preserve the accepted G7 engine and night-observatory product while correcting
the remaining learner-facing, physics-motion, localization, sharing, and public
runtime reliability gaps. Changes must be incremental, test-driven, and small
enough to review independently.

## Non-negotiable invariants

- Keep the trusted shell, CSP, sandbox, zero-echo, verified-only cache, bounded
  heal, answer-first, and honest verification-tier contracts intact.
- Keep public learner input ephemeral and never persist raw questions.
- Preserve a useful answer when generation, verification, QA, persistence, or
  browser assembly fails.
- Never label an artifact verified unless every applicable deterministic and
  browser gate passes.
- Keep one authoritative generated-source limit of 96 KiB measured as UTF-8
  bytes. The deterministic verifier enforces the byte limit; the JSON schema,
  prompt contract, project skill, and tests must not impose a contradictory
  smaller ceiling. Cover ASCII and multibyte boundaries explicitly.
- Use GPT-5.6-family models only and follow `MODEL-ROUTING.md`.
- Do not add BYOK, public free-form model IDs, full declarative-v2 runtime, or
  unrelated product features in this continuation.

## Batch A — teaching clarity and learner control

### A1. Correct misconception presentation

- Render an explicit localized “common misconception” label and warning icon.
- Every misconception string must contain an explicit correction; a false
  statement may never stand alone as learner-facing copy.
- Validate Arabic and English correction shapes deterministically.
- Correct the six pinned lessons and test the rendered result.

### A2. Prediction is an invitation, not a lock

- The primary simulation control remains usable before a prediction.
- Preserve the predict → observe → explain teaching sequence as guidance.
- Selecting a prediction may add contextual feedback but must not unlock basic
  operation or reveal a score before observation.
- Keyboard, screen-reader, reduced-motion, and mobile behavior must remain
  correct.

## Batch B — physical motion and single-source visuals

### B1. Actor and action contract

Every simulation declares one visible primary actor and one action from a
closed allowlist:

`rotates`, `oscillates`, `orbits`, `propagates`, `flows`, `floats_sinks`,
`phases`.

The declared action must be concept-relevant rather than decorative.

### B2. Deterministic actor-motion gate

- Track the declared actor, not the entire canvas, across time and parameter
  changes.
- Reject background-only sparkle, glow, or particle movement as proof of the
  scientific action.
- For oscillation, confirm sign reversal and a period consistent with the
  model within declared tolerance.
- For rotation/orbit, confirm the actor or its surface markers move with the
  declared angle.
- For propagation/flow, confirm concept-relevant phase or particle movement.
- Respect reduced motion while keeping an equivalent readable causal state.
- Negative fixtures must include moving backgrounds, particles outside the
  actor region, a hidden or off-canvas actor, and frame counters that advance
  without concept-relevant actor change.
- The browser probe must exercise the primary control before any prediction and
  sample enough timepoints to distinguish a trajectory from a single changed
  frame.

The six pinned lessons have these minimum concept-relevant proofs:

| Lesson | Primary actor/action proof |
|---|---|
| Moon phases | Moon illumination geometry changes with orbital angle; a changing icon alone fails. |
| Pendulum | Bob reverses direction and its measured period follows the length model. |
| Day and night | Earth and a visible surface landmark rotate relative to fixed illumination. |
| Sound pitch | Wave phase propagates spatially; amplitude-only pulsing fails. |
| Simple circuit | Charge carriers flow and speed changes consistently with calculated current. |
| Buoyancy | The body moves to a physically consistent submerged or sunk equilibrium relative to the waterline. |

### B3. One source for calculation and rendering

The visual state for angle, phase, submerged fraction, flow speed, brightness,
and other pivotal properties must derive from the same model function or state
used by `test(inputs)`. Reject parallel visual calculations that can disagree
with verified outputs.

### B4. Semantic visual QA

For curated promotion only, review three bounded screenshots with
`gpt-5.6-terra` against a closed verdict schema:

`actor_visible`, `action_performed`, `physically_consistent`, `defects`.

The image review is supplemental. Deterministic and browser gates still decide
whether an artifact can be cached or labeled verified.

### B5. Professional rendering and temporal quality

- Preserve the accepted night-observatory design system; do not redesign the
  product merely to demonstrate a skill.
- Render at the effective device-pixel ratio so actors, curves, labels, units,
  and surface markers remain crisp without clipping at every accepted viewport.
- Maintain a clear visual hierarchy: the scientific actor and causal change are
  primary; decorations, overlays, and ambient particles remain subordinate.
- Use clamped elapsed time or a fixed simulation step where physics requires
  it. A slow frame must not make the actor jump, tunnel, reverse incorrectly, or
  accumulate unbounded error.
- Every animation loop has explicit start, pause, off-screen/reduced-motion,
  destroy, and user-control behavior. It must not leak timers or continue work
  after teardown.
- Validate a temporal sequence, not one attractive screenshot: initial state,
  mid-action, parameter change, and returned/reset state must form one coherent
  physical story.
- Keep the existing measured cadence when sufficient; increase it only from a
  browser measurement that proves smoother motion without violating latency,
  CPU, accessibility, or battery constraints.

## Batch C — sharing, library, localization, and presentation

### C1. Safe generated-experience sharing

- Provide a stable share URL for an eligible completed artifact.
- Never encode the raw learner question, credentials, or private runtime ID in
  the URL.
- A verified share resolves after an application-process restart for the
  documented release retention window. The public identifier is opaque or
  content-addressed, lookup rejects traversal or tampering, and only the
  already-verified portable artifact is served under the existing CSP.
- Document retention and expiration behavior. Expired or withdrawn links must
  fail closed without revealing whether a learner question once existed.
- Copy action must have localized success/failure feedback and keyboard access.
- Missing, expired, or invalid artifacts degrade to a safe gallery path.

### C2. Self-playing verified library

- Pinned lessons can demonstrate their concept without forcing prediction or
  slider interaction.
- Self-play motion is derived from the physical model and yields to direct user
  input.
- Provide pause/resume/reset controls and honor reduced motion.
- Revalidate all six pinned artifacts before promotion.

### C3. Complete bilingual behavior

- Arabic and English cover landing, build, result, receipt, errors, sharing,
  library, and simulation-shell controls.
- Locale switching is deterministic, persists only the locale preference, and
  never changes from clicks outside the locale control.
- Directionality, punctuation, formulas, units, and technical LTR fragments
  remain correct in both locales.

### C4. Stable presentation mechanics

- Mobile overlays must not hide the main action or trap focus.
- At 320px, 390×844, 1440×900, and 200% zoom, the actor, primary control,
  pause/resume/reset, and share action must remain reachable without an overlay
  covering the actor. Exact above-the-fold placement is not required when
  browser zoom necessarily introduces scrolling.
- Separate concept animation time from slow parameter-sweep time when the
  phenomenon itself is motion.
- Static asset references must be versioned so deployed clients do not combine
  incompatible HTML, CSS, JavaScript, or golden manifests.

## Batch D — public runtime reliability

### D1. Preserve answer-first value

Once a safe answer is emitted, every later failure path must retain it. The
result may become answer-only with retry/gallery actions, but must not collapse
to a generic error or lose the explanation.

Receipts must report the model and outcome for each executed stage. Do not
derive a single model label from the last execution, because a heal or QA model
can otherwise be misreported as the generation model.

### D2. Honest simulatable slices

Do not reinterpret malformed, partial, or contradictory stage output as a
verified simulation. Preserve valid safe fields, reject invalid simulation
contracts, and degrade to answer-only when an honest module cannot be formed.

### D3. First-draft generation reliability

Improve prompts or contracts only in response to a captured failing fixture.
Add the regression test first. Keep the module surface restricted and avoid
prompt growth that merely repeats trusted-shell responsibilities.

### D4. Experimental model-derived artifacts

Any declarative or model-derived path remains explicitly experimental until it
passes the same contracts, physics fixtures, actor-motion, browser, download,
accessibility, and cache-promotion gates as the existing path. Experimental
work cannot delay or weaken the stable submission path.

## Delivery order

1. Baseline verification and package copy.
   Reconcile the local `sim-quality` project skill with the accepted prediction,
   source-limit, actor/action, and reduced-motion contracts before using it.
2. Batch A with failing tests, implementation, full affected suites, commit.
3. Batch B with fixtures and actor tracking before any golden regeneration.
4. Batch C with unit/integration/browser/accessibility coverage.
5. Batch D with captured failure fixtures and public-path smoke only after all
   offline gates pass.
6. Revalidate six goldens, run the complete release verification, and update
   evidence.

No batch proceeds while its acceptance rows are failing.
