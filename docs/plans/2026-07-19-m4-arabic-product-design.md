# M4 Arabic-first product design

## Direction and alternatives

The selected direction is a warm science notebook: quiet paper surfaces, deep ink green,
solar amber, and sparse orbital linework. It gives Laysh a recognizable classroom identity
without competing with the simulation. A dark observatory theme was rejected because long
Arabic explanations and projection use need brighter, higher-legibility surfaces. A playful
toy interface was rejected because badges and reward-like decoration could overstate what the
machine checks establish.

The implementation stays dependency-free: semantic HTML, one stylesheet, one JavaScript state
controller, the existing FastAPI contracts, and a self-hosted GNU FreeSans Arabic/Latin WOFF2
subset. The six M5 lessons appear as disabled preview cards labeled `قريبًا بعد المراجعة`; none
claims to be instant until a pinned artifact exists.

## State and data flow

The document contains ask, build, result, and degraded-state regions. Submitting a safe question
pushes `#build`, posts the existing closed ask contract, and reads SSE through `fetch()` so manual
reconnects can send `Last-Event-ID`. The answer event pins the answer card. Stage, heartbeat, and
verification events update bounded Arabic summaries and elapsed time without percentages or raw
model text. A watchdog distinguishes reconnecting, still testing after 90 seconds, cancellation,
and terminal failure. Browser Back restores the previous visible region without cancelling a job.

On completion, the simulation becomes the largest surface, followed by an expandable machine
verification receipt and offline download. Answer-only, unsafe redirect, generation failure,
runtime failure, and backend outage share an accessible recovery component but have distinct
Arabic copy and actions. The opaque `allow-scripts` iframe remains the artifact boundary.

## Acceptance strategy

Unit tests first lock font licensing/routing, RTL and localization markers, truthful gallery
labels, reconnect/replay code, state copy, and sandbox/download security. A raw Chrome DevTools
browser harness then exercises success and every designed failure, keyboard order, focus,
320-pixel reflow, 200% zoom, reduced motion, accessibility-tree names, and offline artifact
loading. It captures accepted 390×844 and 1440×900 screenshots under `out/evidence/screens/`.
One final GPT-5.6-family job is permitted only after all mock journeys pass.
