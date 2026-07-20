# Laysh semantic simulation vision gate

Return only JSON matching the supplied closed judgment schema. Do not use tools.

Inspect the first three desktop frames in parameter order. The fourth desktop frame holds the second
frame's parameter with auto-sweep paused while phenomenon time advances. The fifth frame is mobile
at 390x844. Judge only the declared central actor and action in the desktop sequence. Ignore
decorative particles, glow, shadows, and changing labels as evidence of action.
`actor_visible` means the declared actor or its declared surface feature is clearly visible.
`action_performed` means the actor itself visibly performs the declared action across the frames.
`paused_action_performed` means the actor still visibly performs that action from desktop frame two
to the held-parameter paused frame four. A frozen wave, pendulum, rotating body, orbit, or flow fails.
For a state action such as `floats_sinks`, persistence of the correct equilibrium counts; do not
demand physically dishonest drift or a changed submerged fraction.
For `responds`, the parameter-ordered frames must show the actor's causal static response, while the
held-parameter frame must preserve that same state without invented motion. Count stable held state as
the paused action; do not demand drift.
`physically_consistent` means that visible action agrees with the supplied formula and parameter
states. Treat supplied `frame_model_states` as the exact single-source model outputs; canvas labels
may be rounded for learners and must not be re-estimated independently. A static actor with moving
illumination, terminator, shadow, or decoration must fail.
`labels_obscure_subject` means any in-canvas label or chip overlaps, hides, or materially distracts
from the declared actor in the fifth mobile frame. It must be false. The shell-owned DOM readout
below the canvas is not an in-canvas label and should be ignored.
List concise, observable defects only; return an empty list on a complete pass.

VISION_CONTRACT_JSON:
@@INPUT_JSON@@
