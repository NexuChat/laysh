# Requirements audit

**Audited:** 2026-07-20  
**Target:** clean G7 baseline `828fe4d99dfd516c3fea7a028fc6e4b306199702`

This audit records baseline gaps that justify continuation requirements. It is
not implementation guidance from a later code version.

## Confirmed baseline gaps

| Finding | Baseline observation | Requirement response |
|---|---|---|
| Generated-source limit can disagree | `module.schema.json` allows 40,960 characters while the verifier enforces 96 KiB; the local project skill also says 40 KiB. | `CONTRACT-01` requires one canonical byte limit and boundary tests. |
| Browser motion evidence is too weak | The probe accepts an incremented frame counter and one control change; decorative animation can pass. | `MOTION-02` and `MOTION-03` require actor trajectories, negative fixtures, and per-lesson physics evidence. |
| Prediction gates the control | The existing shell enables the primary control only after a prediction choice. | `TEACH-02` requires control before prediction in unit and browser journeys. |
| Misconception copy can present falsehood alone | Existing fixtures and shell render an unlabeled misconception string without a required correction. | `TEACH-01` requires localized labeling and explicit correction. |
| Generated shares are process-local | Generated artifacts are held in an in-memory map and the download route becomes unavailable after restart. | `SHARE-01` and `SHARE-02` require privacy-safe durable lookup, retention, and closed failure. |
| Model evidence can be ambiguous | The public `effective_model` is derived from the last non-mock stage, which can be heal or QA rather than generation. | `EVID-02` requires stage-by-stage receipts. |
| Runtime generation is Sol-heavy | Baseline defaults use Sol for generation, heal, and QA without a committed tier evaluation. | `ROUTE-01` and `ROUTE-02` require measured routing and prevent speculative Terra-then-Sol double calls. |
| Project skill is stale | The committed `sim-quality` checklist still requires prediction before exploration and a 40 KiB cap. | Delivery step 1 and `CONTRACT-01` require reconciling it before use. |
| Localization is incomplete | The gallery accepts a locale, while the main client and simulation shell are not yet proven bilingual across every core and failure path. | `I18N-01` and `I18N-02` require inventory, snapshots, direction, and event-scope tests. |

## Audit corrections

- The acceptance matrix originally contained 24 rows as stated. An early audit
  command incorrectly counted 22 because its pattern excluded IDs whose prefix
  contains digits, specifically `I18N-01` and `I18N-02`. The corrected pattern
  accepts `[A-Z0-9]+`; no requirement was missing for that reason.
- No account-quota claim is inferred from Sol, Terra, or Luna names. Runtime
  routing decisions require measured end-to-end evidence and account-observed
  usage when available.
- Stable sharing now explicitly means survival across a process restart for a
  documented retention window, not merely a deterministic URL during one
  process lifetime.

## Scope kept out

The audit does not authorize BYOK, arbitrary public model identifiers, a full
declarative-v2 runtime, multi-agent expansion, a history rewrite, or reuse of a
later implementation. These do not block the post-G7 corrections.
