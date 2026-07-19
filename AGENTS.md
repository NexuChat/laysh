# Laysh build rules

`/home/dev/laysh-briefs/SPEC-V3.md` is the sole product authority. Historical v2 and
addendum documents must not drive implementation.

## Quality bar

- Preserve the answer-first path even when generation fails.
- Never label an artifact verified until every applicable deterministic gate passes.
- Keep public contracts closed, versioned, and backward-compatible within a contract version.
- Use test-first changes for contracts, safety, artifact security, job lifecycle, and prompts.
- Keep unit and integration coverage at or above 80 percent.
- Run `pytest -q` and `ruff check .` before every coherent commit.

## Security and privacy

- Never commit secrets, auth files, raw learner questions, tokens, or arbitrary model output.
- Public model calls are ephemeral and pass prompts on stdin with `shell=False`.
- SSE exposes only sanitized contract fields; never reasoning, paths, environment values, or traces.
- Portable artifacts use the SPEC-V3 CSP and contain no network-capable code.
- Generated modules may implement only the declared `window.LayshSimulation` interface.

## Prompt and contract changes

- A prompt change needs a failing fixture that demonstrates the need.
- A contract change updates schema, tests, prompts, and acceptance mapping together.
- Live tests are marked `live`, opt-in, and must never run in the offline suite.

## Commits

Use imperative conventional commit messages. Commit only coherent changes with green offline tests.

