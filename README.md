# Media Operator Service

Media Operator Service is a local Windows-first media workflow frontend and
operator backend. It provides a batch UI for YouTube or local video input,
calls a Dify workflow for orchestration, and performs the heavy stages locally:
download/import, Whisper transcription, DeepSeek subtitle translation, ffmpeg
subtitle burn, and optional Bilibili upload.

The stable production entrypoint is:

```powershell
scripts\start_media_full_stack.bat
```

After startup, open:

```text
http://localhost:8090/media-ui
```

## Quick Setup

For a new Windows machine, follow the full guide:

- [Windows setup](docs/SETUP_WINDOWS.md)
- [Dify setup](docs/DIFY_SETUP.md)
- [Environment reference](docs/ENV_REFERENCE.md)
- [Private GitHub publishing](docs/GITHUB_PRIVATE_PUBLISH.md)

Minimal local bootstrap:

```powershell
cd E:\projects\media-operator-service
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 -SkipHealthCheck
copy .\scripts\media.local.env.ps1.example .\scripts\media.local.env.ps1
notepad .\scripts\media.local.env.ps1
```

Fill the required values in `scripts\media.local.env.ps1`, then run:

```powershell
.\scripts\start_media_full_stack.bat
```

## What Is Tracked

The repository is designed to be safe for a private GitHub repo:

- Source: `app/`
- Workflow generator and startup scripts: `scripts/`
- Dify workflow exports: `dify_workflows/`
- Runtime docs: `docs/`
- Packaging files: `Dockerfile`, `docker-compose.yml`, `requirements.txt`

The following are intentionally not tracked:

- `scripts/media.local.env.ps1`
- `.venv*`
- `data/jobs`, `data/batches`, `data/models`, `data/tools`, `data/tmp`
- logs and generated media artifacts
- API keys, Bilibili cookies, Dify workflow tokens

## Default Production Settings

The example env mirrors the current stable local setup without secrets:

- Whisper: `large-v3`, CUDA, `int8_float16`, standard inference
- VAD: disabled by default to avoid subtitle gaps
- Translation: DeepSeek JSON output, prompt concurrency `8`
- Batch concurrency: default `2`, max `5`
- Burn encoder: ffmpeg auto, usually `h264_nvenc` when available
- Bilibili upload: concurrency `1`, line `QN`, fallback lines enabled

## Main Endpoints

- `GET /health`
- `GET /media-ui`
- `POST /ui/batches`
- `GET /ui/batches/{batch_id}`
- `GET /ui/batches/{batch_id}/events`
- `POST /stage-jobs/download`
- `POST /stage-jobs/transcribe`
- `POST /stage-jobs/translate`
- `POST /stage-jobs/burn`
- `POST /stage-jobs/bilibili-upload`

## Notes

Dify orchestrates the visible workflow. Operator owns all long-running local
file work. The browser never receives the Dify token, DeepSeek API key, or
Bilibili cookies.

