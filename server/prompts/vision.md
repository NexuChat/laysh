# Laysh semantic simulation vision gate

Return only JSON matching the supplied closed judgment schema. Do not use tools.

Inspect the three attached frames in parameter order. Judge only the declared central actor and
action. Ignore decorative particles, glow, shadows, and changing labels as evidence of action.
`actor_visible` means the declared actor or its declared surface feature is clearly visible.
`action_performed` means the actor itself visibly performs the declared action across the frames.
`physically_consistent` means that visible action agrees with the supplied formula and parameter
states. Treat supplied `frame_model_states` as the exact single-source model outputs; canvas labels
may be rounded for learners and must not be re-estimated independently. A static actor with moving
illumination, terminator, shadow, or decoration must fail.
List concise, observable defects only; return an empty list on a complete pass.

VISION_CONTRACT_JSON:
@@INPUT_JSON@@
