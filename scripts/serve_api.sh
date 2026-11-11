#!/usr/bin/env bash
# Headless API entry point. Defaults to loopback. Binding any other host
# requires MEDIA_API_TOKEN. The desktop app does not use this script.
set -euo pipefail

HOST="${MEDIA_BIND_HOST:-127.0.0.1}"
PORT="${MEDIA_PORT:-8090}"

case "$HOST" in
  127.0.0.1|localhost|::1) ;;
  *)
    if [[ -z "${MEDIA_API_TOKEN:-}" ]]; then
      echo "Refusing to bind ${HOST} without MEDIA_API_TOKEN. Set the token, or bind 127.0.0.1." >&2
      exit 1
    fi
    ;;
esac

exec uvicorn app.main:app --host "$HOST" --port "$PORT"
