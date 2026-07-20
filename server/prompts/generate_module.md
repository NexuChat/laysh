# Laysh module generation stage

Return JSON; no tools. Assign once to `window.LayshSimulation`; no Markdown, full HTML/CSS.
Export exactly `version`, `init`, `setParameter`, `test`, `resize`, `destroy`;
`version` must be the number `1`.

`init(options)` receives `canvas`, `context`, `width`, `height`, `locale`, `reducedMotion`,
`emitFrame`, and `registerOverlayRect`; capture, draw, emit. Do not rename `context` to `ctx`.
`setParameter(name,value,timeSeconds)` redraws and emits synchronously. `timeSeconds` defaults
to zero and is the shell-owned PHENOMENON clock: it advances while auto-sweep is paused or the slider
held, freezing only for reduced motion. `test(inputs)` is pure and returns exactly declared outputs.

Use canvas/context, Math, Number, arrays, objects. No document/network/storage/navigation,
dynamic code/workers/timers/sensors/audio/clipboard/console/URLs/animation API. Modules
must not own animation clocks, timers, or `requestAnimationFrame`. Target 12–20 KiB; cap 40 KiB.

## FIRST-DRAFT ACCEPTANCE CONTRACT

Every item is measured; pass on draft one.

1. Model: implement every supplied fixture from all supplied input names; never substitute defaults
for provided inputs. Use exactly one model function per output; painter,
`test`, geometry, feedback, and readout share it. This SINGLE-SOURCE RULE forbids tuned painter math.
Across the full primary-parameter sweep a visible property follows output one with absolute rank correlation
≥ 0.65 and no false visual cliff or jump.

2. Actor: draw the declared actor—not label/glow/shadow/decoration—with its distinct solid RGB tracking signature.
Keep ≥8 signed pixels visible in ≥7 samples, a measurable centroid/extent, and never reuse
the RGB. Use only the declared action adapter:
`rotates|oscillates|orbits|propagates|flows|floats_sinks|phases|responds`.

3. Action: `responds` is the honest static-response action. Bind position/size/extent to
`tracking_output`: correlation ≥0.70, span ≥6 px or 15% pixel count; the held state stays stable.
Intrinsic actions use `timeSeconds`, independent of the parameter sweep, and continue at a held value:
span is at least 6 px (flows 2 px/0.08 s); oscillation uses its period, propagation shifts ¼ cycle at period/4,
and flow ratios match tested rates. The advancing value changes parameter state only. Shimmer/faster
sweep fail. One-second frames change 1.0% of the central 60% and clear freeze.

4. Mobile: at width ≤420 px draw at most one edge `essential-state` label, no numeric/duplicate state.
Call `registerOverlayRect` with exact bounds; height ≤22%, edge anchored, zero overlap with central
20%–80% subject or actor. Prefer zero canvas labels on mobile; shell owns readouts. Wide readout chips
obey the same safe band.

5. Scene: layered scene depth has at least three visible depth layers and reactive feedback beyond
text. Keep physical light physically consistent: never draw light through an opaque body; use a
subtle shadow cone, curved terminator, and smooth fills or gradients, never golf-ball dot patterns. Dual-view
labels when needed: `منظر علوي` / `كما يبدو من الأرض`.

Zero-heal examples:
- lever `responds`: required force moves the signed actor >6 px, stable when held; one mobile label.
- magnet `responds`: force indicator extent follows distance, stable when held; one mobile label.

Avoid recorded failures: rainbow labels; seasons sweep/luminance; evaporation static surface plus
particles; constant output; tuned painter; disappearing actor; binary threshold on smooth output.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
