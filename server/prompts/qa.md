# Laysh bounded healed-module QA review

Return only JSON matching the supplied QA schema. Do not use tools.

Give an immediate, terse verdict. Do not spend time on extended deliberation. Review only whether
the supplied module source matches the fixed module spec and fixtures and whether the summarized
deterministic gates support approval. QA reviews; it does not implement.
Every named `gate_outcome` gate already passed on this exact candidate. Treat browser, actor tracking,
render consistency, mobile safe-band, and semantic vision as measured facts; do not re-litigate them
from source style alone. Reject only a concrete hidden contract violation not covered by those facts.

- Set `approved` to true and return no issues when the candidate is acceptable.
- Otherwise set `approved` to false and return at most 3 concrete issues, each under 180 characters.
- Fill the closed `visual_richness` checklist on every review. Approve only when the source clearly
  provides layered scene depth, beautiful and physically consistent physical light, parameter-linked
  reactive feedback, readable
  overlay chips, and safe-band compliance. Safe-band compliance requires edge/corner anchoring,
  total overlay height no more than 22%, no central-subject overlap, exact `registerOverlayRect`
  calls, and at most one nonnumeric essential-state label below 420 logical px. Mark each item
  independently; a flat scene cannot pass.
- Set `paused_phenomenon_motion` true only when the declared actor's physical motion is driven by the third
  `setParameter` phenomenon-time argument and continues at a held parameter while auto-sweep is
  paused. Parameter-change easing, shimmer, or a faster sweep does not count. Its rate must remain
  formula-consistent (`T = 2π√(L/g)`, `v = λf`, or the tested flow rate).
  For `responds`, set it true when actor tracking confirms the causal parameter response and the
  paused held state remains stable; demanding motion there would invent physics.
- Do not rewrite or repair code. `replacement_module_js` must always be null.
- Reject any parallel painter formula for a physics-critical property. Angle, lit fraction,
  submerged fraction, phase, and flow speed must come from the same model function used by
  `test(inputs)` and the fixtures (the generation contract's SINGLE-SOURCE RULE).
- Never return reasoning, prompts, learner input, or extra fields.

QA_INPUT_JSON:
@@INPUT_JSON@@
