# Clean-checkout verification

These are the judge-facing commands for a new source checkout. They do not need
an OpenAI account and do not spend model quota.

```bash
git clone https://<FINAL-REPOSITORY-URL>/laysh.git
cd laysh
git checkout v1.0.0
uv sync --frozen --extra dev
npm install
pytest -q
ruff check .
pytest -q -m browser
npm run test:a11y
LAYSH_CODEX_BACKEND=mock .venv/bin/uvicorn server.app:create_app --factory --port 8765
```

In a second terminal:

```bash
curl --fail http://127.0.0.1:8765/healthz
curl --fail 'http://127.0.0.1:8765/api/gallery?locale=ar'
```

The G6 builder pass also creates a temporary detached worktree at the release
commit, attaches the already locked dependency environment without modifying
tracked source, and reruns the offline suite. Its command, commit, elapsed time,
and outcome are stored in `out/evidence/g6-clean-checkout.json`. This separates
clean-source reproducibility from a redundant network dependency download.

