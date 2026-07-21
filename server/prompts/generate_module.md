Return closed-schema JSON only; use no tools. Assign JavaScript once to
`window.LayshSimulation`; no Markdown, full HTML, CSS, or shell UI.

Export exactly `version`, `init`, `setParameter`, `test`, `resize`, and `destroy`.
`version` must be the number `1`. `init(options)` receives `canvas`, `context`, `width`, `height`,
`locale`, `reducedMotion`, and `emitFrame`; capture them and draw now.
Do not rename `context` to `ctx`. `setParameter(name, value)` redraws for the declared ID. Every draw calls
`emitFrame`. `test(inputs)` is deterministic, visually side-effect free, and returns exactly the
declared finite outputs.

Shared pivotal-state contract:

- Define one pure named state-object function, preceded by
  `/* LAYSH_SHARED_MODEL: modelState */` using its real name.
- Render and `test(inputs)` call and consume that same model function. Derive pivotal visuals
  (angle, phase, fraction, flow, brightness) from it; easing cannot change their source.
- A separately calculated pivotal visual that can disagree with `test(inputs)` is rejected.

Shared scene-geometry contract:

- After each fit/clamp, replace `canvas.__layshSceneGeometry` with nonempty closed v1.0 samples:
  `phase: "post_fit"`, canvas viewport, state, drawn scientific circles, and pair relations.
- Objects declare `clippingPolicy`; pairs declare `overlapPolicy`, `contactPolicy`, and
  `minimumClearance`. Use `scientific_occlusion` only when physically intended. Recompute after
  fitting; missing/unsupported evidence and undeclared overlap, contact, or clipping fail closed.

Use only the supplied canvas/context, Math, Number, arrays, and plain objects. No document, network,
storage, navigation, dynamic code, workers, timers, sensors, audio, clipboard, console, URLs, or
`requestAnimationFrame`. Keep source ≤96 KiB in UTF-8 bytes. Physics, fixtures, units, assumptions,
security, and the spec are immutable.

Visual contract:

- Create layered scene depth with at least three visible depth layers: domain gradient, near/far
  bodies, and restrained ambient texture; never a flat canvas.
- Make physical light beautiful and physically consistent: glow, soft shadow, true occlusion;
  never draw light through an opaque body. Show its subtle shadow cone.
- Add subtle idle motion. On the shell's ~12 fps same-value redraw, advance private `visualPhase`
  only when reduced motion is off; affect restrained shimmer/trails, never physics or `test(inputs)`.
- Add smooth reactive feedback tied to parameter changes; preserve the prior display value and alter
  more than text.
- Draw rounded translucent readout chips with concise locale labels. If geometry is amplified, label
  its numeric factor (e.g. `×100`) on-canvas; never distort silently.
- Shade continuous bodies with smooth fills or gradients, never golf-ball dot patterns. Illuminated spheres
  need a curved terminator or equivalent physical mask, never a rectangular clip.
- If schematic and observer views share a canvas, label them `منظر علوي` / `كما يبدو من الأرض` or
  `Top view` / `View from Earth` according to locale.
- Keep labels legible and inside canvas. Motion adds atmosphere, never unsupported causal claims.

Self-check ABI, tests, immediate draw, three visible depth layers, physical light/occlusion, idle
motion, same-value redraw, reactive feedback, readout chips, reduced motion, and curved terminator.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
