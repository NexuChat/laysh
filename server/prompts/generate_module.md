# Laysh module generation stage

Return closed JSON only; no tools. Assign JavaScript once to
`window.LayshSimulation`; no Markdown, full HTML, CSS, or shell UI.

Export exactly `version`, `init`, `setParameter`, `test`, `resize`, `destroy`.
`version` must be the number `1`.
`init(options)` receives `canvas`, `context`, `width`, `height`, `locale`, `reducedMotion`,
`emitFrame`, and `registerOverlayRect`; capture them. Do not rename `context` to `ctx`; draw now.
`setParameter(name, value, timeSeconds)` redraws synchronously. `timeSeconds` is the shell-owned
PHENOMENON clock: it advances while auto-sweep is paused or the slider held, and freezes only for
`reducedMotion`. Default it to zero; never create a clock. Both draw paths call
`emitFrame`. `test(inputs)` is pure and returns exactly the declared finite outputs.
Implement and mentally check every supplied fixture in `test(inputs)` before drawing anything.

Use only canvas/context, Math, Number, arrays, and objects. No document, network, storage, navigation,
dynamic code, workers, timers, sensors, audio, clipboard, console, URLs, or animation API.
Target 12–20 KiB; 40 KiB is the hard cap. Fixed inputs/spec are immutable.

Pass measurable gates before visual polish:

- Draw the actor with its distinct solid RGB tracking signature and stable centroid; never reuse it.
  Make intrinsic motion legible without a faster fake sweep. Rates obey `T = 2π√(L/g)`, `v = λf`,
  and tested flow; state an honest visual time scale when needed.
- Adapter: `rotates`/`orbits`/`phases` use the primary angle; `oscillates`/`propagates` use the
  tracking period; `flows` uses its rate. `responds` binds actor position/size/extent to
  `tracking_output`; when held, the held state stays stable without fake motion. `floats_sinks`
  preserves equilibrium.
- SINGLE-SOURCE RULE: angle, lit/submerged fraction, phase, and flow speed use the same model function
  as `test(inputs)` and fixtures; no parallel painter formula.
- Keep two motions distinct: parameter changes come only from the advancing value; intrinsic action
  (`oscillates`, `propagates`, `rotates`, `orbits`/`phases`, `flows`) comes from `timeSeconds` and MUST
  continue at a held value. Shimmer fails. Modules must not own animation clocks, timers, or
  `requestAnimationFrame`.
  One-second frames change 1.0% of the central 60% and clear the whole-canvas freeze floor.
  Same-value redraws do not invent physics. Reduced motion freezes decoration.
- The subject agrees with the first output across the full primary-parameter sweep, with no visual cliff;
  curved illumination stays continuous across 180°.
- Create layered scene depth with at least three visible depth layers: gradient, bodies, texture.
- Keep physical light physically consistent; never draw light through an opaque body. Show its subtle shadow cone.
- Add parameter-linked reactive feedback (eased geometry, trail, ripples, or particles); parameter
  changes alter more than text.
- At 420px or wider, readout chips use at most 22% height and never overlap the central 20%-80% subject. Call
  `registerOverlayRect({x,y,width,height,role})`; role is `essential-state` or `readout`. Scale text
  from canvas size without exceeding the band.
- Below 420px, draw at most ONE edge `essential-state` label; no numeric or duplicate state.
  Use smooth fills or gradients, never golf-ball dot patterns. Spheres need a curved terminator.
- Dual views: `منظر علوي` / `كما يبدو من الأرض`.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
