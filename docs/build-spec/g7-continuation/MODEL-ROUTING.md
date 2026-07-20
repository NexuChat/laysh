# GPT-5.6 routing policy

## Objective

Use the least intensive GPT-5.6 variant and reasoning effort that reliably
passes the required gates. Do not infer account quota consumption from the
model name alone; route from measured quality, latency, retries, and observed
usage when that evidence is available. Sol is an escalation path, not the
default for every task.

## Build-session routing

| Work | Model | Effort | Rule |
|---|---|---:|---|
| Root continuation, integration, ordinary debugging | `gpt-5.6-terra` | medium/high | Default lane. Keep the root Session ID. |
| Mechanical documentation, fixture normalization, deterministic bookkeeping | `gpt-5.6-luna` | low/medium | Use only when the task is fully specified and isolated. |
| Ambiguous architecture, security boundary, difficult cross-cutting failure, final critical review | `gpt-5.6-sol` | high | Escalate only with a recorded reason. |

Do not use maximum reasoning by default. Increase effort only after a concrete
failure demonstrates that the current lane is insufficient.

## Product-runtime routing

| Runtime stage | Route | Escalation rule |
|---|---|---|
| Understand and classify | `gpt-5.6-luna`, low | Terra only after a measured schema or classification failure; retain safe deterministic fallback behavior. |
| Generate a simulation module | Deterministic complexity tier: Terra for an evaluated eligible tier; Sol directly for a tier that has not met the Terra gate. | Do not pay for a known-to-fail Terra draft before Sol. Change the tier boundary only from recorded benchmark evidence. |
| Heal | First attempt uses the generation model with exact deterministic diagnostics. | One Sol final attempt is allowed only after the first heal fails, the artifact remains eligible, and the total job budget permits it. |
| Structured visual QA | `gpt-5.6-terra`, low/medium | Sol only when a closed verdict is inconclusive and the candidate is release-critical. |

Deterministic gates remain authoritative. Model QA supplements schema,
security, physics, browser, accessibility, and actor-motion checks; it does not
replace them.

The repository's runtime defaults must not be changed merely because this table
names a preferred route. First establish a bounded evaluation set and explicit
pass criteria. A route is accepted only when end-to-end success rate, total
model calls including heals, elapsed time, and account-observed usage are no
worse than the route it replaces within declared tolerances.

## Spend controls

- Offline tests and hand-authored fixtures run before any live model call.
- A live call must name the acceptance row it is proving.
- Set a per-run maximum call count and abort conditions before live evaluation.
- Retry only demonstrably transient failures.
- Never regenerate a candidate that already passes merely for aesthetic
  variation during the release window.
- Record model, effort, elapsed time, result, heal count, and quota-relevant
  deviation without recording secrets or learner input.
- Record each stage separately. A single “effective model” value must not hide
  which model performed understanding, generation, healing, or visual QA.
- Enable a fast service tier only if the active catalog exposes it and an A/B
  measurement confirms acceptable quality and quota behavior.
