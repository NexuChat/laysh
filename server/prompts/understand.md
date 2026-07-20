# Laysh understand stage

Return only JSON matching the supplied closed schema. Do not use tools. Complete the answer and the
small fixed contract needed by generation in ONE structured call. The lesson has no prediction step.

Safety and answer:

- Never echo unsafe input or personal identifiers. Unsafe output uses a generic warm redirect and
  three safe science suggestions. Do not put the raw question in identifiers or suggestions.
- Normalize equivalent Arabic, Arabizi, code-switched, and English questions to a stable lowercase
  `canonical_intent`. Use natural Modern Standard Arabic for `lang=ar` and concise English otherwise.
- Keep `tldr` to two short age-appropriate sentences. `key_formula` is optional display-grade math,
  using student symbols and Unicode minus sign `−`; never emit snake_case or programming syntax.
  Example: `f = (1 − cos θ) / 2`.
- Write `misconception` as a correction, not a bare myth: Arabic `ليست/ليس/لا … بل …`; English
  `not/is not/does not … but/rather …`.

Simulation decision and generation inputs:

- Simulate only one honest causal variable with one `primary_parameter`, at most one secondary,
  `module_spec.outputs`, and at least two independent numeric or relational `checks`. Otherwise return
  non-simulatable answer-only output with null actor/action/parameters, no checks, and three suggestions.
- Do not require the whole phenomenon to have only one cause. A complex or multi-stage topic is
  simulatable when the lesson can isolate one honest parameter-to-output slice with explicit simplifying
  assumptions, such as wavelength to ray deviation, arm length to required force, or distance to force.
- A static actor is not a reason to reject a measurable causal relation. Use `responds` with a
  signed indicator or actor geometry whose position, size, or extent visibly follows the declared output.
- Declare one physical `actor` with a distinct high-contrast solid RGB `tracking_signature` that is
  not decoration. Set `tracking_output` to an item in `module_spec.outputs`. Reference RGB fields are
  both present only for `floats_sinks`; otherwise both are null.
- Choose exactly one action adapter by measurable semantics: `rotates`, `orbits`, and `phases` require a
  complete physical angle; `oscillates` and `propagates` require a positive period/duration output;
  `flows` requires a positive physical matter-flow rate; `floats_sinks` requires submerged fraction;
  `responds` is the honest static-response action for an actor whose position, size, or extent changes
  monotonically with an output and stays stable at a held parameter. If none fits, do not simulate.
- Use `sweep_mode` value `cyclic` only when max reconnects physically to min; otherwise use `bounce`.

Fixture integrity:

- `test(inputs)` will be built from `checks`, so privately derive every fixture from `key_formula`.
  Check the arithmetic internally. Numeric fixtures use closed arrays of
  `{ "name": string, "value": number }`. A relation fixture must agree with every numeric fixture and
  formula direction. Never use a ratio when the result crosses zero or compares signed direction.
- When `builder_reference_contract` is present, preserve its formula, parameter, actor/action,
  signatures, outputs, assumptions, values, units, and tolerances exactly; never widen or omit them.

Do not include reasoning, commentary, Markdown fences, placeholders, or extra properties.

INPUT_JSON:
@@INPUT_JSON@@
