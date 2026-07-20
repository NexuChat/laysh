# Laysh module generation stage

Return only closed-schema JSON and do not use tools. Generate only the phenomenon JavaScript,
assigned once to `window.LayshSimulation`; never return Markdown, full HTML, CSS, or shell UI.

Export exactly `version`, `init`, `setParameter`, `test`, `resize`, and `destroy`.
`version` must be the number `1`.
`init(options)` receives `canvas`, `context`, `width`, `height`, `locale`, `reducedMotion`, and
`emitFrame`; capture those exact names and draw immediately. Do not rename `context` to `ctx`.
`setParameter(name, value)` redraws synchronously for the declared ID. Both draw paths call the
captured `emitFrame`. `test(inputs)` is deterministic, visually side-effect free, and returns exactly
the declared finite outputs.

Use only the supplied canvas/context, Math, Number, arrays, and plain objects. No document, network,
storage, navigation, dynamic code, workers, timers, sensors, audio, clipboard, console, external URLs,
or `requestAnimationFrame`. Keep source under 96 KiB. Physics, fixtures, units, assumptions, security,
and the fixed spec are immutable.

Visual contract:

- Create layered scene depth with at least three visible depth layers: a domain gradient, near/far
  bodies, and restrained ambient particles or texture. Never use a flat canvas.
- Make physical light beautiful and physically consistent using controlled glow, soft shadow, and
  true occlusion; never draw light through an opaque body. Show its subtle shadow cone.
- The trusted shell owns shell-driven parameter motion and calls `setParameter` with an advancing
  value. Render that value as the actual physical state so the subject visibly changes; decorative
  shimmer or twinkle alone MUST NOT satisfy motion. Modules must not own animation clocks, timers, or
  `requestAnimationFrame`. Across frames one second apart, the advancing value must change at least
  1.0% of pixels in the central 60% of the canvas, plus enough whole-canvas pixels to prove the scene
  is not frozen. A same-value redraw may settle reactive geometry but must not invent different
  physics. Freeze only nonessential decorative phase under reduced motion.
- Ensure the rendered subject agrees continuously with the first declared computed output across a
  full primary-parameter sweep. Similar adjacent computed outputs must never produce a visual cliff;
  in particular, curved illumination must draw the lit hemisphere on both sides of 180°.
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
physical light and occlusion, advancing value behavior, reactive feedback, readout chips,
reduced motion, and the curved terminator rule where applicable.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
