# Local service and owner-run tunnel

The committed units run Laysh on `127.0.0.1:8765`, keep learner jobs ephemeral,
and use GPT-5.6 only. No credential or tunnel token belongs in this repository.

Install the user units. The five-minute monitor restarts Laysh only after three
consecutive failed health checks:

```bash
mkdir -p ~/.config/systemd/user ~/.config/laysh
install -m 0644 deploy/laysh.service ~/.config/systemd/user/
install -m 0644 deploy/laysh-healthcheck.service ~/.config/systemd/user/
install -m 0644 deploy/laysh-healthcheck.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now laysh.service laysh-healthcheck.timer
curl --fail http://127.0.0.1:8765/healthz
```

Non-secret overrides and the required live-cache HMAC secret go in
`~/.config/laysh/service.env`. Generate the secret directly into that owner-only file, keep
the same value across restarts and deploys, and never commit or print it later:

```bash
umask 077
python -c 'import secrets; print("LAYSH_CACHE_KEY_SECRET=" + secrets.token_hex(32))' >> ~/.config/laysh/service.env
```

Verified live lessons persist under `%h/laysh/out/cache/live` by default. A deployment that
replaces the checkout should set `LAYSH_LIVE_CACHE_ROOT` to a persistent writable volume and
add that path to the unit's `ReadWritePaths`. `LAYSH_MAX_LIVE_LESSONS` defaults to 100; the
least recently accessed live lesson is evicted first, while the six reviewed goldens are
never evicted and remain available when Codex is unavailable.

For a temporary owner-run Cloudflare quick tunnel:

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

Copy the generated HTTPS URL into the `FINAL-DEMO-URL` placeholders only after
testing it in a fresh browser. Quick-tunnel URLs are temporary. For a stable
hostname, copy `cloudflared.example.yml` outside the repository, replace every
angle-bracket placeholder, create the named tunnel using the owner's Cloudflare
account, and install a separate user service for that tunnel. Those external
account actions are intentionally not performed by this build session.

Useful operations:

```bash
systemctl --user restart laysh.service
systemctl --user status laysh.service laysh-healthcheck.timer
journalctl --user -u laysh.service --since today
```
