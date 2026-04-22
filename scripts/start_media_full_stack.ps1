Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonExe = Join-Path $projectRoot ".venv-win\Scripts\python.exe"
$logOut = Join-Path $projectRoot "server.out.log"
$logErr = Join-Path $projectRoot "server.err.log"

if (-not (Test-Path $pythonExe)) {
  throw "Python not found: $pythonExe"
}

$customEnvScript = Join-Path $projectRoot "scripts\media.local.env.ps1"
if (Test-Path $customEnvScript) {
  . $customEnvScript
}

Write-Host "[1/5] Starting Dify containers in WSL..."
$difyContainers = @(
  "docker-nginx-1",
  "docker-api-1",
  "docker-worker-1",
  "docker-worker_beat-1",
  "docker-plugin_daemon-1",
  "docker-db_postgres-1",
  "docker-redis-1",
  "docker-web-1",
  "docker-sandbox-1",
  "docker-ssrf_proxy-1",
  "docker-weaviate-1"
)
$startArgs = @("-d", "Ubuntu-22.04-E", "--", "docker", "start") + $difyContainers
& wsl @startArgs | Out-Null

# Keep this WSL distro alive after the launcher exits. Otherwise the Dify
# containers can receive SIGTERM shortly after startup, leaving localhost:80
# behind nginx with dead upstreams.
$keepAlive = Get-CimInstance Win32_Process -Filter "Name = 'wsl.exe'" |
  Where-Object { $_.CommandLine -like "*Ubuntu-22.04-E*sleep*99999999*" } |
  Select-Object -First 1
if (-not $keepAlive) {
  Start-Process -FilePath "wsl.exe" `
    -ArgumentList @("-d", "Ubuntu-22.04-E", "--", "sleep", "99999999") `
    -WindowStyle Hidden | Out-Null
  Start-Sleep -Seconds 1
}

Write-Host "[2/5] Fetching Dify API token..."
$difyAppId = if ($env:DIFY_APP_ID) { $env:DIFY_APP_ID.Trim() } else { "a6b0d8d0-4a48-4f74-a938-88f4f18f9a03" }
if ([string]::IsNullOrWhiteSpace($difyAppId) -or $difyAppId -eq "YOUR_DIFY_APP_ID") {
  throw "Set DIFY_APP_ID in scripts\media.local.env.ps1 to the Dify app id for the media workflow."
}
$tokenSql = "select token from api_tokens where app_id='$difyAppId' limit 1;"
$tokenResult = & wsl -d Ubuntu-22.04-E -- docker exec docker-db_postgres-1 psql -U postgres -d dify -Atc $tokenSql
$difyToken = ""
if ($tokenResult) {
  $difyToken = ($tokenResult | Select-Object -First 1).Trim()
}
if ([string]::IsNullOrWhiteSpace($difyToken)) {
  throw "Cannot fetch Dify token for app_id $difyAppId"
}

$workflowSql = "select workflow_id from apps where id='$difyAppId' limit 1;"
$workflowResult = & wsl -d Ubuntu-22.04-E -- docker exec docker-db_postgres-1 psql -U postgres -d dify -Atc $workflowSql
$difyWorkflowId = ""
if ($workflowResult) {
  $difyWorkflowId = ($workflowResult | Select-Object -First 1).Trim()
}
if ([string]::IsNullOrWhiteSpace($difyWorkflowId)) {
  throw "Cannot fetch published Dify workflow_id for app_id $difyAppId"
}

Write-Host "[3/5] Setting runtime environment..."
if (-not $env:DIFY_API_BASE) { $env:DIFY_API_BASE = "http://localhost" }
$env:DIFY_WORKFLOW_API_KEY = $difyToken
$env:DIFY_WORKFLOW_ID = $difyWorkflowId
$env:WHISPER_BACKEND = "faster-whisper"
$env:WHISPER_MODEL = "large-v3"
$env:WHISPER_DEVICE = "cuda"
$env:WHISPER_COMPUTE_TYPE = "int8_float16"
$env:WHISPER_WORKER_PYTHON = $pythonExe
$env:WHISPER_WORD_TIMESTAMPS = "true"
$env:WHISPER_INFERENCE_MODE = "standard"
$env:WHISPER_VAD_ENABLED = "false"
$env:WHISPER_VAD_PADDING_MS = "800"
$env:WHISPER_BATCHED_INFERENCE = "false"
$env:WHISPER_BATCH_SIZE = "4"
$env:WHISPER_BEAM_SIZE = "5"
$env:WHISPER_BEST_OF = "5"
$env:WHISPER_CONDITION_ON_PREVIOUS_TEXT = "false"
$env:FFMPEG_BURN_ENCODER = "auto"
$env:SUBTITLE_REPEAT_HANDLING = "compress"
$env:SUBTITLE_REPEAT_COMPRESS_TEXT = "ha ha ha"
$env:SUBTITLE_REPEAT_MIN_SPAN_MS = "2500"
$env:SUBTITLE_REPEAT_MIN_BLOCKS = "4"
$env:SUBTITLE_COHERENCE_MERGE = "true"
$env:SUBTITLE_COHERENCE_MAX_CHARS = "76"
$env:SUBTITLE_COHERENCE_MAX_DURATION_MS = "7200"
$env:SUBTITLE_COHERENCE_MAX_GAP_MS = "650"
$env:SUBTITLE_ORPHAN_MAX_CHARS = "18"
if (-not $env:WORKER_CONCURRENCY) { $env:WORKER_CONCURRENCY = "2" }
if (-not $env:BATCH_WORKER_CONCURRENCY) { $env:BATCH_WORKER_CONCURRENCY = "2" }
if (-not $env:BATCH_WORKER_MAX_CONCURRENCY) { $env:BATCH_WORKER_MAX_CONCURRENCY = "5" }
if (-not $env:ALLOW_PLACEHOLDER_ARTIFACTS) { $env:ALLOW_PLACEHOLDER_ARTIFACTS = "false" }

$ffmpegExe = Join-Path $projectRoot "data\tools\ffmpeg\ffmpeg-8.1-essentials_build\bin\ffmpeg.exe"
$ffprobeExe = Join-Path $projectRoot "data\tools\ffmpeg\ffmpeg-8.1-essentials_build\bin\ffprobe.exe"
if (Test-Path $ffmpegExe) { $env:FFMPEG_BIN = $ffmpegExe }
if (Test-Path $ffprobeExe) { $env:FFPROBE_BIN = $ffprobeExe }

if (-not $env:TRANSLATE_PROVIDER) { $env:TRANSLATE_PROVIDER = "deepseek" }
if (-not $env:TRANSLATE_API_BASE) { $env:TRANSLATE_API_BASE = "https://api.deepseek.com" }
if (-not $env:TRANSLATE_MODEL) { $env:TRANSLATE_MODEL = "deepseek-chat" }
if (-not $env:TRANSLATE_PROMPT_CONCURRENCY) { $env:TRANSLATE_PROMPT_CONCURRENCY = "8" }
if (-not $env:TRANSLATE_API_KEY) {
  Write-Warning "TRANSLATE_API_KEY is empty. en_only can still run, bilingual/zh_only translation will fail."
}
if (-not $env:BILI_UPLOAD_CONCURRENCY) { $env:BILI_UPLOAD_CONCURRENCY = "1" }
if (-not $env:BILI_UPLOAD_LINE) { $env:BILI_UPLOAD_LINE = "QN" }
if (-not $env:BILI_UPLOAD_FALLBACK_LINES) { $env:BILI_UPLOAD_FALLBACK_LINES = "QN,BDA2,WS,auto" }
if (-not (Test-Path Env:BILI_PROXY)) { $env:BILI_PROXY = "" }

Write-Host "[4/5] Restarting operator frontend service..."
$staleProcesses = New-Object System.Collections.Generic.HashSet[int]

try {
  Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { [void]$staleProcesses.Add([int]$_.OwningProcess) }
} catch {
  netstat -ano |
    Select-String ":8090" |
    ForEach-Object { ($_ -split "\s+")[-1] } |
    Where-Object { $_ -match "^\d+$" -and $_ -ne "0" } |
    ForEach-Object { [void]$staleProcesses.Add([int]$_) }
}

Get-CimInstance Win32_Process |
  Where-Object {
    ($_.CommandLine -like "*uvicorn*app.main:app*" -and $_.CommandLine -like "*--port*8090*") -or
    ($_.CommandLine -like "*yt-dlp*" -and $_.CommandLine -like "*$projectRoot*")
  } |
  ForEach-Object { [void]$staleProcesses.Add([int]$_.ProcessId) }

foreach ($pidNum in $staleProcesses) {
  if ($pidNum -ne $PID) {
    Stop-Process -Id $pidNum -Force -ErrorAction SilentlyContinue
  }
}
Start-Sleep -Seconds 1

Start-Process -FilePath $pythonExe `
  -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090") `
  -WorkingDirectory $projectRoot `
  -RedirectStandardOutput $logOut `
  -RedirectStandardError $logErr | Out-Null

Start-Sleep -Seconds 3
$health = Invoke-RestMethod "http://localhost:8090/health"

Write-Host "[5/5] Ready."
Write-Host ("Dify configured: " + $health.dify.configured)
Write-Host ("Whisper: " + $health.whisper.model + " / " + $health.whisper.device)
Write-Host ("Batch concurrency default/max: " + $health.dify.batch_worker_concurrency + "/" + $health.dify.batch_worker_max_concurrency)
Write-Host "Opening media-ui..."
Start-Process "http://localhost:8090/media-ui" | Out-Null
