# Media Operator

Media Operator is a Windows desktop workspace for turning local media or YouTube sources into subtitled videos and source-grounded notes. The desktop app runs its media stages locally. DeepSeek translation and viewpoint generation are optional.

- **视频制作** imports and orders sources, previews subtitles, runs a local batch, and exports video and subtitles.
- **字幕分析** imports audio, video, or existing SRT/VTT files, then lets you review timestamped evidence and edit draft viewpoints.
- **Obsidian** stores the viewpoints you choose to publish, together with linked source notes. Successfully published drafts are cleared after the local write has been verified.

See the [Windows quick start and build instructions](docs/DESKTOP_QUICKSTART.md). The optional headless media API can be run with the included Docker Compose configuration.

Desktop source is in frontend, and the built assets are bundled by scripts/build_desktop.ps1. Keep credentials in the desktop settings and runtime data outside Git.
