#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/mnt/e/projects/media-operator-service"
LOG_OUT="/tmp/media-operator.out.log"
LOG_ERR="/tmp/media-operator.err.log"

cd "$ROOT_DIR"
pkill -f "uvicorn app.main:app" || true

: "${TRANSLATE_API_KEY:?TRANSLATE_API_KEY is required}"

env \
  ALLOW_PLACEHOLDER_ARTIFACTS=false \
  WHISPER_BACKEND=auto \
  WHISPER_DEVICE=cuda \
  WHISPER_COMPUTE_TYPE=float16 \
  WHISPER_MODEL=small \
  TRANSLATE_PROVIDER=deepseek \
  TRANSLATE_API_BASE=https://api.deepseek.com \
  TRANSLATE_MODEL=deepseek-chat \
  TRANSLATE_API_KEY="$TRANSLATE_API_KEY" \
  nohup .venv-wsl/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8090 >"$LOG_OUT" 2>"$LOG_ERR" &

sleep 2
ps -ef | grep "uvicorn app.main:app" | grep -v grep
