# Laysh curated semantic visual QA

Return only JSON matching the closed visual QA schema. Review the three attached
screenshots in order: initial state, mid-action state, then parameter-changed
state. Give an immediate terse verdict; do not use tools, rewrite code, or infer
facts that are not visible.

- `actor_visible`: the declared scientific actor is visible, legible, and not
  hidden, clipped, or displaced outside the simulation.
- `action_performed`: the three images visibly demonstrate the declared action;
  decorative backgrounds or unrelated particles do not count.
- `physically_consistent`: the visible sequence agrees with the supplied fixed
  model summary and passed gate names, without contradictory light, geometry,
  direction, or scale cues.
- `defects`: at most three concise observable defects. Use an empty list only
  when none are visible.

This verdict is supplemental. It can reject a curated candidate but can never
override a deterministic or browser failure. Never return reasoning, learner
input, paths, prompts, or extra fields.

VISUAL_QA_INPUT_JSON:
@@INPUT_JSON@@
