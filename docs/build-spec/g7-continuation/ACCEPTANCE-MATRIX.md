# G7 continuation acceptance matrix

Status values: `not-started`, `failing`, `passing`, `blocked`. Every `passing`
row needs named automated evidence and, where specified, manual evidence.

| ID | Requirement | Required evidence |
|---|---|---|
| BASE-01 | Start exactly at clean G7 commit `828fe4d99dfd516c3fea7a028fc6e4b306199702`. | HEAD assertion, clean status, 74-commit count. |
| BASE-02 | Baseline suites pass before implementation. | Pytest, Ruff, browser/a11y baseline report. |
| TEST-01 | New work preserves test integrity. | No new unexplained skips; coverage at least 80%; explain any material drop from the 90.01% baseline. |
| EVID-01 | Work remains in the root Session ID. | Session ledger records the root ID, model changes, commits, and commands. |
| EVID-02 | Runtime receipts identify every executed model stage truthfully. | Understand/generate/heal/QA receipt tests; no last-stage-derived ambiguous model label. |
| CONTRACT-01 | Generated-source size has one authoritative 96 KiB UTF-8 byte limit. | Project skill, schema, prompt, and verifier do not conflict; ASCII and multibyte boundary tests cover limit minus/at/plus one byte. |
| TEACH-01 | Misconceptions are labeled and explicitly corrected in AR/EN. | Content validator, six-golden test, browser snapshots. |
| TEACH-02 | Prediction does not lock the primary control. | Unit/state test plus keyboard/mobile browser journey. |
| MOTION-01 | Actor/action fields are closed and required. | Schema failures for missing/unknown values. |
| MOTION-02 | Actor tracking rejects decorative-only motion. | Positive/negative deterministic fixtures and browser probe. |
| MOTION-03 | Oscillation/rotation/orbit/propagation/flow match the model. | Per-action physics fixtures with declared tolerances. |
| MOTION-04 | Rendering and `test(inputs)` use one pivotal state source. | Contract/static checks plus deliberately divergent fixture rejection. |
| VQA-01 | Curated visual QA uses a closed Terra verdict and cannot override failed gates. | Adapter/schema tests and failed-gate promotion test. |
| VISUAL-01 | The site and six simulations render crisp, intentional, physically legible motion without temporal or teardown defects. | DPR/resize tests, four-state temporal captures, frame-time and cleanup probe, AR/EN responsive review, and closed visual-QA verdicts. |
| SHARE-01 | Completed eligible artifacts have privacy-safe stable share URLs. | API tests, no-raw-question assertion, copy/recovery browser tests. |
| SHARE-02 | A share survives process restart for a documented retention window and fails closed on expiry/tampering. | Restart integration test, persistence/expiry tests, traversal and identifier-tampering negatives. |
| LIB-01 | Six pinned lessons self-play physical motion and yield to user control. | Six browser journeys, pause/resume/reset, reduced-motion evidence. |
| I18N-01 | All core and failure paths are bilingual and direction-correct. | Locale inventory, AR/EN snapshots, direction tests. |
| I18N-02 | Locale changes only from the locale control. | Event-scope regression test. |
| UI-01 | Mobile overlays preserve action visibility and focus. | 320px, 390×844, 200% zoom, keyboard tests. |
| UI-02 | Concept time and parameter-sweep time remain independent where required. | Fake-clock and pendulum/wave browser tests. |
| ASSET-01 | Static assets and golden manifests are version-compatible. | Versioned URL/manifest tests and clean-browser deploy smoke. |
| REL-01 | Downstream failures retain an already-emitted safe answer. | Failure matrix across generation, heal, QA, cache, assembly, and runtime. |
| REL-02 | Invalid simulation slices never receive a verified label. | Malformed/partial/contradictory fixtures and negative cache assertions. |
| GEN-01 | Prompt changes are driven by failing fixtures and do not duplicate shell work. | Red-before-green regression evidence and prompt snapshot review. |
| EXP-01 | Experimental artifacts cannot enter stable cache without all gates. | Promotion-policy and route-label tests. |
| GOLD-01 | Six goldens pass scientific, actor-motion, bilingual, browser, and a11y review. | Manifest, hashes, screenshots, and per-golden report. |
| ROUTE-01 | Runtime follows evidence-based GPT-5.6 routing. | Invocation tests for Luna/Terra/Sol tier and escalation conditions. |
| ROUTE-02 | Generation routing is adopted from measured end-to-end evidence and avoids known-failing Terra-to-Sol double spend. | Bounded evaluation report with success, total calls/heals, latency, account-observed usage, tier decision, call cap, and abort conditions. |
| RELEASE-01 | Full release gates pass with no hidden failures. | Final verification report with zero failing/not-started rows. |

## Release query

```text
rows total: 30
passing: 30
failing: 0
not-started: 0
blocked: 0
```
