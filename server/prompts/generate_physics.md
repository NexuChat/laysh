Return closed-schema JSON only. Do not use tools or Markdown.

Produce a declarative physics fragment, never JavaScript. The required fields are
`physics_expressions`, `output_names`, `brief_summary`, and `assumptions`.
`physics_expressions` is an ordered array of `{name, expression}`. Its names and
`output_names` must both exactly equal the ordered `module_spec.outputs` list.

Each expression is one safe mathematical expression. It may use only declared
parameter IDs and `pi`, finite numeric literals, parentheses, unary `+`/`-`, binary
`+`, `-`, `*`, `/`, `%`, `**`, and these calls: `abs`, `acos`, `asin`, `atan`,
`atan2`, `ceil`, `clamp`, `cos`, `exp`, `floor`, `log`, `log10`, `max`, `min`, `pow`,
`round`, `sin`, `sqrt`, `tan`. Do not use `Math`, attributes, indexing, lambdas,
variables other than declared parameter IDs, code, comments, or statements. The
trusted assembler parses and compiles expressions and owns all runtime state and ABI.
For fixed quantities such as gravity, density, area, or a coefficient, write scientific
constants as finite numeric literals inside the expression and disclose their meaning
in `assumptions`; never invent a symbolic alias for a fixed quantity.

Treat the first ordered `module_spec.outputs` entry as the learner-facing readout.
It must respond to changes in the parameter named by `primary_parameter.id` while
every other declared parameter is held at its declared default. Do not make the first
output depend only on a secondary parameter or correlate two controls to create an
apparent change.

Derive every fixture from the stated formula and honor its tolerance. Keep the fixed
lesson contract immutable. Keep `brief_summary` under 240 characters and list only
honest simplifying assumptions. Do not echo the learner's raw question.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
