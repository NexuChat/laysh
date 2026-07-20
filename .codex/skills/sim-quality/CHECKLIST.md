# Simulation quality checklist

## Contract

- Output matches the closed module schema with no extra keys.
- `window.LayshSimulation` exports exactly version, init, setParameter, test, resize, destroy.
- `test(inputs)` is deterministic, side-effect free, and returns declared finite outputs.
- The first frame is emitted within four seconds and reduced motion stops auto-animation.

## Scientific checks

- One primary variable controls the stated observable outcome.
- At least two independent understanding-stage fixtures pass, including boundaries when relevant.
- Units, tolerances, relational direction, and simplifying assumptions are explicit.

## Teaching checks

- Prediction invites reflection before observation but never locks the primary control; observation precedes causal explanation.
- No more than two controls exist and only the primary is initially prominent.
- Feedback names what changed and why; no scores, streaks, shame, or celebration effects.
- The misconception has a localized common-misconception label, warning, explicit correction, and visible causal evidence.
- Canvas state has an equivalent textual explanation.

## Safety and portability

- No network, storage, navigation, dynamic code, workers, sensors, clipboard, or messaging APIs.
- No external URL or full HTML document; generated source is at most 96 KiB measured in UTF-8 bytes.
- Trusted CSP, iframe sandbox, escaping, and error-beacon boundaries remain unchanged.
- Keyboard, RTL/LTR, 320px reflow, and reduced motion retain essential functionality.

## Actor and motion

- Declare one visible, concept-relevant primary actor and one allowed action: `rotates`, `oscillates`, `orbits`, `propagates`, `flows`, `floats_sinks`, or `phases`.
- The actor trajectory, pivotal visual state, and `test(inputs)` derive from one model state; decorative movement never proves the action.
- Reduced motion stops automatic animation while preserving an equivalent readable causal state.
