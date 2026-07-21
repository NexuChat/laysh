Return closed-schema JSON only; use no tools. Produce JavaScript assigned once to
`window.LayshSimulation`; no Markdown, full HTML, CSS, or shell UI.

Export exactly `version`, `init`, `setParameter`, `test`, `resize`, and `destroy`.
`version` must be the number `1`.
`init(options)` receives `canvas`, `context`, `width`, `height`, `locale`, `reducedMotion`, and
`emitFrame`; capture those exact names and draw immediately. Do not rename `context` to `ctx`.
`setParameter(name, value)` redraws synchronously for the declared ID. Both draw paths call the
captured `emitFrame`. `test(inputs)` is deterministic, visually side-effect free, and returns exactly
the declared finite outputs.

Shared pivotal-state contract:

- Define one pure named model function returning a state object, for example
  `function modelState(value) { ... }`, preceded by
  `/* LAYSH_SHARED_MODEL: modelState */` with its real name.
- `draw` or `render` and `test(inputs)` must call and consume that same model function.
  Derive pivotal visuals—angle, phase, illuminated/submerged fraction,
  flow speed, brightness, or equivalent—from its state; easing may not change
  their source.
- Never calculate a pivotal formula separately: a visual value that can
  disagree with `test(inputs)` is rejected.

Use only the supplied canvas/context, Math, Number, arrays, and plain objects. No document, network,
storage, navigation, dynamic code, workers, timers, sensors, audio, clipboard, console, external URLs,
or `requestAnimationFrame`. Keep source at or below 96 KiB measured in UTF-8 bytes. Physics, fixtures, units, assumptions, security,
and the spec are immutable.

Visual contract:

- Create layered scene depth with at least three visible depth layers: a domain gradient, near/far
  bodies, and restrained ambient particles or texture. Never use a flat canvas.
- Make physical light beautiful and physically consistent using controlled glow, soft shadow, and
  true occlusion; never draw light through an opaque body. Show its subtle shadow cone.
- Include subtle idle motion. The shell issues same-value redraw calls near 12 fps: advance a private
  `visualPhase` only on those calls when reduced motion is off. It must visibly affect a restrained
  coordinate, opacity, shimmer, or trail without changing `test(inputs)` or physics.
- Add smooth reactive feedback tied to parameter changes—eased geometry, a fading trail, ripples, or
  quantity-linked particles. Preserve the previous display value locally; changing a parameter must
  alter more than text.
- Draw at least one rounded translucent readout chip beside the phenomenon with concise Arabic or
  English labels; never leave raw corner numbers.
- Shade continuous bodies with smooth fills or gradients, never golf-ball dot patterns. Illuminated spheres
  need a curved terminator or equivalent physical mask, never a rectangular clip.
- If schematic and observer views share a canvas, label them `منظر علوي` / `كما يبدو من الأرض` or
  `Top view` / `View from Earth` according to locale.
- Keep every label legible and inside the canvas. Motion adds atmosphere only, never unsupported
  causal claims.

Before returning, self-check the ABI, deterministic tests, immediate draw, three visible depth layers,
physical light and occlusion, idle motion, same-value redraw behavior, reactive feedback, readout chips,
reduced motion, and the curved terminator rule where applicable.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
