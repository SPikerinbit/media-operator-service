
# Media Operator desktop preview dependencies

The installer includes Python runtime components and the Python libraries described in the accompanying license directory. It also includes three independent command-line programs.

| Component | Binary provenance and source |
| --- | --- |
| FFmpeg and ffprobe | yt-dlp/FFmpeg-Builds autobuild-2026-11-08-18-52, win64-gpl, version N-128713-g0f89d936b3. [Exact FFmpeg revision](https://github.com/FFmpeg/FFmpeg/tree/0f89d936b3) and [build recipes, patches, and dependency definitions](https://github.com/yt-dlp/FFmpeg-Builds/tree/2e105eceb226411f9a56c821306c2c2d00b7a389). The build enables GPL and version 3. |
| yt-dlp and EJS | Official yt-dlp Windows x64 executable, 2026.10.26. [Release, licensing information and source archive](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.10.26). The frozen Windows executable includes GPLv3+ components. [EJS sources](https://github.com/yt-dlp/ejs). |
| Deno | Official Windows x64 Deno v2.9.8. [Source and license](https://github.com/denoland/deno/tree/v2.9.8). |
| WebView2 | Microsoft Evergreen Runtime bootstrapper for machines that need it. [Distribution information](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution). |
| Whisper models | Downloaded on demand. [Systran model files](https://huggingface.co/Systran/faster-whisper-small). |
| Optional NVIDIA acceleration | NVIDIA CUDA 12 and cuDNN 9, downloaded separately from NVIDIA at the user's request. [NVIDIA release and license information](https://docs.nvidia.com/cudnn/latest/installation/backend/windows.html). |

When sharing this preview, keep the relevant license material and corresponding source accessible alongside the installer.
The installer also includes the Adobe Source Han Sans CN 2.005R and Source Han Serif CN 2.003R subtitle fonts (Light, Regular and Bold) under the SIL Open Font License 1.1. The bundled licenses identify the original copyright holders.
