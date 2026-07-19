# Laysh module generation stage

Return only JSON matching the supplied closed schema. Do not use tools.

Generate only the phenomenon-specific JavaScript assigned exactly once to
`window.LayshSimulation`. Do not return full HTML, CSS, trusted-shell UI, or Markdown.

The object must contain exactly `version`, `init`, `setParameter`, `test`, `resize`, and `destroy`.
Use only the supplied canvas/context, Math, Number, arrays, and plain objects. Do not use document,
network, storage, navigation, dynamic code, workers, timers, sensors, audio, clipboard, console, or
external URLs. `init` draws synchronously and calls `emitFrame`. `setParameter` redraws and calls the
captured `emitFrame`. `test(inputs)` is deterministic, has no visible side effects, and returns exactly
the declared finite outputs. Honor reduced motion by avoiding automatic animation. Keep source under
40 KiB.

UNDERSTANDING_JSON:
@@INPUT_JSON@@

