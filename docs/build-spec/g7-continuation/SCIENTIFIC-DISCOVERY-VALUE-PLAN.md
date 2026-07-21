# Laysh scientific-discovery value plan

- **Status:** unification foundation authorized; value journey remains gated
- **Execution session:** original root Codex session
  `019f7998-9378-72b2-b590-ee10e632ce81`
- **Plan date:** 2026-07-20
- **Project:** `/home/dev/laysh`
- **Progress ledger:** `BUILD-NOTEBOOK.md`

## 1. Purpose

Increase the real scientific, educational, and technical value of Laysh without
rebuilding the accepted engine or inflating the project with unrelated product
features.

The finished experience must demonstrate this loop:

```text
question
  -> immediate useful answer
  -> visible scientific plan
  -> optional hypothesis
  -> interactive experiment
  -> observation from the real model state
  -> causal explanation
  -> verifiable transfer challenge
  -> honest verification receipt
```

The goal is not to claim that Laysh is an "AI laboratory." The goal is to make
the running product prove that it can turn curiosity into a bounded,
scientifically checked discovery experience.

## 2. Activation gate and precedence

This plan is a sequenced extension, not permission to interrupt or weaken the
active continuation.

The owner's 2026-07-21 unified-generation directive overrides the older
activation order for one bounded foundation: inventory/ADR, shared geometry
contracts and validation, generated-path wiring, and general CI regressions may
run before the 30-row continuation closes. Canary generation, regeneration of
the six references, and V0–V6 learner-value work remain gated exactly as below.

Implementation starts only after all of the following are true:

1. All 30 rows in `ACCEPTANCE-MATRIX.md` are `passing` with their required
   evidence.
2. `RELEASE-01` passes.
3. The full test suite and Ruff pass.
4. The current Batch B/C/D work is committed coherently and the worktree is
   clean.
5. `BUILD-NOTEBOOK.md` records the real commands, results, evidence paths, and
   commits.

Reading and reviewing this plan may happen earlier. Do not change schemas,
prompts, UI behavior, or goldens for this plan while the activation gate is
closed.

Precedence remains:

1. competition rules;
2. `/home/dev/laysh-briefs/SPEC-V3.md` and its safety/privacy contracts;
3. the active G7 continuation brief and acceptance matrix;
4. this value plan.

If this plan conflicts with answer-first behavior, honest verification,
privacy, accessibility, deterministic gates, or the submission deadline, the
existing invariant wins. This plan must never delay a valid submission.

## 3. Product value contract

Laysh succeeds when a learner can:

1. receive a concise answer even if no simulation is built;
2. understand what causal relationship the experiment will test;
3. change a meaningful variable without first completing a quiz;
4. observe a concept-relevant change produced by the scientific model;
5. connect that observation to the governing relationship;
6. apply the relationship to one new, machine-checkable case; and
7. see exactly what was checked, assumed, simplified, or not verified.

This is a discovery loop, not scoring, profiling, or a claim that measured
learning gains have already been proven.

## 4. Reuse before expansion

The current understanding contract already contains much of the required
teaching structure:

- `learning_objective`;
- `key_formula`;
- `primary_parameter` and optional `secondary_parameter`;
- `prediction`;
- `misconception`;
- `explanation_prompt`;
- `transfer_prompt`;
- `module_spec.outputs`, `actor`, and `action`;
- independent numeric or relational `checks`; and
- generated-module `assumptions`.

Do not add parallel fields merely to rename these concepts. First prove whether
the learner-facing experience can be assembled from the existing closed
contract.

A schema addition is allowed only for information that cannot be derived
honestly and deterministically from existing fields. Likely bounded gaps to
evaluate are:

- a learner-facing causal question;
- held-constant labels;
- explicit model limitations;
- allowlisted reference identifiers; and
- a closed, verifiable transfer challenge rather than an ungraded free-text
  prompt.

Any accepted addition must update schema, prompt, mocks, six goldens, API/public
contract where applicable, rendering, verification, tests, and documentation
together.

## 5. Target learner journey

### 5.1 Answer first

The answer card remains the first substantive result and stays visible through
generation, verification, failure, retry, and fallback. The discovery layer
must not delay or replace it.

### 5.2 What will we discover?

For an honestly simulatable question, render a concise Arabic/English plan card
from trusted structured fields:

- concept or learning objective;
- causal question;
- primary variable the learner can change;
- observable output or outcome;
- formula/relationship when appropriate;
- important assumptions; and
- limitations when known.

The card must use learner language, not expose prompts, chain of thought, raw
questions, internal IDs, or model diagnostics.

### 5.3 Optional hypothesis

Prediction remains an invitation. The primary control works before a choice is
made. If the learner predicts, compare the choice with the observed model state
using neutral language and no score, shame, streak, or profile.

### 5.4 Observe and explain

The observation shown to the learner must be computed from the same pivotal
model state used by rendering and `test(inputs)`. Do not generate a generic
observation sentence that can disagree with the simulation.

The explanation must connect:

```text
changed input -> model relationship -> observed output -> scientific reason
```

It must identify simplifying assumptions and avoid presenting a bounded school
model as a complete description of reality.

### 5.5 Transfer challenge

After the explanation, offer one short new case that changes a parameter or
boundary condition. The challenge must be closed and machine-checkable through
the same model or a verified relation fixture.

The transfer challenge:

- is optional;
- never blocks replay, reset, download, or sharing;
- provides immediate explanatory feedback;
- uses no free-form AI grading;
- stores no learner answer beyond the current browser experience; and
- cannot award a verification badge or alter the artifact's scientific tier.

## 6. Scientific grounding without inflated architecture

Start with a small curated reference catalog, not a general RAG platform.

Each catalog entry must contain:

- a stable local reference ID;
- title and publisher/authoritative body;
- canonical URL or bibliographic locator;
- scientific concept tags;
- the bounded claim or relationship it supports;
- locale-independent metadata; and
- a builder-reviewed date.

Rules:

1. A model may select only reference IDs offered from an allowlist. It may not
   invent a URL or citation.
2. Curated goldens must have builder-reviewed references before promotion.
3. A live generated lesson without a matched curated reference may still give
   a safe answer or pass deterministic simulation gates, but the receipt must
   state that no curated source was attached.
4. A reference supports a claim; it does not by itself prove that generated
   code implements the claim correctly.
5. Source lookup cannot override failed physics, motion, security, browser, or
   accessibility gates.
6. Do not add embeddings or a vector database unless a measured catalog
   coverage failure justifies a bounded retrieval experiment after release.

## 7. Architecture

```text
learner question
  -> deterministic safety/privacy prefilter
  -> GPT-5.6 structured understanding
       -> immediate answer
       -> existing learning/model contract
       -> bounded reference-ID candidates when available
  -> honest simulatable decision
       -> answer-only + safe suggestions, or
       -> verified cache / GPT-5.6 module generation
  -> deterministic schema/security/physics gates
  -> actor-motion and shared-state gates
  -> assembled trusted shell
  -> browser/accessibility/temporal verification
  -> discovery UI
       -> optional prediction
       -> model-derived observation
       -> causal explanation
       -> model-checked transfer challenge
  -> honest receipt and portable artifact
```

These are stages and responsibilities, not a claim that four autonomous agents
exist. Keep the trusted shell/generated-module boundary. Do not introduce
accounts, a new database, 3D, WebAssembly, or a second simulation runtime for
this work.

## 8. Delivery batches

### V0 — activate and baseline

- Re-read this plan, `CONTINUATION-BRIEF.md`, `ACCEPTANCE-MATRIX.md`, and the
  current schemas before acting.
- Prove the activation gate with named commands and evidence.
- Record HEAD, clean status, test counts, coverage, Ruff, browser/a11y results,
  and the 30-row acceptance state in `BUILD-NOTEBOOK.md`.
- Create a field-reuse audit mapping every desired learner surface to the
  existing understanding/module contracts.
- Do not change code in this batch.

**Exit:** clean baseline and an evidence-backed decision about the minimum
contract delta.

### V1 — closed discovery contracts, TDD first

- Write failing tests for only the approved gaps from V0.
- Prefer deriving the plan card from existing fields.
- If needed, add closed structures for limitations, allowlisted reference IDs,
  and a verifiable transfer challenge.
- Require localized learner-facing fields in Arabic and English.
- Add negative fixtures for extra fields, invented references, contradictory
  transfer answers, missing outputs, and uncheckable free-text grading.
- Update mock backends before any live model call.

**Exit:** closed schemas and deterministic validation are green; no UI yet.

### V2 — visible scientific plan

- Render the answer first and the plan card second.
- Use the trusted shell/application UI for structure and accessibility.
- Keep the scientific actor and primary causal change visually dominant.
- Cover empty, non-simulatable, delayed, failed, offline, and retry states.
- Verify Arabic/English, RTL/LTR, keyboard, screen reader, reduced motion,
  320px, 390x844, 1440x900, and 200% zoom.

**Exit:** the learner can state what will change and what will be observed
before manipulating the experiment.

### V3 — observation, explanation, and transfer

- Derive observation feedback from the current tested model state.
- Compare an optional prediction with observed output neutrally.
- Tie the explanation to the changed input and output relationship.
- Implement one closed, model-checkable transfer challenge.
- Keep all learner interaction session-local and resettable.
- Test prediction skipped, correct, incorrect, changed after reset, replayed,
  reduced-motion, and keyboard-only journeys.

**Exit:** every promoted golden completes the discovery loop without an
additional model call or persistent learner record.

### V4 — sources, limitations, and receipt

- Add the curated reference catalog with schema and integrity tests.
- Attach builder-reviewed references to the six goldens.
- Show assumptions, limitations, source status, test counts, and verification
  tier in the receipt using precise copy.
- Distinguish `curated reference attached` from `no curated reference matched`.
- Reject unknown, malformed, duplicate, or model-invented reference IDs.
- Confirm the receipt never says scientifically proven, guaranteed, or fully
  accurate.

**Exit:** a learner or judge can see what evidence exists and where the model
stops being authoritative.

### V5 — unseen-question evaluation

Create a sanitized, curated benchmark of at least 12 non-personal questions:

- six Arabic and six English;
- honestly simulatable and non-simulatable cases;
- more than one scientific domain;
- at least one misconception-sensitive case per locale; and
- no question copied from public learner input.

Record for each case:

- eligibility decision;
- answer availability;
- contract validity;
- generation/heal calls;
- deterministic and browser gate results;
- false-verification outcome;
- latency; and
- transfer-challenge validity when a simulation passes.

Do not claim improved learning outcomes from this engineering benchmark. A
learning-effect claim requires a separate learner study.

**Exit:** report includes all cases, failures, and zero hidden exclusions.

### V6 — final proof and narrative

- Revalidate the six goldens through every old and new gate.
- Run the complete suites, Ruff, coverage, browser/a11y, temporal motion, and
  portable offline-artifact checks.
- Update README and demo copy to describe real stages rather than fictional
  agents.
- Demonstrate within the judge path:
  1. a new Arabic question;
  2. immediate answer;
  3. visible scientific plan;
  4. optional prediction and active control;
  5. concept-relevant motion;
  6. causal explanation and transfer;
  7. receipt, assumptions, limitations, and source status; and
  8. one honest answer-only fallback.
- Store sanitized evidence paths and exact commands in `BUILD-NOTEBOOK.md`.

**Exit:** all value rows below pass and existing acceptance remains 30/30.

### V7 — optional breadth after the proof is complete

Only after V6:

- add four goldens to reach ten, one at a time through all gates;
- consider a session-only `what if?` tutor that is constrained by the same
  model outputs and fixtures; and
- evaluate bounded reference retrieval only if catalog coverage evidence shows
  a real gap.

None of V7 is required to prove the core idea.

## 9. Value acceptance matrix

Update this table only from named evidence. `passing` without evidence is not a
valid state.

| ID | Status | Requirement | Required evidence |
|---|---|---|---|
| VALUE-BASE-01 | not-started | Existing continuation remains 30/30 and clean before activation. | Full baseline report and clean status. |
| VALUE-CONTRACT-01 | not-started | Existing fields are reused and every new field has a proven gap. | Field-reuse audit and schema diff review. |
| VALUE-PLAN-01 | not-started | Simulatable results show a concise causal plan after the answer. | AR/EN schema, render, and browser tests. |
| VALUE-CONTROL-01 | not-started | Primary control remains usable without prediction. | Unit, keyboard, and mobile journey. |
| VALUE-OBSERVE-01 | not-started | Observation feedback comes from the tested pivotal model state. | Shared-state positive and divergent negative fixtures. |
| VALUE-EXPLAIN-01 | not-started | Explanation connects changed input, relationship, and observed output. | Six-golden content checks and snapshots. |
| VALUE-TRANSFER-01 | not-started | Transfer challenge is closed, model-checkable, optional, and explanatory. | Contract, physics, reset, and browser tests. |
| VALUE-SOURCE-01 | not-started | References use curated IDs; arbitrary or invented citations fail closed. | Catalog integrity and negative schema tests. |
| VALUE-RECEIPT-01 | not-started | Receipt distinguishes checks, assumptions, limitations, and source status honestly. | Tier/copy matrix and browser snapshots. |
| VALUE-PRIVACY-01 | not-started | Predictions, observations, and transfer answers are not persisted. | Storage/log/cache/download privacy tests. |
| VALUE-EVAL-01 | not-started | Sanitized AR/EN unseen benchmark reports every case without cherry-picking. | Benchmark manifest and report. |
| VALUE-TRUST-01 | not-started | No failed artifact receives verified promotion. | Cross-gate negative promotion suite. |
| VALUE-GOLD-01 | not-started | Six goldens pass the complete old and new discovery contracts. | Per-golden report, hashes, and browser evidence. |
| VALUE-RELEASE-01 | not-started | Existing and value gates are fully green with truthful evidence. | Final report and notebook ledger. |

## 10. Failure behavior

- **Not simulatable:** preserve the answer, explain that an honest interactive
  model was not built, and offer verified suggestions. Do not fabricate a plan
  card or transfer challenge.
- **No reference match:** preserve valid output, state that no curated reference
  was attached, and do not imply source-backed status.
- **Generation/heal/QA failure:** preserve the answer and gallery; do not show a
  partial discovery flow as verified.
- **Observation/transfer inconsistency:** fail the new discovery gate and block
  promotion; do not replace computed evidence with generic prose.
- **Browser or accessibility failure:** block promotion exactly as today.
- **Reference catalog unavailable:** degrade honestly without weakening physics
  or security gates.

## 11. Implementation discipline

- Work only in the original root session; do not create subagents for this
  extension unless the user later changes that instruction explicitly.
- Use red -> green -> refactor for every batch.
- Run focused tests, affected suites, Ruff, then the full release chain.
- Do not use live model calls until mock/schema/deterministic tests are green.
- Use GPT-5.6 routing from `MODEL-ROUTING.md`; record any escalation and reason.
- Do not invoke Sol without a recorded reason.
- Keep commits small, coherent, and passing. Never amend, rebase, reset, or
  rewrite the accepted history.
- Do not stage unrelated dirty files. Do not hide, skip, or weaken a failure.
- Do not push, deploy, publish, or mutate external services without explicit
  user authorization.
- Record real evidence only; never fabricate a session ID, test result, source,
  benchmark outcome, screenshot verdict, or model receipt.

Suggested commit sequence after activation:

```text
docs: record scientific discovery activation audit
feat: close scientific discovery contracts
feat: expose the causal experiment plan
feat: complete the observation and transfer loop
feat: add curated scientific reference receipts
test: evaluate unseen scientific discovery cases
docs: record scientific discovery release evidence
```

Commit names are illustrative; use the smallest truthful split supported by the
actual work.

## 12. Definition of done

This plan is complete only when:

1. the original 30 acceptance rows still pass;
2. all 14 value rows pass with named evidence;
3. all six goldens complete the full discovery loop in Arabic and English;
4. the unseen benchmark is published internally with failures included;
5. no failed simulation, transfer, source, motion, browser, or accessibility
   gate can receive verified promotion;
6. all learner interaction remains ephemeral;
7. full tests, Ruff, coverage, browser/a11y, temporal motion, and offline
   artifact verification pass;
8. `BUILD-NOTEBOOK.md` contains real commands, outputs, evidence paths, and
   commits; and
9. the demo and README describe the implemented system without overclaiming
   agents, RAG, personalization, universal coverage, or scientific certainty.

## 13. Instruction to the executing Codex session

When instructed to execute this file:

1. verify that the session ID is the original root ID listed at the top;
2. inspect Git status and do not absorb unrelated or in-progress changes;
3. report whether the activation gate is open;
4. if it is closed, finish the existing continuation and do not begin V1;
5. when it opens, execute V0 through V6 in order with TDD and small commits;
6. update the value matrix and `BUILD-NOTEBOOK.md` only from actual evidence;
7. stop only for a genuine blocker requiring new user authority; and
8. never claim completion until both the original and value acceptance matrices
   are fully green.

## 14. Unified-generation foundation addendum

### No Example-Specific Correctness Fixes

Correctness fixes may not branch on a lesson ID, slug, reference name, question
text, artifact hash, or one of the six examples. They may not introduce
per-lesson coordinates, CSS, prompts, validators, source-string rewrites, or
post-generation artifact patches. A discovered defect must be expressed as a
general contract, an executable invariant, a minimal generated-path regression,
and—where appropriate—an independent scientific oracle.

Allowed reference material is data, not runtime logic: known cases, numerical
relations, tolerances, source references, learning objectives, required
observables, and acceptance criteria. A legacy artifact can remain temporarily
as a regression input, but it is not a source of scientific truth and cannot be
copied into the shared implementation.

### Foundation traceability matrix

| Foundation row | Status | Requirement | Implementation/evidence destination |
|---|---|---|---|
| UNIFY-INV-01 | passing | Classify existing general rules, scientific oracles, reusable assets, custom runtime, patched artifacts, and temporary fixes. | `UNIFIED-GEOMETRY-INVENTORY.md` at audited HEAD `049f6fa`. |
| UNIFY-ADR-01 | passing | Record the reference defect, first custom correction, generated-path gap, freeze, extraction, and CI decision. | `docs/architecture/ADR-0001-unified-scene-geometry-validation.md`. |
| UNIFY-CONTRACT-01 | passing | Closed shared overlap/contact/occlusion/clipping/clearance contract with safe defaults and fail-closed unsupported geometry. | `server/schemas/scene_geometry.schema.json`, `server/scene_geometry.py`, and `tests/test_scene_geometry.py`. |
| UNIFY-VALIDATOR-01 | passing | One deterministic validator used by generated and curated paths. | `tests/test_scene_geometry_wiring.py`, `tests/test_scene_geometry_ci_wiring.py`, and the AST call-boundary gate. |
| UNIFY-CLAMP-01 | passing | Candidate -> clamp/fit -> recompute -> validate all -> alternative or reject. | `tests/test_scene_geometry_properties.py` rejects missing or stale post-fit evidence and an invalid final clamp. |
| UNIFY-CI-01 | passing | Production learner runtime cannot import or branch on example-specific code. | `scripts/check_no_example_specific_runtime.py` returned `[]`; its focused suite passed 10 tests. |
| UNIFY-GEN-COLLISION-01 | passing | A colliding generated fixture is rejected through `verify_candidate`. | Example-agnostic real-path tests in `tests/test_scene_geometry_ci_wiring.py`. |
| UNIFY-OCCLUSION-01 | passing | Explicit scientific occlusion is accepted by the same path. | Shared policy unit test and generated-path integration both pass. |
| UNIFY-RESPONSIVE-01 | passing | Generated viewport/state samples catch responsive and dynamic collision defects. | 39 deterministic viewports and 11 temporal samples in `tests/test_scene_geometry_properties.py`. |
| UNIFY-MOON-REGRESSION-01 | passing | Moon remains only a fixture and passes without a custom production branch. | Legacy browser regression in the 303-pass full suite plus the zero-finding AST/import gate; the custom refresher remains frozen offline only. |
| UNIFY-REPRO-01 | blocked | A reference artifact is reproducibly generated with unified provenance and no manual patch. | Deliberately deferred until the owner-authorized Canary phase. |

The blocked reproducibility row is an explicit phase boundary, not a hidden
success. Phases 1–4 must not generate a Canary or rewrite the six artifacts.
