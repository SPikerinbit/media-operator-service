# Environment Reference

The local env file is:

```text
scripts\media.local.env.ps1
```

It is intentionally ignored by Git. Start from:

```text
scripts\media.local.env.ps1.example
```

## Required

- `DIFY_APP_ID`: Dify workflow app id used to fetch token and workflow id.
- `TRANSLATE_API_KEY`: DeepSeek API key.

## Dify

- `DIFY_API_BASE`: default `http://localhost`.
- `DIFY_WORKFLOW_API_KEY`: fetched automatically by the startup script.
- `DIFY_WORKFLOW_ID`: fetched automatically by the startup script.
- `OPERATOR_BASE_URL`: URL written into Dify workflow HTTP nodes.
- `PUBLIC_BASE_URL`: public URL used by Operator file links.

## Whisper

Stable defaults:

```powershell
$env:WHISPER_BACKEND = "faster-whisper"
$env:WHISPER_MODEL = "large-v3"
$env:WHISPER_DEVICE = "cuda"
$env:WHISPER_COMPUTE_TYPE = "int8_float16"
$env:WHISPER_INFERENCE_MODE = "standard"
$env:WHISPER_VAD_ENABLED = "false"
$env:WHISPER_BATCHED_INFERENCE = "false"
```

`standard` is slower than batched inference but avoids the periodic missing
subtitle issue seen with batched/VAD combinations.

## Translation

Stable defaults:

```powershell
$env:TRANSLATE_PROVIDER = "deepseek"
$env:TRANSLATE_API_BASE = "https://api.deepseek.com"
$env:TRANSLATE_MODEL = "deepseek-chat"
$env:TRANSLATE_PROMPT_CONCURRENCY = "8"
```

The translation stage uses JSON output with validation and fallback behavior.

## Burn

```powershell
$env:FFMPEG_BURN_ENCODER = "auto"
```

`auto` chooses `h264_nvenc` when available and falls back to CPU encoding.

## Batch

```powershell
$env:WORKER_CONCURRENCY = "2"
$env:BATCH_WORKER_CONCURRENCY = "2"
$env:BATCH_WORKER_MAX_CONCURRENCY = "5"
```

On an 8GB RTX 4060 Laptop GPU, batch concurrency `2` is the stable default for
`large-v3`.

## Bilibili

Required for upload:

```powershell
$env:BILI_SESSDATA = "YOUR_BILI_SESSDATA"
$env:BILI_JCT = "YOUR_BILI_JCT"
$env:BILI_BUVID3 = "YOUR_BILI_BUVID3"
```

Recommended:

```powershell
$env:BILI_DEDEUSERID = "YOUR_DEDEUSERID"
$env:BILI_AC_TIME_VALUE = "YOUR_AC_TIME_VALUE"
$env:BILI_UPLOAD_CONCURRENCY = "1"
$env:BILI_UPLOAD_LINE = "QN"
$env:BILI_UPLOAD_FALLBACK_LINES = "QN,BDA2,WS,auto"
$env:BILI_PROXY = ""
```

Bilibili upload should normally not use the YouTube proxy.

## Proxy

For slow YouTube downloads:

```powershell
$env:http_proxy = "http://127.0.0.1:7899"
$env:https_proxy = "http://127.0.0.1:7899"
$env:HTTP_PROXY = "http://127.0.0.1:7899"
$env:HTTPS_PROXY = "http://127.0.0.1:7899"
$env:YT_DLP_PROXY = "http://127.0.0.1:7899"
```

Leave these commented out on machines without that proxy.

