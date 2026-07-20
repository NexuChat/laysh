# Two-tier simulation retention

## Decision

Laysh classifies verification failures with one fail-closed policy shared by the
pipeline, cache receipt, measurement report, and UI. A candidate is Tier A when
every applicable gate passes. It is Tier B only when every failure is an
explicitly allowlisted polish failure and all correctness-critical gates have
run and passed. Any unknown failure is correctness-critical by default.

The polish allowlist is deliberately narrow:

- mobile overlay safe-band failures;
- subject idle motion below the strict visual bound only while remaining above
  the total-freeze tripwire;
- the existing suspect relation-fixture diagnostic when independent numeric
  fixtures for the same output passed;
- semantic-vision label obstruction, which does not dispute actor visibility,
  actor action, or physical consistency.

Security, source and shell integrity, runtime, numerical fixtures, render/output
consistency, actor trajectory, total freeze, corrective misconception, and any
unknown gate remain correctness-critical.

## Pipeline and persistence

Each candidate restarts verification at deterministic gate one. A polish-only
deterministic candidate is still assembled, then receives browser and semantic
vision checks so Tier B never bypasses a correctness gate. The pipeline keeps
the newest correctness-passing candidate as the best Tier B candidate and still
spends the allowed heal attempt trying to reach Tier A. If the heal budget is
exhausted, too small, or the heal call fails, the saved Tier B candidate is
released instead of discarded. A later correctness failure cannot overwrite it.

Receipts record `correctness_passed` and the exact missed polish check codes.
Tier A receipts require zero failures. Tier B receipts require at least one
recorded polish miss and correctness success. Existing pre-policy live Tier B
entries with zero failed gates are interpreted as Tier A so they are not
mislabelled experimental after deployment. Both tiers remain durable,
shareable, and gallery-visible.

## Honest presentation and tests

Tier A retains the instant/verified treatment. Tier B uses a visually distinct
amber “تجريبية / Experimental” badge, an always-visible statement that it is
scientifically correct but missed polish checks, and a receipt list naming those
checks. The same metadata is returned by job, share, and gallery-detail APIs.

Tests cover the fail-closed taxonomy, strictness-only retention after heal
exhaustion, correctness failure fallback, cache invariants, restart/share/gallery
round trips, and visible bilingual badge copy. The full offline suite, coverage,
and Ruff run before commit; the five public benchmark questions run twice after
the implementation.
