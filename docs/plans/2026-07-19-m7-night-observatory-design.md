# M7 design: Night Observatory excellence upgrade

Status: owner-directed and implementation-ready. The decisions below translate
`UPGRADE-V1.1.md` into a testable product contract; they do not change Laysh's
trust, safety, answer-first, or evidence contracts.

## Experience thesis

Laysh should feel like a night observatory where a learner asks a small question
and watches a trustworthy instrument come alive. The web app and every portable
simulation share one visual language: deep-space ink, moonlight blue, warm amber,
cream type, orbital geometry, soft physical light, and restrained glass surfaces.
The first ten seconds must communicate one action, six instant examples, and a
living scientific scene.

## Design system

- Canvas: layered radial and linear gradients from `#05080b` to `#0e1c2b`, with
  CSS-only star fields and dashed orbital rings. Decorative motion stops when
  `prefers-reduced-motion` is enabled.
- Accents: `#58b7ff` for the Laysh dot and interaction, `#f6a94a` for primary
  actions and energy, `#eef4f8` for primary text, and `#7e93a6` for supporting
  text. Amber focus rings remain visible on every dark surface.
- Type: a self-hosted Arabic FreeSerif subset supplies the Naskh-flavoured
  display face; the existing self-hosted FreeSans subset remains the UI face.
  Arabic text never uses negative letter spacing.
- Surfaces: 16-20 px glass cards with subtle light borders, large soft shadows,
  and hover/focus responses that finish within 150 ms.
- Brand: the rendered mark is always `ليش` followed by a moonlight-blue dot and
  the Arabic promise is always `اسأل ليش، والعب الجواب.`

## Landing and navigation

The initial viewport contains a living orbital miniature, one question field,
one thumb-reachable primary action, and six horizontally swipeable luminous
golden cards. Golden playback stays in-page. View changes use short opacity and
transform transitions, never scroll jumps. User text keeps `dir=auto`; formulas,
identifiers, and technical fragments remain directionally isolated.

## Truthful agent theatre

The answer card remains the first substantive content. Every subsequent theatre
element is driven by an existing SSE payload:

- stage cards use the stage name, sanitized detail, and server elapsed time;
- verification chips are created only from received gate names;
- the self-heal act appears only after a real `healing` stage event;
- the `هل تعلم؟` interlude displays the answer summary emitted by understand;
- failure, reconnect, cancellation, and watchdog copy retain their distinct
  existing states.

The silhouette is decorative, not progress. There are no percentages, invented
logs, predicted completion times, or model reasoning.

## Portable simulation instrument

The trusted shell becomes a compact observatory instrument: dark glass controls,
readout chips, a framed stage, styled sliders/selects, and a projector/fullscreen
control. It owns a reduced-motion-aware animation scheduler that asks the module
to redraw with its current parameter value; generated modules may use that redraw
to advance visual-only idle phase but still may not own timers or animation APIs.
The public ABI and CSP remain unchanged.

The module source ceiling becomes 96 KiB. Generation and QA explicitly require:
layered scene depth, beautiful and physically consistent light, observable idle
motion, smoothly reactive feedback, and readable Arabic overlays. QA reports a
closed `visual_richness` checklist in addition to its existing correctness
verdict. Deterministic safety, fixture, interface, runtime, invariant, and browser
gates remain mandatory.

## Golden promotion

Each of the six P0 fixtures receives one initial generation plus at most two
regenerations. A candidate can replace a v1.0 pin only through an explicit v1.1
promotion path after deterministic verification, structured QA visual approval,
browser min/default/max checks, idle-motion evidence, and the builder review
checklist. Existing screenshots become the `before` record; accepted v1.1 mobile
and desktop captures become the `after` record. Live jobs cannot overwrite pins.

## Verification plan

Test-first coverage will enforce the palette and brand, responsive theatre hooks,
projector and scheduler behaviour, 96 KiB boundary, closed QA schema, prompt
requirements, explicit v1.1 golden replacement, and honest event mapping. Browser
acceptance covers 390x844 and 1440x900, keyboard/focus, reduced motion, contrast,
golden min/default/max/idle/reactive states, all designed failures, and the full
live journey. Accepted stage timings are compared with the same six v1.0 golden
fixtures; either understand or generate p95 exceeding its v1.0 counterpart by
more than 10% fails G7.

G7 produces screenshots and evidence for owner review. No release tag is created.
