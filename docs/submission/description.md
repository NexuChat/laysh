# Laysh (ليش): Ask why. Play the answer.

## Inspiration

Arabic-speaking learners can often find a definition but still struggle to see
the causal relationship behind it. Laysh starts with the question children keep
asking—“ليش؟ / why?”—and turns an explanation into something they can predict,
change, observe, and explain.

## What it does

Laysh is an Arabic-first learning experience for secondary-school learners aged
13+ and teachers. It answers a safe question first, then builds a focused
interactive simulation when the concept is meaningfully simulatable. Six
builder-reviewed lessons—Moon phases, buoyancy, pendulum period, a simple
circuit, sound pitch, and day/night—play instantly. Every lesson includes a
prediction prompt, an observable control, a causal text alternative, precise
assumptions and units, and an expandable verification receipt. The complete
lesson downloads as a self-contained, network-dead HTML file.

## How we built it

The builder authored the product, pedagogy, engineering, visual direction, and
acceptance briefs. In one primary Codex build thread, Codex accelerated their
implementation into a new FastAPI/vanilla-web repository with closed schemas,
replayable SSE jobs, an isolated subprocess adapter, a trusted bilingual lesson
shell, deterministic verification, bounded healing, browser automation, and
granular evidence.

The public runtime is GPT-5.6-only. gpt-5.6-luna returns the normalized intent,
answer, fixed module specification, and independent fixtures in one structured
call. gpt-5.6-sol generates only the restricted simulation module. If a gate
fails, Sol receives the exact structured diagnostics and may heal the module at
most twice; Sol also performs bounded terse QA when required. A changed module
restarts schema, assembly, security, VM, interface, scientific fixture, and real
browser checks from the beginning. Only a fully passing artifact is cached or
marked verified.

## Challenges and lessons

The hardest part was making “tested and repaired” true rather than decorative.
Real live failures exposed output-schema restrictions, a case-insensitive
security false positive, contradictory generated fixtures, blind heal reports,
and an overlong QA input. Each failure became a focused regression test and a
more precise contract. A live run then demonstrated generate → verify failure →
heal with exact diagnostics → reverify pass.

We also learned that quality and latency pull in opposite directions. The two
unseen public smokes completed and stayed inside the 180-second public ceiling,
but first-answer p95 was 25.3 seconds against a 12-second objective and new-module
p95 was 178.3 seconds against 90 seconds. Laysh reports that honestly, never says
every simulation is instant, and makes reviewed goldens and verified cache hits
the dependable fast path.

## Impact and what's next

Laysh gives a learner value even when generation fails: the answer stays pinned
and the product offers an instant lesson or retry. Teachers get a portable lesson
without accounts, analytics, or learner tracking. Next steps—after the P0 release,
not hidden inside it—include four more reviewed lessons, projector links, Arabic
voice input, a second static gallery origin, presenter queue controls, curated
domain adapters, and teacher-facing tools.

Primary Codex `/feedback` Session ID:
`019f7998-9378-72b2-b590-ee10e632ce81`

