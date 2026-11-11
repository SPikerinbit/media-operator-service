#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_OUT="${MEDIA_LOG_OUT:-/tmp/media-operator.out.log}"
LOG_ERR="${MEDIA_LOG_ERR:-/tmp/media-operator.err.log}"
BIND_HOST="${MEDIA_BIND_HOST:-0.0.0.0}"
BIND_PORT="${MEDIA_PORT:-8090}"
PYTHON_BIN="${MEDIA_PYTHON:-$ROOT_DIR/.venv-wsl/bin/python}"

cd "$ROOT_DIR"
pkill -f "uvicorn app.main:app" || true

: "${TRANSLATE_API_KEY:?TRANSLATE_API_KEY is required}"

env \
  ALLOW_PLACEHOLDER_ARTIFACTS=false \
  WHISPER_BACKEND=auto \
  WHISPER_DEVICE="${WHISPER_DEVICE:-cuda}" \
  WHISPER_COMPUTE_TYPE="${WHISPER_COMPUTE_TYPE:-float16}" \
  WHISPER_MODEL="${WHISPER_MODEL:-small}" \
  TRANSLATE_PROVIDER=deepseek \
  TRANSLATE_API_BASE="${TRANSLATE_API_BASE:-https://api.deepseek.com}" \
  TRANSLATE_MODEL="${TRANSLATE_MODEL:-deepseek-chat}" \
  TRANSLATE_API_KEY="$TRANSLATE_API_KEY" \
  nohup "$PYTHON_BIN" -m uvicorn app.main:app --host "$BIND_HOST" --port "$BIND_PORT" >"$LOG_OUT" 2>"$LOG_ERR" &

sleep 2
ps -ef | grep "uvicorn app.main:app" | grep -v grep
