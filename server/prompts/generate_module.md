Return closed-schema JSON only; use no tools. Assign JavaScript once to
`window.LayshSimulation`; no Markdown, full HTML, CSS, or shell UI.

Export exactly `version`, `init`, `setParameter`, `test`, `resize`, `destroy`.
`version` must be the number `1`. `init(options)` receives `canvas`, `context`, `width`, `height`,
`locale`, `reducedMotion`, and `emitFrame`; draw immediately. Do not rename `context` to `ctx`.
`setParameter(name,value)` handles the declared ID and redraws; each draw calls `emitFrame`.
`test(inputs)` is deterministic, side-effect free, and returns only declared finite outputs.

Shared model:
- Put `/* LAYSH_SHARED_MODEL: modelState */` before one pure named state-object function.
- In both draw and `test(inputs)`, bind `const state = modelState(...)` and read
  `state.<declared_output>`. All pivotal physics comes from it; easing is presentation-only.

Shared geometry:
- After every fit/clamp assign `canvas.__layshSceneGeometry = [{ schemaVersion: "1.0",
  phase: "post_fit", ... }]` from current dimensions/state, with nonempty scientific circle/rect
  objects and relations. Declare object `clippingPolicy` and relation `overlapPolicy`,
  `contactPolicy`, `minimumClearance`. Only intended physics may use `scientific_occlusion`;
  missing/unsupported evidence and undeclared overlap/contact/clipping fail closed.

Use canvas/context, Math, Number, arrays, plain objects only. No document, network, storage,
navigation, dynamic code, workers, timers, sensors, audio, clipboard, console, URLs, or
`requestAnimationFrame`. Source <=96 KiB in UTF-8 bytes. All supplied contracts are immutable.

Visual contract:
- Build layered scene depth with at least three visible depth layers: domain gradient and near/far bodies.
- Make physical light beautiful and physically consistent: glow, soft shadow, true occlusion;
  never draw light through an opaque body. Show its subtle shadow cone.
- Add subtle idle motion: on the shell's ~12 fps same-value redraw, advance private `visualPhase`
  only when reduced motion is off. It may affect shimmer/trails, never physics or `test(inputs)`.
- Add smooth reactive feedback tied to changes; preserve the prior display value and alter more than text.
- The prediction must be visibly testable at minimum, midpoint, and maximum. The declared actor's
  causal action carries the change, not only text, a marker, a frame counter, or decorative motion.
  Never move/resize the whole diagram to fake a scientific consequence.
- Never draw changing numbers, percentages, or live readout values on the canvas. The trusted shell
  owns the live numeric readout below the scene as readout chips. Stable conceptual labels are
  allowed. If geometry is amplified, label its numeric factor (for example `x100`) on-canvas;
  never distort silently.
- Use smooth fills or gradients for continuous bodies, never golf-ball dot patterns. Illuminated
  spheres need a curved terminator or equivalent physical mask, never a rectangular clip.
- If schematic and observer views share a canvas, label `منظر علوي` / `كما يبدو من الأرض` or
  `Top view` / `View from Earth` by locale. Keep labels legible and inside canvas.

Self-check ABI, fixtures, first draw, shared model, post-fit geometry, three visible depth layers,
physical light, idle motion, same-value redraw, reactive feedback, stable conceptual labels,
reduced motion, min/mid/max causality, actor visibility, curved terminator.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
