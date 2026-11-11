
param(
    [Parameter(Mandatory)][string]$BuildDir,
    [Parameter(Mandatory)][string]$OutputDir,
    [Parameter(Mandatory)][string]$InnoCompiler,
    [string]$PythonExe = "python"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$assets = Join-Path $BuildDir "assets"
$dist = Join-Path $BuildDir "dist"
$application = Join-Path $dist "MediaOperator"

function Get-VerifiedAsset($Name, $Url, $Hash) {
    $path = Join-Path $assets $Name
    if (-not (Test-Path -LiteralPath $path)) {
        curl.exe --fail --location --silent --show-error --retry 3 $Url -o $path
        if ($LASTEXITCODE -ne 0) { throw "Could not download $Name" }
    }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $Hash) {
        throw "SHA-256 mismatch for $Name. Remove the bad cached file and retry."
    }
    return $path
}

New-Item -ItemType Directory -Force $assets, $OutputDir | Out-Null
$ffmpegArchive = Get-VerifiedAsset "ffmpeg.zip" "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/autobuild-2026-11-08-18-52/ffmpeg-N-128713-g0f89d936b3-win64-gpl.zip" "7f29103f8b234207bd7e7b35a8d59367760cc031753da69e546c29a03083f1df"
$nvencArchive = Get-VerifiedAsset "ffmpeg-8.0.1-essentials_build.zip" "https://github.com/GyanD/codexffmpeg/releases/download/8.0.1/ffmpeg-8.0.1-essentials_build.zip" "e2aaeaa0fdbc397d4794828086424d4aaa2102cef1fb6874f6ffd29c0b88b673"
$denoArchive = Get-VerifiedAsset "deno.zip" "https://github.com/denoland/deno/releases/download/v2.9.8/deno-x86_64-pc-windows-msvc.zip" "cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf"
$yt = Get-VerifiedAsset "yt-dlp.exe" "https://github.com/yt-dlp/yt-dlp/releases/download/2026.10.26/yt-dlp.exe" "f5389d3698ecde4ef06f4e6b1ce0294fe9ac1396228c8990b8d3416d6d177a7d"
$sans = Get-VerifiedAsset "source-han-sans-cn.zip" "https://github.com/adobe-fonts/source-han-sans/releases/download/2.005R/19_SourceHanSansCN.zip" "3a769d1b082ebd813cdb4c06ea57d29b340bce548edcc8e61976b78ca28e6236"
$serif = Get-VerifiedAsset "source-han-serif-cn.zip" "https://github.com/adobe-fonts/source-han-serif/releases/download/2.003R/14_SourceHanSerifCN.zip" "aa3f9134809de83bb2add0bd965e61421772ce2fd8628fe98516b77c93e1d819"
$webview = Join-Path $assets "WebView2Setup.exe"
if (-not (Test-Path -LiteralPath $webview)) {
    curl.exe --fail --location --silent --show-error --retry 3 "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -o $webview
    if ($LASTEXITCODE -ne 0) { throw "Could not download WebView2 bootstrapper" }
}
$signature = Get-AuthenticodeSignature -LiteralPath $webview
if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "CN=Microsoft Corporation") {
    throw "Invalid Microsoft signature for the WebView2 bootstrapper"
}

$ffmpegDir = Join-Path $assets "ffmpeg-pinned"
New-Item -ItemType Directory -Force $ffmpegDir | Out-Null
if (-not (Get-ChildItem -LiteralPath $ffmpegDir -Recurse -Filter "ffmpeg.exe")) {
    tar.exe -xf $ffmpegArchive -C $ffmpegDir
    if ($LASTEXITCODE -ne 0) { throw "Could not extract FFmpeg" }
}
$nvencDir = Join-Path $assets "ffmpeg-nvenc-8.0.1"
$nvencExe = Join-Path $nvencDir "ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe"
if (-not (Test-Path -LiteralPath $nvencExe)) {
    New-Item -ItemType Directory -Force $nvencDir | Out-Null
    tar.exe -xf $nvencArchive -C $nvencDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $nvencExe)) { throw "Could not extract NVENC-compatible FFmpeg" }
}
if (-not (Test-Path -LiteralPath (Join-Path $assets "deno.exe"))) {
    tar.exe -xf $denoArchive -C $assets
    if ($LASTEXITCODE -ne 0) { throw "Could not extract Deno" }
}

Push-Location (Join-Path $root "frontend")
try {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "Could not install desktop frontend dependencies" }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "Desktop frontend build failed" }
} finally {
    Pop-Location
}

& $PythonExe -m PyInstaller --noconfirm --distpath $dist --workpath (Join-Path $BuildDir "freeze") (Join-Path $root "packaging\media_operator.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$frontend = Join-Path $root "app\static\desktop-ui"
$static = Join-Path $application "_internal\app\static"
New-Item -ItemType Directory -Force $static | Out-Null
Copy-Item -LiteralPath $frontend -Destination $static -Recurse -Force
$bundledFrontend = Join-Path $static "desktop-ui"
$assetReferences = [regex]::Matches((Get-Content -LiteralPath (Join-Path $bundledFrontend "index.html") -Raw),
    '/static/desktop-ui/(assets/[^"\s]+)')
if ($assetReferences.Count -lt 2) { throw "Desktop frontend entry point is missing its generated assets" }
foreach ($asset in $assetReferences) {
    if (-not (Test-Path -LiteralPath (Join-Path $bundledFrontend $asset.Groups[1].Value) -PathType Leaf)) {
        throw "Missing bundled desktop asset: $($asset.Groups[1].Value)"
    }
}

$tools = Join-Path $application "tools"
New-Item -ItemType Directory -Force $tools | Out-Null
foreach ($name in "ffmpeg.exe", "ffprobe.exe") {
    $binary = Get-ChildItem -LiteralPath $ffmpegDir -Recurse -Filter $name | Select-Object -First 1
    if (-not $binary) { throw "Missing $name" }
    Copy-Item -LiteralPath $binary.FullName -Destination $tools
}
Copy-Item -LiteralPath $nvencExe -Destination (Join-Path $tools "ffmpeg-burn.exe")
Copy-Item -LiteralPath $yt, (Join-Path $assets "deno.exe") -Destination $tools
$licenses = Join-Path $application "licenses"
$fonts = Join-Path $application "fonts"
New-Item -ItemType Directory -Force $fonts, $licenses | Out-Null
foreach ($font in @(@{Archive=$sans; Family="SourceHanSansCN"}, @{Archive=$serif; Family="SourceHanSerifCN"})) {
    $family = $font.Family
    $staging = Join-Path $BuildDir $family
    New-Item -ItemType Directory -Force $staging | Out-Null
    & tar.exe -xf $font.Archive -C $staging "SubsetOTF/CN/$family-Light.otf" "SubsetOTF/CN/$family-Regular.otf" "SubsetOTF/CN/$family-Bold.otf" "LICENSE.txt"
    if ($LASTEXITCODE -ne 0) { throw "Could not extract $family" }
    Copy-Item -Path (Join-Path $staging "SubsetOTF\CN\*.otf") -Destination $fonts
    Copy-Item -LiteralPath (Join-Path $staging "LICENSE.txt") -Destination (Join-Path $licenses "$family-OFL.txt")
}
& $PythonExe (Join-Path $root "packaging\collect_notices.py") $licenses
if ($LASTEXITCODE -ne 0) { throw "Could not collect Python notices" }
Copy-Item -LiteralPath (Join-Path $root "packaging\THIRD_PARTY.md") -Destination $licenses
Copy-Item -LiteralPath (Join-Path $root "docs\DESKTOP_QUICKSTART.md") -Destination $application
Get-ChildItem -LiteralPath (Join-Path $root "frontend/src/vendor") -Recurse -File -Filter "LICENSE" |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $licenses "$($_.Directory.Name)-LICENSE.txt") }
$nodeLicenses = Join-Path $licenses "frontend"
Push-Location (Join-Path $root "frontend")
try {
    foreach ($packagePath in (& npm.cmd ls --omit=dev --all --parseable)) {
        if ($packagePath -notmatch '[\\/]node_modules[\\/]') { continue }
        $packageInfo = Get-Content -LiteralPath (Join-Path $packagePath "package.json") -Raw | ConvertFrom-Json
        $label = ($packageInfo.name -replace '[/@]', '-') + '-' + $packageInfo.version
        $licenseFolder = Join-Path $nodeLicenses $label
        Get-ChildItem -LiteralPath $packagePath -File -Filter 'LICENSE*' | ForEach-Object {
            New-Item -ItemType Directory -Force $licenseFolder | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $licenseFolder
        }
    }
} finally {
    Pop-Location
}
$extraNotices = Join-Path $BuildDir "sources"
if (Test-Path -LiteralPath $extraNotices) {
    Get-ChildItem -LiteralPath $extraNotices -File -Filter "*.txt" | Copy-Item -Destination $licenses
}

$version = (Get-Content -LiteralPath (Join-Path $root "VERSION") -Raw).Trim()
& $InnoCompiler "/DAppVersion=$version" "/DMediaDist=$application" "/DMediaOutput=$OutputDir" "/DWebViewSetup=$webview" (Join-Path $root "packaging\MediaOperator.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed" }

$installer = Join-Path $OutputDir "MediaOperatorSetup.exe"
$checksum = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
"$checksum *MediaOperatorSetup.exe" | Set-Content -LiteralPath (Join-Path $OutputDir "MediaOperatorSetup.sha256") -Encoding ascii
