param(
  [switch]$SkipHealthCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvPython = Join-Path $projectRoot ".venv-win\Scripts\python.exe"
$requirements = Join-Path $projectRoot "requirements.txt"
$envExample = Join-Path $projectRoot "scripts\media.local.env.ps1.example"
$envLocal = Join-Path $projectRoot "scripts\media.local.env.ps1"
$toolsDir = Join-Path $projectRoot "data\tools"

function Require-Command($Name, $InstallHint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "$Name was not found. $InstallHint"
  }
}

function Write-Step($Message) {
  Write-Host ""
  Write-Host "==> $Message"
}

Set-Location $projectRoot

Write-Step "Checking required host tools"
Require-Command "git" "Install Git for Windows: https://git-scm.com/download/win"
Require-Command "python" "Install Python 3.12 from https://www.python.org/downloads/windows/"
Require-Command "wsl" "Install WSL 2 and an Ubuntu distro, then install Docker for Dify."

$pythonVersion = (& python --version) -join " "
Write-Host "Python: $pythonVersion"
Write-Host "Git: $((& git --version) -join ' ')"

Write-Step "Creating Windows Python virtual environment"
if (-not (Test-Path $venvPython)) {
  python -m venv (Join-Path $projectRoot ".venv-win")
}
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r $requirements

Write-Step "Preparing local env file"
if (-not (Test-Path $envLocal)) {
  Copy-Item -LiteralPath $envExample -Destination $envLocal
  Write-Host "Created scripts\media.local.env.ps1 from the example template."
  Write-Host "Edit it and fill DIFY_APP_ID, TRANSLATE_API_KEY, and Bilibili cookies before a full run."
} else {
  Write-Host "scripts\media.local.env.ps1 already exists; leaving it unchanged."
}

Write-Step "Checking ffmpeg"
New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
$ffmpegExe = Join-Path $toolsDir "ffmpeg\ffmpeg-8.1-essentials_build\bin\ffmpeg.exe"
if (Test-Path $ffmpegExe) {
  Write-Host "Found bundled ffmpeg: $ffmpegExe"
} elseif (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
  Write-Host "Found ffmpeg on PATH."
} else {
  Write-Host "ffmpeg was not found."
  Write-Host "Install ffmpeg or place a Windows build at data\tools\ffmpeg\ffmpeg-8.1-essentials_build\bin\ffmpeg.exe."
}

Write-Step "Checking optional NVIDIA GPU"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
  & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
} else {
  Write-Host "nvidia-smi was not found. CPU mode can still work, but large-v3 will be slow."
}

Write-Step "Checking Dify/Docker access from WSL"
try {
  & wsl -- docker ps --format "{{.Names}}" | Select-Object -First 5
} catch {
  Write-Host "Could not query Docker from WSL. Install/start Docker Desktop and Dify before running the full stack."
}

if (-not $SkipHealthCheck) {
  Write-Step "Starting the media stack"
  & (Join-Path $projectRoot "scripts\start_media_full_stack.ps1")
} else {
  Write-Step "Skipped service health check"
  Write-Host "Run scripts\start_media_full_stack.bat after filling scripts\media.local.env.ps1."
}

Write-Host ""
Write-Host "Bootstrap complete."
