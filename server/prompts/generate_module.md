# Laysh module generation stage

Return only JSON matching the supplied closed schema. Do not use tools.

Generate only the phenomenon-specific JavaScript assigned exactly once to
`window.LayshSimulation`. Do not return full HTML, CSS, trusted-shell UI, or Markdown.

The object must contain exactly `version`, `init`, `setParameter`, `test`, `resize`, and `destroy`.
`version` must be the number `1`. `init(options)` receives `canvas`, `context`, `width`, `height`,
`locale`, `reducedMotion`, and `emitFrame`; capture those exact property names and draw immediately.
Do not rename `context` to `ctx`. `setParameter(name, value)` receives the declared parameter ID and
must redraw synchronously.
Use only the supplied canvas/context, Math, Number, arrays, and plain objects. Do not use document,
network, storage, navigation, dynamic code, workers, timers, sensors, audio, clipboard, console, or
external URLs. `init` draws synchronously and calls `emitFrame`. `setParameter` redraws and calls the
captured `emitFrame`. `test(inputs)` is deterministic, has no visible side effects, and returns exactly
the declared finite outputs. Honor reduced motion by keeping same-value redraws visually still. Keep
source under 96 KiB.

Visual quality rules for the canvas module:

- Build layered scene depth, never a flat single-color canvas. Combine a domain-appropriate gradient,
  near and far bodies, and restrained ambient texture or particles: stars for astronomy, water
  light-play for buoyancy, workshop glow for circuits, or an equally relevant physical setting.
- Make physical light beautiful and physically consistent. Use soft shadows, controlled glows, and
  visible occlusion. A sun may have a corona, a filament may visibly heat, and a waveform may leave a
  luminous trail, but every effect must still encode the fixed model.
- Include subtle idle motion that makes the instrument feel alive before interaction. The trusted
  shell supplies a same-value redraw about twelve times per second; advance a private visual-only
  phase on that redraw when `reducedMotion` is false. Never use timers, `requestAnimationFrame`, or any
  hidden change to `test(inputs)` or its physics.
- Add smooth reactive feedback tied directly to parameter changes: eased geometry, fading trails,
  ripple rings, or particle speed proportional to the declared quantity. Preserve the previous
  displayed parameter locally so each redraw can interpolate without changing `test(inputs)`.
- Render readable Arabic or English readout chips near the action, with a translucent backing and
  concise labels. Do not leave raw numbers floating in canvas corners.
- Before returning, self-check the implementation itself (not just the plan): the draw path must
  contain at least three visible depth layers; a private `visualPhase` must visibly affect a subtle
  coordinate, opacity, shimmer, or trail and advance on a same-value redraw only when reduced motion
  is off; parameter changes must alter more than a text label; and at least one rounded translucent
  readout chip must be drawn beside the phenomenon.
- Use smooth fills or gradients for continuous bodies and surfaces; never use golf-ball dot patterns
  as a substitute for shading.
- In light-and-shadow models, never draw light through an opaque body. Show a subtle shadow cone on
  the physically occluded side and keep illumination consistent in every view.
- On illuminated spheres, use a curved terminator or an equivalent physically plausible lit mask;
  never fake a phase with a rectangular clip or straight vertical cut.
- If one canvas mixes a schematic with an observer view, label the views in the lesson language.
  Arabic labels use `منظر علوي` and `كما يبدو من الأرض`; English labels use `Top view` and
  `View from Earth`.
- Keep labels precise, legible, and within the canvas. Depict only claims supported by the fixed
  formula, fixtures, and assumptions. Visual motion may add atmosphere but must not add an unsupported
  causal claim.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
