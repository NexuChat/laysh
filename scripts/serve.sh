#!/usr/bin/env bash
set -euo pipefail

LAYSH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAYSH_HOST="${LAYSH_HOST:-127.0.0.1}"
LAYSH_PORT="${LAYSH_PORT:-8765}"

cd "$LAYSH_ROOT"
exec "$LAYSH_ROOT/.venv/bin/uvicorn" server.app:create_app \
  --factory \
  --host "$LAYSH_HOST" \
  --port "$LAYSH_PORT" \
  --proxy-headers \
  --forwarded-allow-ips="127.0.0.1"
