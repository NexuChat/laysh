# Laysh module heal stage

Return only JSON matching the supplied module schema. Do not use tools.

Repair the module against the fixed understanding contract and exact gate failures below. Do not
change the answer, parameters, output names, fixtures, or teaching objective. Return module-only
JavaScript, never full HTML. Preserve the restricted interface and capabilities. Resolve every listed
failure, then provide safe summary and assumptions fields. Do not include reasoning or extra fields.

For every shared-model repair, retain `/* LAYSH_SHARED_MODEL: modelState */`. In both draw and
`test(inputs)`, bind `const state = modelState(...)`, then read `state.<declared_output>` when drawing
and returning outputs; a bare call or duplicate formula does not repair the gate.

Preserve or repair the shared post-fit scene evidence after every fitted draw with this exact closed
shape, replacing only identifiers and finite values:
`canvas.__layshSceneGeometry = [{ schemaVersion: "1.0", phase: "post_fit",
viewport: { width, height, safeInset: 0 }, state: { id: "frame", timeMs: 0 },
objects: [{ id: "actor", scientific: true,
geometry: { type: "circle", cx, cy, radius }, clippingPolicy: "forbid" }], relations: [] }]`.
`state` must never be null; circle is the only supported geometry. Add every scientific body and
declare each pair's overlap/contact/clearance policy. `scientific_occlusion` is allowed only for
physically intended overlap. Recompute after every clamp or fit and resolve every
`scene_geometry` failure exactly.

The v1.1 visual quality is part of the fixed contract and must survive every repair: preserve or add
at least three scene-depth layers, physically consistent curved illumination and occlusion, a private
visual phase advanced by the trusted shell's same-value redraw when reduced motion is off, smooth
parameter-linked reactive feedback, and stable conceptual labels. The prediction must be visibly
testable at minimum, midpoint, and maximum through the declared actor's causal action, not only text,
a marker, a frame counter, or decorative motion. Never draw changing numbers, percentages, or live
readout values on the canvas. The trusted shell owns the live numeric readout below the scene. The
module still owns no timers or animation APIs. Fixing a deterministic gate must never flatten or
visually regress the scene.

HEAL_INPUT_JSON_WITH_EXACT_GATE_FAILURES:
@@INPUT_JSON@@
