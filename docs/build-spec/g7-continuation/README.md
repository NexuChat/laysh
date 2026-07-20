# Laysh G7 continuation pack

**Status:** audited and build-authorized  
**Prepared:** 2026-07-20  
**Target repository:** `/home/dev/laysh`  
**Clean baseline:** `828fe4d99dfd516c3fea7a028fc6e4b306199702`  
**Root Codex session:** `019f7998-9378-72b2-b590-ee10e632ce81`

This package defines the work that follows the accepted G7 close-out. It is an
incremental continuation package, not a replacement product specification and
not a source-code patch. The implementation session must derive its code from
these requirements and tests, not from any later repository history.

This is an owner-authorized external requirements package prepared outside the
target Git history. It records required outcomes and baseline observations; it
does not import a later implementation.

## Document order

1. [`PROVENANCE.md`](PROVENANCE.md) — trusted baseline and evidence boundary.
2. [`CONTINUATION-BRIEF.md`](CONTINUATION-BRIEF.md) — required behavior and scope.
3. [`MODEL-ROUTING.md`](MODEL-ROUTING.md) — evidence-based GPT-5.6 routing policy.
4. [`ACCEPTANCE-MATRIX.md`](ACCEPTANCE-MATRIX.md) — objective completion gates.
5. [`BUILD-NOTEBOOK-TEMPLATE.md`](BUILD-NOTEBOOK-TEMPLATE.md) — execution ledger.
6. [`REQUIREMENTS-AUDIT.md`](REQUIREMENTS-AUDIT.md) — baseline gaps and audit decisions.
7. [`CAPABILITY-STAGES.md`](CAPABILITY-STAGES.md) — build, release, and submission tool boundaries.
8. [`ROOT-RESUME-PROMPT.md`](ROOT-RESUME-PROMPT.md) — exact prompt for the root session.

If these documents conflict, the order above wins. The official competition
rules and the security, privacy, and honesty contracts already committed at the
clean G7 baseline remain binding.

## Use

Start the resumed root Codex session through
`/home/dev/laysh-briefs/run-laysh-codex.sh`; its Laysh profile limits the
available skill, plugin, agent, and MCP surface. The resumed session copies this package into
`docs/build-spec/g7-continuation/` before implementation. It then executes the
acceptance rows test-first, in dependency order, and records only real evidence.

Do not copy historical session ledgers, archived implementation code, later
commits, or generated patches into the target repository.
