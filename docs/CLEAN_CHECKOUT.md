# Clean-checkout verification for the v1.1 release candidate

These judge-facing commands verify one exact, owner-approved v1.1 release
candidate commit from a new source checkout. They do not need an OpenAI account
and do not spend model quota. Replace both placeholders before running them.

```bash
git clone https://github.com/NexuChat/laysh.git
cd laysh
git checkout --detach <FINAL-RELEASE-COMMIT>
uv sync --frozen --extra dev
uv run pytest -q
uv run ruff check .
uv run pytest -q -m browser
uv run pytest -q -m browser tests/test_m4_browser.py
LAYSH_CODEX_BACKEND=mock uv run uvicorn server.app:create_app --factory --port 8765
```

`package.json` contains command aliases and zero JavaScript dependencies, so
this verification has no JavaScript package-install step.

In a second terminal:

```bash
curl --fail http://127.0.0.1:8765/healthz
curl --fail 'http://127.0.0.1:8765/api/gallery?locale=ar'
```

The v1.1 release pass must also create a temporary clean archive or detached
worktree at `<FINAL-RELEASE-COMMIT>` and rerun these gates. The final RELEASE-01
evidence must record that exact commit, commands, timings, and outcomes; an
untested tag or working tree is not equivalent evidence.

## Share-link retention

Verified share links use a 30-day default retention window and expose their
expiry in the public metadata. After expiry, playback and download are no
longer available. Release operators must describe these links as temporary,
not permanent hosting.
