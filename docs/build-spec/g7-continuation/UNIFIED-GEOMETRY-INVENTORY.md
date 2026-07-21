# Unified geometry migration inventory

- Audit date: 2026-07-21
- Root session: `019f7998-9378-72b2-b590-ee10e632ce81`
- Audited HEAD: `049f6fa`
- Owner directive: `OWNER-DIRECTIVE-UNIFY.md`, phases 1–4 only

This inventory freezes new example-specific correctness work. `current status`
describes the state at the start of the migration; it is not a claim that the
destination already exists. Line ranges name the audited revision and may move
after extraction.

| file | symbol / line range | associated example | type | migration destination | replacement test | removal condition | current status |
|---|---|---|---|---|---|---|---|
| `server/verify.py` | `_source_report`, `formula_presentation_report`, `verify_module_source`, `_run_node_report`, `verify_module_with_node`, `verify_candidate` (54–399) | every generated learner module | `GENERAL_RULE` | Keep as the generated-verification orchestrator; call the shared scene validator from here. | Generated collision through `verify_candidate`; generated scientific occlusion through the same call. | Never removed; geometry blind spot must be removed before phase 3 closes. | Existing production path; geometry missing. |
| `server/browser_verify.py` | `verify_artifact_in_browser` (68–158) | every generated learner artifact | `GENERAL_RULE` | Evidence collector for a shared geometry report; policy decisions stay in the shared validator. | Browser/runtime regression plus shared-validator wiring test. | Never removed; do not duplicate policy logic here. | Existing production path; geometry missing. |
| `server/golden_physics_motion.py` | `evaluate_body_geometry` (54–164) | Moon phases | `GENERAL_RULE` | `server/scene_geometry.py` shared contract and validator. | Circle overlap, declared occlusion, clipping, contact, unsupported shape, responsive and dynamic samples. | Delete the duplicate after both generated and curated paths import the shared validator. | Proven circle-distance rule, trapped in curated path. |
| `server/golden_physics_motion.py` | `verify_golden_physics_motion` geometry branch (166–353) | six pinned lessons; geometry only for Moon | `GENERAL_RULE` | Retain curated evidence collection, but delegate every geometry decision to `server/scene_geometry.py`. | Import/call-boundary test plus six-lesson regression. | Wrapper can remain only as offline regression tooling; it may not own geometry policy. | Partial; stronger than generated path. |
| `server/golden_geometry.py` | `_SCENE_LAYOUT`, `_OLD_*`, `_NEW_*`, `upgrade_moon_geometry` (11–97) | Moon phases | `EXAMPLE_SPECIFIC_RUNTIME` | None. The correct invariant moves to the shared contract; coordinates and string replacements do not migrate. | General post-clamp collision and responsive property tests; Moon artifact is a regression fixture only. | Shared validator is connected to generated and curated paths and the Moon regression passes without importing this module. | Frozen custom transformer; scheduled for deletion. |
| `server/golden_geometry.py` | `refresh_pinned_moon_geometry` (100–147) | Moon phases | `MANUALLY_PATCHED_ARTIFACT` | None. Future regeneration must use the unified generator after Canary approval. | No-example-specific runtime/import gate; Moon regression fixture. | Shared path blocks the defect and no production or curated verifier imports this refresher. | Frozen artifact patcher; scheduled for deletion. |
| `scripts/refresh_pinned_moon_geometry.py` | module entry point (1–9) | Moon phases | `OBSOLETE_TEMPORARY_FIX` | None. | AST/import-boundary gate. | `server/golden_geometry.py` is removed. | Frozen; scheduled for deletion. |
| `server/golden_shared_state.py` | `_moon_phases` … `_day_night`, `upgrade_golden_module` (17–448) | all six references | `EXAMPLE_SPECIFIC_RUNTIME` | Model relations belong in independent scientific fixtures/model registry; source-text rewriting does not migrate. | Existing shared-state divergent negatives plus future unified compiler reproducibility test. | Unified compiler and Canary reproduce the references without source rewriting. | Frozen offline migration tool; not called by learner pipeline. |
| `server/golden_motion.py` | `verify_golden_actor_motion` (25–163) | all six references | `GENERAL_RULE` | Future shared temporal browser verification; outside phases 1–4 except import-boundary classification. | Existing decorative-motion negatives and generated-path temporal wiring in a later phase. | Remove the golden-specific wrapper only after equivalent shared browser evidence exists. | Retained offline regression wrapper. |
| `server/motion.py` | actor trajectory evaluators | every scene actor | `GENERAL_RULE` | Retain as a shared deterministic evaluator. | Existing actor-only positive/negative fixtures. | Never removed while used by shared temporal verification. | Already general and proven. |
| `server/physics_motion.py` | action physics evaluators | all six action families | `SCIENTIFIC_ORACLE` | Retain as independent action-specific known-case fixtures, not layout code. | Existing declared-tolerance physics tests. | Replace only with an independently validated model registry. | Retained reference oracle. |
| `server/shared_state.py` | `shared_model_report` | every generated module | `GENERAL_RULE` | Retain in generated verification. | Existing divergent visual/model fixtures. | Never removed without a stronger state-binding contract. | Already general and connected. |
| `scripts/check_golden.mjs` | `geometrySamples` browser probe | Moon phases today | `REUSABLE_ASSET` | Evidence producer consumed by the shared validator; it must not decide policy. | Curated-path shared-validator wiring test. | Rename/generalize only when the broader browser-verification consolidation is implemented. | Retained offline probe. |
| `server/fixtures/*_ar.json` | `checks`, `review_contract.physics_motion`, optional `body_geometry` | six references | `SCIENTIFIC_ORACLE` | Normalize later into code-free reference cases/model-registry facts. | Known-case, invariant, and tolerance tests independent of rendered artifact. | Do not delete; remove non-reference fields only after the unified spec format and parity tests exist. | Retained references; partially mixed format. |
| `out/cache/golden/*.json` | embedded `artifact` and receipts | six references | `MANUALLY_PATCHED_ARTIFACT` | Build output with provenance from the future unified generation path. | Artifact reproducibility/provenance test after Canary. | Retire only after Canary and six regenerations pass; explicitly forbidden in phases 1–4. | Legacy regression inputs; not scientific truth. |
| `out/cache/golden/moon_phases.json` | embedded artifact (~258 kB) and `geometry_refresh` receipt | Moon phases | `MANUALLY_PATCHED_ARTIFACT` | Same as other build output; no source extraction. | Moon regression through shared validator; future unified provenance. | Retire only after approved Canary/regeneration phase. | Retained regression fixture, never copied into the shared runtime. |
| `sim_shell/contract.js`, `sim_shell/shell.js` | trusted ABI/readout/runtime shell | every simulation | `REUSABLE_ASSET` | Retain; add only general scene-evidence plumbing when required. | ABI, readout, teardown, resize, reduced-motion tests. | Never removed without an equivalent trusted shell. | General and proven. |
| `server/prompts/generate_module.md`, `server/prompts/qa.md` | general visual/readout requirements | every generated module | `GENERAL_RULE` | Keep generic; require the shared visual contract without lesson names. | Prompt snapshot plus generated fixture entering shared geometry validation. | Remove only when free-module generation is replaced by trusted SceneSpec compilation. | General; geometry evidence contract still missing. |

## Freeze rule

No new branch, prompt, coordinate, CSS override, validator, refresh script, or
artifact rewrite may be keyed by lesson ID, slug, question text, or one of the
six reference names. Scientific facts and known cases remain fixtures. A defect
must become a general executable contract and a generated-path regression.

## Measured split before extraction

The four `server/golden_*` modules above total 1,111 lines. The generated
verification core (`server/verify.py`, `server/browser_verify.py`, and
`server/assemble.py`) totals 614 lines. Line count is only a smell; the decisive
evidence is the call graph in ADR-0001: the learner path does not call the only
geometry evaluator.
