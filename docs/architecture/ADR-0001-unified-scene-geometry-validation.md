# ADR-0001: Unified scene geometry validation

- Status: accepted for migration phases 1–4
- Date: 2026-07-21
- Decision owner: Laysh owner directive
- Representative build session: `019f7998-9378-72b2-b590-ee10e632ce81`

## Context

A visible defect appeared in a reference Moon simulation: independent clamps
kept the Sun's center near the canvas edge while breaking its clearance from the
Moon's orbit. The first correction rewrote that one artifact's source and added
a curated-only circle-overlap check. The correction made the reference pass,
but review then proved that generated learner modules never execute that check.

The truthful sequence is therefore:

1. a reference simulation exposed a real geometry defect;
2. the first fix corrected the example and proved a useful circle-distance
   invariant;
3. call-graph review showed the learner generation path remained geometry-blind;
4. example-specific rewriting was frozen;
5. only the proven invariant will be extracted into a shared contract and
   validator, wired into both generated and curated verification; and
6. CI will prevent an example-specific runtime from reappearing.

## Call graph before this decision

```text
POST /api/ask                          server/app.py:100
  -> JobManager._run                   server/jobs.py:187-198
     -> run_pipeline                   server/pipeline.py:58
        -> validate_module_output
        -> verify_candidate            server/pipeline.py:263
           -> formula_presentation_report
           -> _source_report
           -> shared_model_report
           -> _run_node_report
              -> scripts/verify_module.mjs
           -> assemble_artifact
           -> verify_artifact_contract
        -> manager.browser_verifier    server/pipeline.py:267-270
           -> verify_artifact_in_browser
              -> scripts/check_artifact.mjs
        -> VERIFIED or bounded heal/fallback

Offline curated evidence only:
scripts/verify_golden_physics_motion.py
  -> verify_golden_physics_motion
     -> scripts/check_golden.mjs
        -> geometrySamples
     -> evaluate_body_geometry         server/golden_physics_motion.py:54
```

`server/verify.py` contained no `collision`, `overlap`, `clearance`, or
`geometry` reference at the audited HEAD. `server/golden_geometry.py` was
imported only by its refresh script and its focused test. The line-count ratio
did not establish isolation; the two disjoint call chains above do.

## Decision

1. Define one closed Shared Scene Geometry Contract and one deterministic
   Shared Geometry Validator in a non-golden production module.
2. Treat overlap, contact, occlusion, clipping, and minimum clearance as
   explicit policies. The rule is "no undeclared overlap, contact, occlusion,
   or clipping," not absolute non-overlap.
3. Default scientific objects and undeclared pairs to the safe, forbidding
   policy. Unsupported scientific geometry fails closed.
4. Evidence collectors may report shapes, viewport, state, and post-fit bounds;
   they may not decide policy.
5. Candidate layout must follow: candidate -> clamp/fit -> recompute geometry ->
   validate all constraints -> alternative layout or reject. A clamp is never
   proof of validity.
6. `verify_candidate` and curated regression verification must call the same
   validator. No stronger golden-only geometry branch is permitted.
7. Delete the Moon source transformer and refresher only after the shared path
   and regression tests are green. Retain scientific facts and the legacy Moon
   artifact solely as a regression fixture until the later Canary migration.
8. Add an AST/import-boundary CI gate that rejects example names or `golden_*`
   dependencies in the production learner verification path.

## Explicit non-goals for phases 1–4

- No Canary.
- No regeneration of the six references.
- No claim that SceneSpec, auto-layout alternatives, trusted compiler, or
  immutable provenance are complete.
- No migration of unproven source-rewrite logic from `golden_*`.
- No GPT or visual-model call for geometry validation.

## Alternatives rejected

- **Keep the Moon validator beside the Moon fixture:** leaves new questions
  unprotected.
- **Forbid every intersection:** rejects eclipses, contact, and other valid
  scientific relationships.
- **Trust the model's layout or a screenshot:** neither is an executable
  geometry proof.
- **Delete all goldens now:** destroys independent regression evidence before a
  unified replacement and violates the ordered migration.
- **Copy the custom `sceneLayout` constants into production:** migrates an
  example patch rather than the invariant.

## Consequences

Generated modules that declare scientific scene geometry can be rejected before
publication with actionable, policy-specific diagnostics. Curated evidence and
new learner work share the same minimum. Legacy artifacts remain a disclosed
migration risk until Canary and reproducible regeneration are implemented.

## Implemented call graph after phases 2–4

```text
POST /api/ask
  -> JobManager._run
     -> run_pipeline
        -> verify_candidate
           -> _run_node_report
              -> scripts/verify_module.mjs
                 -> canvas.__layshSceneGeometry samples
           -> validate_scene_geometry
              -> structural and supported-geometry checks on every sample
              -> require final post_fit evidence after any fit/clamp
              -> validate bounds and pair policies on every post_fit state
           -> assemble_artifact only when all deterministic gates pass
        -> verify_artifact_in_browser

Offline curated evidence
  -> verify_golden_physics_motion
     -> scripts/check_golden.mjs
     -> evaluate_body_geometry
        -> validate_scene_geometry
```

The runnable AST/import-boundary gate in
`scripts/check_no_example_specific_runtime.py` protects both shared-validator
edges and rejects example-keyed correctness logic in the learner runtime. The
phase-4 repository scan produced zero findings. Synthetic generated-path tests
prove forbidden collision rejection, explicit scientific-occlusion acceptance,
unsupported-geometry fail-closed behavior, post-fit sequencing, responsive
viewport coverage, and temporal collision detection without a lesson-specific
branch. Canary generation and legacy artifact retirement remain deferred.
