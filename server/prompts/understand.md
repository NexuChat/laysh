# Laysh understand stage

Return only JSON matching the supplied closed schema. Do not use tools.

Complete safety classification, concise answer, simulation decision, one causal learning objective,
localized teaching prompts, module specification, and independent fixtures in ONE structured call.

Rules:

- Never echo unsafe input. Unsafe output uses a generic warm redirect and three safe suggestions.
- Never include the raw question in `canonical_intent`, output metadata, or suggestions.
- Reject personal identifiers and unsafe requests without restating them.
- Normalize Arabic dialect, Arabizi, and Arabic/English code-switching to one stable lowercase intent.
- Use natural Modern Standard Arabic for Arabic input and concise English for English input.
- For safe input, every learner-facing title, answer, label, prediction, choice, misconception, and
  teaching prompt must be meaningful natural language in `lang`. Never substitute hashes, UUIDs,
  opaque IDs, redaction tokens, or placeholder strings for learner-facing copy. Zero-echo applies to
  unsafe input and private identifiers; it does not permit unreadable placeholders in a safe lesson.
- A simulatable result has one primary parameter, no more than one secondary parameter, and at least
  two independent numeric or relational fixtures.
- Write `key_formula` as short, student-facing display-grade math, never as source code. Use concise
  symbols such as `f`, `θ`, `T`, `L`, `I`, and `R`; use the Unicode minus sign `−`; and never emit
  snake_case, camelCase, implementation field names, or programming syntax. For example, emit
  `f = (1 − cos θ) / 2`, not `illuminated_fraction = (1 - cos(2π * lunar_day / 29.53)) / 2`.
- Keep implementation identifiers in `module_spec` and fixture inputs only. Define any display symbol
  needed for comprehension in `tldr` using natural language.
- When `builder_reference_contract` is present, it is a builder-reviewed curated constraint: preserve
  its scientific formula, primary parameter ID/range/default/step/unit, units, assumptions,
  misconception target, output names, and all reference input/output values. Convert every reference
  value into a closed schema numeric check. Copy its named tolerance exactly; never widen a reference
  tolerance. Do not reinterpret or omit those references.
- Fixtures are the fixed scientific contract for module verification. Use finite values and honest
  tolerances.
- Privately derive every fixture from `key_formula` before emitting it. Check the arithmetic internally
  for every numeric input and expected output; do not expose scratch work or reasoning.
- A relation fixture must agree with every numeric fixture for the same output and with the direction
  implied by `key_formula`. Recalculate both sides before choosing the relation and minimum ratio.
- Fixture inputs are closed arrays of `{ "name": string, "value": number }` entries, never
  dynamic-key objects. Example: `[{ "name": "angle_deg", "value": 90 }]`.
- Non-simulatable output preserves a useful answer, contains no checks, and offers three simulatable
  science suggestions.
- `module_spec.outputs` lists every output the future module's `test(inputs)` must return.
- Do not include reasoning, commentary, Markdown fences, or extra properties.

INPUT_JSON:
@@INPUT_JSON@@
