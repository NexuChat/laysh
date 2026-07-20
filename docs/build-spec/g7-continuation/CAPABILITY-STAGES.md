# Capability stages

Capabilities are retained on the machine but exposed only in the phase that
needs them. This prevents a build session from accidentally pushing, deploying,
submitting, or choosing an unrelated implementation stack.

## Stage 1 — build and verification

Launcher: `/home/dev/laysh-briefs/run-laysh-codex.sh`

Effective-surface verifier: `/home/dev/laysh-briefs/verify-laysh-profile.py`.
Use it instead of bare `codex mcp list` or `codex plugin list`, which report the
global installation rather than launcher overrides.

- Model: Terra/high by default, with the escalation policy in
  `MODEL-ROUTING.md`.
- MCP: OpenAI Developer Docs, Playwright, and AccessLint only.
- Visual skills: the committed `sim-quality` contract, frontend design,
  motion-performance review, browser QA, responsive/accessibility review, and
  the normal test-first/security/API skills.
- GitHub, Cloudflare account actions, Devpost, media-generation plugins, Chief,
  and subagents remain unavailable.

This stage ends only when all 30 acceptance rows pass. It may produce commits
and local evidence, but it must not push or mutate an external service.

## Stage 2 — owner-authorized release

Launcher: `/home/dev/laysh-briefs/run-laysh-release-codex.sh`

This stage adds the already configured GitHub MCP. Before any remote write it
must verify:

1. all acceptance rows pass at the intended release commit;
2. the owner has approved the repository name and public visibility;
3. `git remote -v` resolves to that exact repository;
4. no secret, raw learner question, runtime credential, or private evidence is
   tracked; and
5. the push command and target branch are recorded in the release notebook.

Current machine evidence: `gh` is authenticated, but the clean Laysh repository
has no remote. Therefore GitHub is useful later and intentionally disabled in
Stage 1; installing a second GitHub plugin now would duplicate the existing MCP.

The installed `cloudflared` CLI matches the repository's systemd plus tunnel
deployment plan. A generic Cloudflare Workers/Pages plugin is not installed
because it targets a different architecture. Named-tunnel creation, DNS, and
public-host changes remain owner-authorized external actions.

## Stage 3 — submission and media

The local Codex CLI marketplace snapshot does not currently expose a Devpost
plugin, even if another ChatGPT surface shows “Devpost Hackathons — Installed.”
Recheck the surface where that badge appears at submission time; do not claim a
CLI integration that is not locally visible.

Remotion, Hyperframes, and Canva remain installed globally but disabled during
build. Enable a media tool only after the release commit is fixed and only for a
specific deliverable such as the existing 2:55 demo outline. Uploading a public
video, completing Devpost fields, selecting a track, and pressing Submit remain
owner-only actions with a final reopen-and-verify pass.

## Promotion rule

Do not solve a later-stage need by broadening the current stage. Promote the
session only when its entry conditions are met, then enable the smallest
additional capability required for the named external action.
