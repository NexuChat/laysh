# G7 continuation build notebook

## Identity

- Root Session ID:
- Parent Session ID, if forked:
- Active model and effort:
- Start time UTC:
- Baseline commit:
- Working branch:

## Baseline verification

| Check | Command | Result | Evidence path |
|---|---|---|---|
| HEAD and history | | | |
| Working tree | | | |
| Unit/integration | | | |
| Browser/a11y | | | |
| Lint | | | |
| Non-browser coverage | | | |

Expected starting observation: full Pytest 193 passed and 1 documented live
skip; Ruff passed; browser marker 6 passed and 1 documented live skip;
non-browser coverage 187 passed, 7 deselected, 90.01% total. Record and explain
any difference before implementation.

## Batch record

Repeat this section for every batch.

### Batch `<name>`

- Acceptance IDs:
- User-visible outcome:
- Failing tests added first:
- Failure observed:
- Implementation summary:
- Refactor summary:
- Commands and real results:
- Browser/manual evidence:
- Live model calls, if any:
- Model escalation and reason, if any:
- Commit:
- Remaining risks:

## Model-call ledger

| UTC | Acceptance ID | Stage | Model | Effort | Elapsed | Result | Heal count | Evidence |
|---|---|---|---|---:|---:|---|---:|---|

Do not record prompts containing learner data, secrets, tokens, auth paths, or
raw environment values.

## Runtime routing evaluation

- Evaluation set and hashes:
- Candidate route and existing route:
- Predeclared success/latency/usage tolerances:
- Maximum calls and abort conditions:
- Success rate by complexity tier:
- Total calls and heals by route:
- Elapsed time by route:
- Account-observed usage evidence:
- Routing decision and reason:

## Final release record

- Acceptance rows total:
- Passing:
- Failing:
- Not started:
- Blocked:
- Unit/integration result:
- Browser result:
- Accessibility result:
- Lint/type/build result:
- Six-golden result:
- Public-path smoke result:
- Final commit:
- Owner-only actions remaining:
- Coverage and skip deviations:
- Per-stage model receipt evidence:
