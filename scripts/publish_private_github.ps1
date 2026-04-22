param(
  [Parameter(Mandatory = $true)]
  [string]$Owner,

  [string]$Repo = "media-operator-service",
  [string]$Branch = "main",
  [string]$CommitMessage = "Prepare private reproducible media operator release"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$localEnv = Join-Path $projectRoot "scripts\media.local.env.ps1"
$backupDir = Join-Path $projectRoot "data\backups\env"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupEnv = Join-Path $backupDir "media.local.env.ps1.$timestamp.bak"
$token = $env:GITHUB_TOKEN

function Fail($Message) {
  throw $Message
}

function Invoke-GitHubApi($Method, $Uri, $Body = $null) {
  $headers = @{
    "Accept" = "application/vnd.github+json"
    "Authorization" = "Bearer $token"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent" = "media-operator-publisher"
  }
  $args = @{
    Method = $Method
    Uri = $Uri
    Headers = $headers
  }
  if ($null -ne $Body) {
    $args["ContentType"] = "application/json"
    $args["Body"] = ($Body | ConvertTo-Json -Depth 8)
  }
  Invoke-RestMethod @args
}

function Assert-CleanSecrets {
  $trackedFiles = git ls-files

  if ($trackedFiles | Where-Object { $_ -match '(^|/)scripts/media\.local\.env\.ps1$' }) {
    Fail "Refusing to publish tracked local secret file: scripts/media.local.env.ps1"
  }

  $secretMatchers = @(
    @{ Name = "GitHub PAT"; Pattern = 'github_pat_' },
    @{ Name = "GitHub classic token"; Pattern = 'ghp_' },
    @{ Name = "OpenAI/DeepSeek-style key"; Pattern = 'sk-' },
    @{ Name = "Bilibili SESSDATA"; Pattern = 'BILI_SESSDATA=' },
    @{ Name = "Bilibili csrf"; Pattern = 'BILI_JCT=' },
    @{ Name = "Bilibili buvid3"; Pattern = 'BILI_BUVID3=' },
    @{ Name = "Bilibili ac_time_value"; Pattern = 'BILI_AC_TIME_VALUE=' }
  )

  foreach ($matcher in $secretMatchers) {
    $rgArgs = @(
      "--line-number",
      "--hidden",
      "-F",
      "--glob", "!.git/**",
      "--glob", "!scripts/media.local.env.ps1",
      "--glob", "!scripts/publish_private_github.ps1",
      "--glob", "!data/**",
      "--glob", "!docs/**",
      $matcher.Pattern,
      "."
    )

    $matches = & rg @rgArgs 2>$null
    if ($LASTEXITCODE -eq 0 -and $matches) {
      Fail "Secret-like content matched $($matcher.Name):`n$matches"
    }
  }
}

if ([string]::IsNullOrWhiteSpace($token)) {
  Fail "Set GITHUB_TOKEN in this PowerShell session before running this script."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Fail "Git is required."
}
if (-not (Get-Command rg -ErrorAction SilentlyContinue)) {
  Fail "ripgrep (rg) is required for the secret scan."
}

Set-Location $projectRoot
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

$hadLocalEnv = Test-Path $localEnv
try {
  if ($hadLocalEnv) {
    Copy-Item -LiteralPath $localEnv -Destination $backupEnv -Force
    Write-Host "Backed up local env to $backupEnv"
  }

  if (-not (Test-Path ".git")) {
    git init
  }
  git branch -M $Branch

  git add -A
  git reset -- scripts/media.local.env.ps1 2>$null

  Assert-CleanSecrets

  Write-Host "Creating or reusing private GitHub repository $Owner/$Repo"
  $repoInfo = $null
  try {
    $repoInfo = Invoke-GitHubApi "GET" "https://api.github.com/repos/$Owner/$Repo"
  } catch {
    $body = @{
      name = $Repo
      private = $true
      has_issues = $true
      has_projects = $false
      has_wiki = $false
      auto_init = $false
    }
    $repoInfo = Invoke-GitHubApi "POST" "https://api.github.com/user/repos" $body
  }

  if (-not $repoInfo.private) {
    Fail "Repository $Owner/$Repo exists but is not private. Refusing to push."
  }

  if (git diff --cached --quiet) {
    Write-Host "No staged changes to commit."
  } else {
    git commit -m $CommitMessage
  }

  $remoteUrl = "https://github.com/$Owner/$Repo.git"
  if (git remote get-url origin *> $null) {
    git remote set-url origin $remoteUrl
  } else {
    git remote add origin $remoteUrl
  }

  $auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$token"))
  git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $auth" push -u origin $Branch
  git remote set-url origin $remoteUrl

  Write-Host "Published private repository: $remoteUrl"
} finally {
  if ($hadLocalEnv -and (Test-Path $backupEnv)) {
    Copy-Item -LiteralPath $backupEnv -Destination $localEnv -Force
    Write-Host "Restored local env from backup."
  }
}


