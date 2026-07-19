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
- A simulatable result has one primary parameter, no more than one secondary parameter, and at least
  two independent numeric or relational fixtures.
- Fixtures are the fixed scientific contract for module verification. Use finite values and honest
  tolerances.
- Non-simulatable output preserves a useful answer, contains no checks, and offers three simulatable
  science suggestions.
- `module_spec.outputs` lists every output the future module's `test(inputs)` must return.
- Do not include reasoning, commentary, Markdown fences, or extra properties.

INPUT_JSON:
@@INPUT_JSON@@

