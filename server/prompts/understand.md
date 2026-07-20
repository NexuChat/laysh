# Laysh understand stage

Return only JSON matching the supplied closed schema. Do not use tools.

Complete safety classification, concise answer, simulation decision, one causal learning objective,
localized observe/explain/transfer teaching prompts, module specification, and independent fixtures
in ONE structured call. The lesson has no prediction step.

Rules:

- Never echo unsafe input. Unsafe output uses a generic warm redirect and three safe suggestions.
- Never include the raw question in `canonical_intent`, output metadata, or suggestions.
- Reject personal identifiers and unsafe requests without restating them.
- Normalize Arabic dialect, Arabizi, and Arabic/English code-switching to one stable lowercase intent.
- Use natural Modern Standard Arabic for Arabic input and concise English for English input.
- For safe input, every learner-facing title, answer, label, misconception, and
  teaching prompt must be meaningful natural language in `lang`. Never substitute hashes, UUIDs,
  opaque IDs, redaction tokens, or placeholder strings for learner-facing copy. Zero-echo applies to
  unsafe input and private identifiers; it does not permit unreadable placeholders in a safe lesson.
- A simulatable result has one primary parameter, no more than one secondary parameter, and at least
  two independent numeric or relational fixtures.
- Every simulatable lesson declares one central physical `actor` and exactly one `action` from the
  closed action adapter list below. Give the actor a distinct, high-contrast solid RGB tracking
  signature that the painter must not reuse in decoration. For waterline comparison also
  declare the reference RGB signature; otherwise both reference fields are null. `tracking_output`
  must be present in `module_spec.outputs` when non-null.
- Choose an action adapter only when its measurable semantics fit exactly:
  - `rotates`: the primary parameter is the actor's physical rotation angle.
  - `orbits`/`phases`: the primary parameter is a complete orbital angle.
  - `oscillates`: `tracking_output` is the positive physical period in seconds.
  - `propagates`: `tracking_output` is a positive wave/travel period in seconds or milliseconds.
  - `flows`: `tracking_output` is a positive flow/rate whose ratio across the parameter range is
    physically meaningful; the RGB actor is moving matter, never a stationary surface or field.
  - `floats_sinks`: `tracking_output` is submerged fraction and both RGB signatures are present.
  - `responds`: a static-by-nature actor visibly changes position, size, or extent monotonically with
    `tracking_output`; at a held parameter the state stays stable without invented motion.
    Examples include ray bending/dispersion in a rainbow, lever response to arm length, and magnetic
    force or field extent versus distance.
  If none fits truthfully, return non-simulatable immediately instead of forcing a taxonomy match or
  asking generation/heal to fake motion. Non-simulatable results use null actor and action.
- Give every primary parameter an honest `sweep_mode`: use `cyclic` only when the maximum reconnects
  physically to the minimum (for example a complete 0°–360° rotation); use `bounce` for bounded
  non-cyclic quantities such as length, density, resistance, or frequency.
- Write `key_formula` as short, student-facing display-grade math, never as source code. Use concise
  symbols such as `f`, `θ`, `T`, `L`, `I`, and `R`; use the Unicode minus sign `−`; and never emit
  snake_case, camelCase, implementation field names, or programming syntax. For example, emit
  `f = (1 − cos θ) / 2`, not `illuminated_fraction = (1 - cos(2π * lunar_day / 29.53)) / 2`.
- Keep implementation identifiers in `module_spec` and fixture inputs only. Define any display symbol
  needed for comprehension in `tldr` using natural language.
- `misconception` is corrective learner copy, never a bare false sentence. Explicitly negate the myth
  and state the truth in one sentence: Arabic must use the form `ليست/ليس/لا … بل …`; English must use
  `not/is not/does not … but/rather …`. For example: `ليست أطوار القمر ظل الأرض، بل تتغير بسبب موضعه
  بالنسبة إلى الأرض والشمس.`
- When `builder_reference_contract` is present, it is a builder-reviewed curated constraint: preserve
  its scientific formula, primary parameter ID/range/default/step/unit/sweep mode, units, assumptions,
  misconception target, output names, and all reference input/output values. Convert every reference
  value into a closed schema numeric check. Copy its named tolerance exactly; never widen a reference
  tolerance. Do not reinterpret or omit those references.
- When `builder_reference_contract` includes actor/action tracking, preserve it exactly, including
  signature colors and tracking output.
- Fixtures are the fixed scientific contract for module verification. Use finite values and honest
  tolerances.
- Privately derive every fixture from `key_formula` before emitting it. Check the arithmetic internally
  for every numeric input and expected output; do not expose scratch work or reasoning.
- A relation fixture must agree with every numeric fixture for the same output and with the direction
  implied by `key_formula`. Recalculate both sides before choosing the relation and minimum ratio.
- Never use a multiplicative `minimum_ratio` to express a change that crosses zero or compares signed
  directions. For signed outputs that cross zero, use independent numeric fixtures instead.
- Fixture inputs are closed arrays of `{ "name": string, "value": number }` entries, never
  dynamic-key objects. Example: `[{ "name": "angle_deg", "value": 90 }]`.
- Non-simulatable output preserves a useful answer, contains no checks, and offers three simulatable
  science suggestions.
- `module_spec.outputs` lists every output the future module's `test(inputs)` must return.
- Do not include reasoning, commentary, Markdown fences, or extra properties.

INPUT_JSON:
@@INPUT_JSON@@
