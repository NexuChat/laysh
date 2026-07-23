---
name: model-lab-scientific-canvas
description: Build a visually rich, scientifically causal Canvas simulation for the isolated Laysh model lab.
---

# Model Lab scientific Canvas

`MODEL_LAB_SCIENTIFIC_CANVAS_SKILL_V1`

This skill is used only by the isolated model-comparison lab. Produce the complete
JavaScript simulation module, not HTML, CSS, Markdown, or an explanation.

## Scientific direction

1. Read the fixed understanding and physics fragment as immutable scientific input.
2. Choose the clearest visual proof, not the easiest collection of generic shapes.
   Show the cause, the interaction, and the observable outcome in one coherent scene.
3. Write the exact marker `/* LAYSH_SHARED_MODEL: modelState */`, then use one
   pivotal `modelState(input)` function as the single source for both `test(inputs)`
   and every scientifically meaningful visual.
4. The primary control must visibly and continuously change the scientific actor at
   minimum, middle, and maximum values. A moving background, decorative particles,
   changing text, or a frame counter is not evidence.
5. When a physical effect is too small to see honestly, add a clearly labelled inset
   or a fixed magnification disclosure. Never silently exaggerate the physics.
6. Use the supplied fixtures as numerical anchors. If the physics fragment conflicts
   with a fixture, prefer the fixture and fixed understanding and disclose the
   simplifying assumption.

## Art direction

1. Compose a real scene with foreground, subject, and background depth. Prefer
   recognizable silhouettes, paths, curves, gradients, controlled glow, occlusion,
   shadows, and restrained texture over stacks of circles and rectangles.
2. Draw with the full supported Canvas 2D vocabulary: paths, bezier curves,
   transforms, gradients, line caps/joins, clipping, and compositing.
3. Reserve clear safe lanes for at most two stable labels. Never place changing
   numbers, percentages, or readouts over the illustration; the trusted shell owns
   those below the canvas.
4. Design responsively from normalized anchors. Keep the scientific actor visible
   and unclipped at narrow mobile and wide desktop sizes and at 200% zoom.
5. Use the optional third `setParameter(name, value, elapsedMs)` argument for smooth
   causal or idle movement. Clamp the timestep. In reduced motion, render a clear
   causal state without continuous motion.
6. Make reset, resize, pause, and destroy deterministic. Own no timers or animation
   frames; the trusted shell supplies the clock and stops it.

## Runtime boundary

- Assign exactly once to `window.LayshSimulation`.
- Export exactly `version`, `init`, `setParameter`, `test`, `resize`, and `destroy`.
- Use only the supplied canvas/context, numbers, arrays, plain objects, and Math.
- No DOM access, network, storage, navigation, URLs, workers, sensors, audio,
  dynamic code, timers, or model-created HTML.
- Keep source within 96 KiB and draw the first complete frame during `init`.
- Emit a frame after every draw.
