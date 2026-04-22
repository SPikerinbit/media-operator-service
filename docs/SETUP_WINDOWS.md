# Windows Setup

This guide assumes a Windows machine with an NVIDIA GPU. CPU mode can work, but
`large-v3` transcription will be slow.

## 1. Install prerequisites

Install these first:

- Git for Windows: https://git-scm.com/download/win
- Python 3.12: https://www.python.org/downloads/windows/
- WSL 2 with Ubuntu
- Docker Desktop with WSL integration enabled
- NVIDIA driver with `nvidia-smi` available

Optional but useful:

- ripgrep (`rg`) for secret scanning and debugging
- ffmpeg on PATH, or a Windows ffmpeg build under `data\tools\ffmpeg`

## 2. Clone the private repository

```powershell
cd E:\projects
git clone https://github.com/YOUR_GITHUB_OWNER/media-operator-service.git
cd .\media-operator-service
```

## 3. Bootstrap Python and local files

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 -SkipHealthCheck
```

This creates `.venv-win`, installs Python dependencies, and creates
`scripts\media.local.env.ps1` if it does not already exist.

## 4. Fill local env

Open:

```powershell
notepad .\scripts\media.local.env.ps1
```

Set at least:

- `DIFY_APP_ID`
- `TRANSLATE_API_KEY`

For Bilibili upload, also set:

- `BILI_SESSDATA`
- `BILI_JCT`
- `BILI_BUVID3`
- `BILI_DEDEUSERID`
- `BILI_AC_TIME_VALUE`

Keep this file local. It is ignored by Git.

## 5. Configure Dify

Follow [Dify setup](DIFY_SETUP.md). The important result is that your media
workflow app id is copied into `DIFY_APP_ID`.

## 6. Start the full stack

```powershell
.\scripts\start_media_full_stack.bat
```

The script starts the configured Dify containers, fetches the app API token
from Dify PostgreSQL, starts Operator on port `8090`, and opens the UI.

Open manually if needed:

```text
http://localhost:8090/media-ui
```

## 7. Verify health

```powershell
Invoke-RestMethod http://localhost:8090/health | ConvertTo-Json -Depth 6
```

Expected:

- `dify.configured` is `true`
- `whisper.model` is `large-v3`
- `whisper.device` is `cuda` on GPU machines
- `translation.configured` is `true` after setting DeepSeek key
- `bilibili.configured` is `true` after setting Bilibili cookies

