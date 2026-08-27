Return closed-schema JSON only; use no tools. Assign JavaScript once to
`window.LayshSimulation`; no Markdown, full HTML, CSS, or shell UI.

Actor recognizable as `module_spec.actor` without relying on text labels;
no generic circle, orb, or rectangle. Concept-specific silhouette:
`floating_body` hull crossing water; `wavefront` propagating front or ray bundle.

Export exactly `version`, `init`, `setParameter`, `test`, `resize`, and `destroy`; `version` must be the number `1`.
`init(options)` receives `canvas`, `context`, `width`, `height`, `locale`,
`reducedMotion`, and `emitFrame`; draw immediately. Do not rename `context` to `ctx`.
`setParameter(name, value)` redraws and calls `emitFrame`; `test(inputs)` is deterministic,
side-effect free, and returns exactly declared finite outputs.

After `/* LAYSH_SHARED_MODEL: modelState */`, define one pure named state-object function. Render
and `test(inputs)` call the same model function: `const state = modelState(value);`; use real
`state.output` for pivotal visuals; no duplicate formula or no-op call.

After each fit/clamp set `canvas.__layshSceneGeometry` from the final drawn geometry. This is the
single most-failed contract, so follow it literally.

Every object is closed: an unknown key anywhere fails the whole sample array. Allowed keys, and no
others — sample: `schemaVersion`, `phase`, `viewport`, `state`, `objects`, `relations`; state: `id`,
`timeMs`; object: `id`, `scientific`, `geometry`, `clippingPolicy`; circle: `type`, `cx`, `cy`,
`radius`; relation: `objects`, `overlapPolicy`, `contactPolicy`, `minimumClearance`.

`state` is a trap: it is NOT the physical state and NOT what `modelState()` returns. It only names
the sample — `id` (nonempty string) and `timeMs` (finite, >= 0). An angle, fraction, output or any
measurement inside it fails every sample; physics lives in geometry and `canvas.__layshActorResponse`.

One body:
`[{ schemaVersion: "1.0", phase: "post_fit", viewport: { width, height, safeInset: 0 },`
`state: { id: "primary", timeMs: 0 }, objects: [{ id: "actor", scientific: true,`
`clippingPolicy: "forbid", geometry: { type: "circle", cx, cy, radius } }], relations: [] }]`

Many bodies extend that shape; never invent `from`/`to`/`type`/`bounds`. Declare every pair once —
three objects means three relations:
`objects: [{ id: "moon", … }, { id: "sun", … }], relations: [{ objects: ["moon","sun"],`
`overlapPolicy: "scientific_occlusion", contactPolicy: "forbid", minimumClearance: 0 }]`

`scientific_occlusion` with zero clearance is the correct way to say one body hides another, as in
an eclipse or transit; it expresses physical intent only. Every pair carries its own
overlap/contact/clearance policy. Report only pivotal scientific bodies. Do not report decorative
particles, glows, text, chips, trails, or texture.

Use only canvas/context, Math, Number, arrays, and plain objects; no document, network, storage,
navigation, dynamic code, workers, timers, sensors, audio, clipboard, console, URLs, or
`requestAnimationFrame`. Keep source ≤96 KiB in UTF-8 bytes; fixed physics/spec is immutable.

Create layered scene depth: at least three visible depth layers—gradient, near/far bodies, and
restrained texture; never flat. Make physical light beautiful and physically consistent;
never draw light through an opaque body; show glow, true occlusion, soft shadow, and a
subtle shadow cone. Add
subtle idle motion via private `visualPhase` on the shell's ~12 fps same-value redraw, only outside
reduced motion; visual-only, never physics or `test(inputs)`. Add reactive feedback to parameter changes:
preserve the prior display value and change more than text.
- Never draw changing numbers, percentages, or live readout values on the canvas. The trusted shell
  owns the live numeric readout below the scene. Keep readout chips outside the drawing, especially
  on narrow mobile viewports, so they cannot cover the actor; stable labels are allowed.
  If geometry is amplified, label its numeric factor (for example `×100`) on-canvas; never distort
  silently; this fixed disclosure is not a live readout.
Shade continuous bodies with smooth fills or gradients, never golf-ball dot patterns; illuminated
spheres need a curved terminator or equivalent physical mask, never a rectangular clip. If
schematic and observer views share a canvas, label them `منظر علوي` / `كما يبدو من الأرض` or `Top
view` / `View from Earth`; keep labels inside the canvas.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
