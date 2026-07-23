Return closed-schema JSON only; use no tools and no Markdown.

This is the isolated Model Lab Direct Canvas Studio. The fixed understanding and the
independent physics fragment are already supplied. Produce one finished JavaScript
Canvas simulation module immediately. Do not return a declarative drawing fragment,
HTML, CSS, shell UI, analysis, alternatives, or a code fence.

The following runtime skill is authoritative for this lab call:

MODEL_LAB_RUNTIME_SKILL:
@@SKILL_TEXT@@

Module ABI and runtime:

- Assign exactly once to `window.LayshSimulation` and return the source in `module_js`.
- Export exactly `version`, `init`, `setParameter`, `test`, `resize`, and `destroy`;
  `version` is the number `1`.
- `init(options)` receives `canvas`, `context`, `width`, `height`, `locale`,
  `reducedMotion`, and `emitFrame`; draw a complete first frame immediately.
- Keep the identifier `context`; do not rename it to `ctx`.
- Implement `setParameter(name, value, elapsedMs)` with a clamped optional timestep.
  The trusted shell owns animation scheduling. Do not create timers or animation
  frames.
- `test(inputs)` is pure, deterministic, side-effect free, and returns exactly the
  ordered output names declared by the fixed module specification.
- `resize(nextWidth, nextHeight)` recomputes the responsive layout and redraws.
- `destroy()` drops references and leaves no work running.

Single scientific source of truth:

- Write the exact comment `/* LAYSH_SHARED_MODEL: modelState */`, followed
  immediately by one named pure `modelState(input)` function. Do not translate,
  expand, or annotate the marker.
- `test(inputs)` and drawing must call that same function. Never duplicate or
  cosmetically fake the pivotal relationship.
- Treat the physics fragment as the starting scientific implementation. Check it
  against the fixed fixtures before writing the module. The fixed understanding and
  fixtures win if there is a conflict.
- Map the primary parameter through its full declared range. Minimum, midpoint, and
  maximum must yield visibly distinct scientific states, not just a text/readout
  change.

Visual production bar:

- Choose a domain-appropriate scientific visual proof and build a recognizable scene,
  not a generic icon. Show cause → interaction → observable consequence.
- Use supported Canvas paths, arcs, ellipses, bezier curves, gradients, transforms,
  clipping, shadows, line caps/joins, and compositing where they improve clarity.
- Use at least three meaningful depth layers and a restrained palette with strong
  subject/background contrast. Physical light must respect occlusion.
- Keep the scientific actor within a responsive safe region. Recompute all geometry
  after fit/clamp on every draw and resize.
- Draw at most two short stable labels in clear lanes. Never draw changing numbers,
  slider values, percentages, or live readouts over the scene.
- If a necessary effect is magnified, disclose the fixed factor visibly; never distort
  silently.
- Use `elapsedMs` for smooth motion only when motion teaches the mechanism. Clamp each
  step to 100 ms. Reduced-motion mode still shows a causally legible static state.

Hard safety boundary:

- Use only canvas/context, Math, Number, arrays, strings, and plain objects.
- No document, network, storage, navigation, external URLs, dynamic code, workers,
  timers, sensors, audio, clipboard, console, or `requestAnimationFrame`.
- Keep UTF-8 source at or below 96 KiB.

`canvas.__layshSceneGeometry is optional` in this isolated studio. Spend the source
budget on the actual scientific scene, not invented metadata. If you already know the
closed v1.0 scene-geometry contract exactly, you may emit an array of truthful
`post_fit` samples after the final clamp; otherwise omit it. A small truthful
`canvas.__layshActorResponse` object is also optional. Never compromise or simplify
the drawing merely to manufacture metadata.

Before returning, perform this short operational self-check:

- Return exactly OUTPUT_NAMES_JSON from `module_spec.outputs`, in the same order, in
  the top-level `output_names` array.
- `test(inputs)` returns every one of those names as a finite number at every supplied
  numeric fixture.
- The exact shared-model marker and exact six-key ABI appear once.
- `init`, the minimum control value, and the maximum control value all draw without
  throwing and visibly change the scientific state.

UNDERSTANDING_JSON:
@@INPUT_JSON@@

PHYSICS_FRAGMENT_JSON:
@@PHYSICS_JSON@@

DISCOVERY_PLAN_JSON:
@@DISCOVERY_JSON@@
