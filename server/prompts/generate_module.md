# Laysh module generation stage

Return only closed-schema JSON; do not use tools. Generate only phenomenon JavaScript assigned once
to `window.LayshSimulation`, never Markdown, full HTML, CSS, or shell UI.

Export exactly `version`, `init`, `setParameter`, `test`, `resize`, `destroy`.
`version` must be the number `1`.
`init(options)` receives `canvas`, `context`, `width`, `height`, `locale`, `reducedMotion`, and
`emitFrame`; capture those exact names. Do not rename `context` to `ctx`; draw immediately.
`setParameter(name, value, timeSeconds)` redraws synchronously. The shell owns `timeSeconds`; default
an omitted value to zero and never create a module clock. Both draw paths call `emitFrame`.
`test(inputs)` is deterministic, side-effect free, and returns exactly the declared finite outputs.

Use only supplied canvas/context, Math, Number, arrays, and plain objects. No document, network,
storage, navigation, dynamic code, workers, timers, sensors, audio, clipboard, console, external URLs,
or `requestAnimationFrame`. Keep source under 96 KiB. Fixed physics, fixtures, units, assumptions,
security, parameters, actor, action, and spec are immutable.

Visual contract:

- Create layered scene depth with at least three visible depth layers: domain gradient, near/far
  bodies, and restrained texture. Never use a flat canvas.
- Make physical light beautiful and physically consistent with glow, soft shadow, and true
  occlusion; never draw light through an opaque body. Show its subtle shadow cone.
- shell-driven parameter motion supplies an advancing value. Render it as actual subject state;
  shimmer alone fails. Modules must not own animation clocks, timers, or `requestAnimationFrame`.
  One-second frames must change at least 1.0% of the central 60% plus the whole-canvas freeze floor.
  Same-value redraws may settle geometry but not invent physics. Reduced motion freezes decoration.
- Draw the actor/feature with its exact solid RGB tracking signature, large enough for a stable pixel
  centroid; never reuse that color. The actor itself performs the declared action. For `oscillates`,
  shell time continuously drives the tested period while the slow parameter sweep rides on top.
- The subject agrees with the first computed output across the full primary-parameter sweep, with no
  visual cliff; curved illumination remains continuous across 180°.
- Add smooth parameter-linked reactive feedback (eased geometry, trail, ripples, or particles) and
  preserve the prior display value. Parameter changes must alter more than text.
- Draw rounded translucent readout chips with localized labels. Shade bodies with
  smooth fills or gradients, never golf-ball dot patterns. Spheres need a curved terminator,
  not rectangular clips.
- If schematic and observer views coexist, label them `منظر علوي` / `كما يبدو من الأرض` or
  `Top view` / `View from Earth`. Keep every label legible and inside the canvas.
- SINGLE-SOURCE RULE: every physics-critical visual property (angle, lit fraction, submerged
  fraction, phase, flow speed) comes from the same model function used by `test(inputs)` and fixtures.
  Any parallel painter formula is a contract violation.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
