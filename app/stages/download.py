from __future__ import annotations

# ruff: noqa: F821
"""Source download, local import, and the command runners.

Executed inside app.main so callers and tests keep patching that module.
"""

def safe_job_artifact(job_id: str, name: str) -> Path:
    path = artifact_path(job_id, name).resolve()
    base = job_dir(job_id).resolve()
    if base not in path.parents and path != base:
        raise ValueError("invalid artifact path")
    return path


def resolve_local_artifact_from_url(url: str) -> tuple[str, Path]:
    parsed = urlparse(url)
    if not parsed.path.startswith("/files/"):
        raise ValueError("url must be a /files/{job_id}/{filename} resource")
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 3:
        raise ValueError("invalid files url")
    _, job_id, filename = parts
    path = safe_job_artifact(job_id, filename)
    if not path.exists():
        raise ValueError("artifact not found")
    return job_id, path


def run_command(cmd: list[str], *, cwd: Path | None = None, log_dir: Path | None = None, log_name: str = "command") -> None:
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / f"{log_name}.out.log"
        stderr_path = log_dir / f"{log_name}.err.log"
        with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_file, stderr_path.open(
            "w", encoding="utf-8", errors="replace"
        ) as stderr_file:
            completed = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                check=False,
                creationflags=WINDOW_FLAGS,
            )
        if completed.returncode != 0:
            stderr = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
            stdout = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
            message = stderr or stdout or f"command failed with exit code {completed.returncode}"
            raise RuntimeError(message)
        return

    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
        creationflags=WINDOW_FLAGS,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or f"command failed with exit code {completed.returncode}"
        raise RuntimeError(stderr)


def run_command_streaming(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    log_dir: Path | None = None,
    log_name: str = "command",
    on_stdout_line: Callable[[str], None] | None = None,
    on_stderr_line: Callable[[str], None] | None = None,
    env: dict[str, str] | None = None,
) -> None:
    log_dir = log_dir or tempfile.mkdtemp(prefix="media-command-")
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{log_name}.out.log"
    stderr_path = log_dir / f"{log_name}.err.log"
    stdout_tail: list[str] = []
    stderr_tail: list[str] = []

    process = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
        encoding="utf-8" if DESKTOP else None,
        errors="replace",
        creationflags=WINDOW_FLAGS,
        env=env,
    )

    def reader(pipe: Any, path: Path, tail: list[str], callback: Callable[[str], None] | None) -> None:
        with path.open("w", encoding="utf-8", errors="replace") as handle:
            try:
                for line in iter(pipe.readline, ""):
                    text = line.rstrip("\r\n")
                    handle.write(text + "\n")
                    handle.flush()
                    tail.append(text)
                    del tail[:-20]
                    if callback:
                        callback(text)
            finally:
                pipe.close()

    stdout_thread = threading.Thread(target=reader, args=(process.stdout, stdout_path, stdout_tail, on_stdout_line), daemon=True)
    stderr_thread = threading.Thread(target=reader, args=(process.stderr, stderr_path, stderr_tail, on_stderr_line), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    return_code = process.wait()
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    if return_code != 0:
        message = "\n".join(stderr_tail or stdout_tail).strip() or f"command failed with exit code {return_code}"
        raise RuntimeError(message)


_ffmpeg_encoders_cache: set[str] | None = None
_ffmpeg_hwaccels_cache: set[str] | None = None


def ffmpeg_encoders() -> set[str]:
    global _ffmpeg_encoders_cache
    if _ffmpeg_encoders_cache is not None:
        return _ffmpeg_encoders_cache
    try:
        completed = subprocess.run(
            [FFMPEG_BIN, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=WINDOW_FLAGS,
        )
        text = f"{completed.stdout}\n{completed.stderr}"
    except Exception:
        text = ""
    _ffmpeg_encoders_cache = set(re.findall(r"\b[\w]+(?:_[\w]+)+\b", text))
    return _ffmpeg_encoders_cache


def ffmpeg_hwaccels() -> set[str]:
    global _ffmpeg_hwaccels_cache
    if _ffmpeg_hwaccels_cache is not None:
        return _ffmpeg_hwaccels_cache
    try:
        completed = subprocess.run(
            [FFMPEG_BIN, "-hide_banner", "-hwaccels"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=WINDOW_FLAGS,
        )
        text = f"{completed.stdout}\n{completed.stderr}"
    except Exception:
        text = ""
    names: set[str] = set()
    for line in text.splitlines():
        value = line.strip().lower()
        if value and re.fullmatch(r"[a-z0-9_]+", value):
            names.add(value)
    _ffmpeg_hwaccels_cache = names
    return _ffmpeg_hwaccels_cache


@lru_cache(maxsize=4)
def nvenc_runtime_error(binary: str) -> str:
    try:
        completed = subprocess.run(
            [binary, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=s=320x240:d=0.1",
             "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, errors="replace", timeout=12, creationflags=WINDOW_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)
    return "" if completed.returncode == 0 else completed.stderr.strip() or "NVENC 编码检测失败"


def ffmpeg_nvenc_available() -> bool:
    if DESKTOP:
        return not nvenc_runtime_error(FFMPEG_BURN_BIN)
    return "h264_nvenc" in ffmpeg_encoders()


def ffmpeg_cuda_hwaccel_available() -> bool:
    return "cuda" in ffmpeg_hwaccels()


def selected_burn_encoder(mode: str | None = None) -> str:
    return "nvenc" if (mode or FFMPEG_BURN_ENCODER) != "cpu" and ffmpeg_nvenc_available() else "cpu"


def ffmpeg_video_encoder_args(encoder: str) -> list[str]:
    if encoder == "nvenc":
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            FFMPEG_NVENC_PRESET,
            "-tune",
            FFMPEG_NVENC_TUNE,
            "-rc",
            "vbr",
            "-cq",
            str(FFMPEG_NVENC_CQ),
            "-b:v",
            "0",
            "-pix_fmt",
            "yuv420p",
        ]
    return ["-c:v", "libx264", "-pix_fmt", "yuv420p"]


def build_yt_dlp_format_selector(resolution: Resolution = "best", fps: Fps = "source") -> str:
    video_filters: list[str] = []
    if resolution != "best":
        height = {"1080p": 1080, "1440p": 1440, "2160p": 2160}[resolution]
        video_filters.append(f"height<={height}")
    if fps != "source":
        video_filters.append(f"fps<={fps}")
    if not video_filters:
        return DEFAULT_YT_DLP_FORMAT
    filter_text = "][".join(video_filters)
    mp4_filter_text = f"{filter_text}][ext=mp4][vcodec^=avc1"
    m4a_audio = "bestaudio[ext=m4a]/bestaudio"
    return (
        f"bestvideo[{mp4_filter_text}]+{m4a_audio}/"
        f"best[ext=mp4][{filter_text}]/"
        f"bestvideo[{filter_text}]+bestaudio/"
        f"best[{filter_text}]/best"
    )


def to_windows_path(path: Path) -> str:
    raw = str(path)
    if os.name == "nt":
        return raw
    completed = subprocess.run(
        ["wslpath", "-w", raw],
        capture_output=True,
        text=True,
        check=False,
        creationflags=WINDOW_FLAGS,
    )
    if completed.returncode == 0:
        converted = completed.stdout.strip()
        if converted:
            return converted
    if raw.startswith("/mnt/") and len(raw) > 6 and raw[6] == "/":
        drive_letter = raw[5].upper()
        remainder = raw[7:].replace("/", "\\")
        return f"{drive_letter}:\\{remainder}"
    return raw


def yt_dlp_ffmpeg_location() -> str:
    configured = str(FFMPEG_BIN or "").strip()
    if not configured or configured.lower() == "ffmpeg":
        return ""
    path = Path(configured)
    if path.name.lower().startswith("ffmpeg"):
        return str(path.parent)
    return str(path)


def online_media_proxy(url: str) -> str | None:
    if YT_DLP_PROXY or not DESKTOP:
        return YT_DLP_PROXY or None
    target = urlparse(url)
    if os.name == "nt":
        windows_proxies = urllib_request.getproxies_registry()
        if windows_proxies:
            if urllib_request.proxy_bypass_registry(target.hostname or ""):
                return None
            return windows_proxies.get(target.scheme) or windows_proxies.get("all")
    if urllib_request.proxy_bypass(target.hostname or ""):
        return None
    proxies = urllib_request.getproxies()
    return proxies.get(target.scheme) or proxies.get("all")


def yt_dlp_network_flags(url: str) -> list[str]:
    proxy = online_media_proxy(url)
    if not DESKTOP:
        return ["--proxy", proxy] if proxy else []
    return ["--ignore-config", "--encoding", "utf-8", "--proxy", proxy or "",
            "--js-runtimes", f"deno:{Path(YT_DLP_BIN).with_name('deno.exe')}"]


def online_media_error(url: str, diagnostics: str) -> str:
    reason = diagnostics.lower()
    if DESKTOP:
        from app.desktop_sources import extract_error, site as site_of
        label = site_of(url)[0] or ("B 站" if video_url_kind(url) == "bilibili" else "YouTube")
        recognized = extract_error(url, diagnostics)
        if label in {"抖音", "小红书"} and recognized.code in {"site_blocked", "session_required", "no_stream"}:
            return str(recognized)
    else:
        label = "B 站" if video_url_kind(url) == "bilibili" else "YouTube"
    if any(term in reason for term in ("10061", "connection refused", "actively refused", "proxyerror")):
        return f"无法连接到{label}。请检查 Windows 系统代理或网络连接后重试。"
    if any(term in reason for term in ("timed out", "timeout", "getaddrinfo", "failed to establish", "network is unreachable")):
        return f"连接{label}超时或网络不可达，请检查网络后重试。"
    if "sign in" in reason or "login required" in reason:
        return f"{label}要求登录或验证，此链接暂时无法读取。"
    if "unavailable" in reason or "private video" in reason:
        return f"{label}上的视频暂不可用，请确认链接仍可访问。"
    return f"读取{label}素材失败，请核对链接后重试。详细信息已记录。"


def download_youtube(
    job_id: str,
    youtube_url: str,
    format_selector: str = DEFAULT_YT_DLP_FORMAT,
    progress_callback: Callable[[int, str, str | None], None] | None = None,
    *,
    audio_only: bool = False,
) -> Path:
    source_dir = job_dir(job_id)
    source_dir.mkdir(parents=True, exist_ok=True)
    if YT_DLP_BIN.lower().endswith(".exe"):
        output_template = to_windows_path(source_dir / "source.%(ext)s")
    else:
        output_template = str(source_dir / "source.%(ext)s")
    cmd = [
        YT_DLP_BIN,
        "--no-playlist",
        "--socket-timeout",
        str(YT_DLP_SOCKET_TIMEOUT),
        "--retries",
        str(YT_DLP_RETRIES),
        "--fragment-retries",
        str(YT_DLP_FRAGMENT_RETRIES),
        "--newline",
        "--merge-output-format",
        "mp4",
        "-f",
        format_selector,
        "-o",
        output_template,
        youtube_url,
    ]
    cmd[1:1] = yt_dlp_network_flags(youtube_url)
    if DESKTOP:
        metadata_file = source_dir / "source-metadata.jsonl"
        metadata_file.unlink(missing_ok=True)
        cmd[1:1] = [
            "--no-simulate", "--print-to-file", "after_move:%(.{title,description,thumbnail})j",
            to_windows_path(metadata_file) if YT_DLP_BIN.lower().endswith(".exe") else str(metadata_file),
        ]
    ffmpeg_location = yt_dlp_ffmpeg_location()
    if ffmpeg_location:
        cmd[1:1] = ["--ffmpeg-location", ffmpeg_location]
    def handle_yt_dlp_line(line: str) -> None:
        if not progress_callback:
            return
        percent_match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
        if percent_match:
            percent = float(percent_match.group(1))
            progress_callback(min(95, max(5, int(5 + percent * 0.9))), line.strip(), line)
            return
        if "[Merger]" in line:
            progress_callback(97, "merging video and audio", line)
        elif "[ExtractAudio]" in line or "[Fixup" in line:
            progress_callback(98, line.strip(), line)

    run_command_streaming(
        cmd,
        cwd=ROOT_DIR,
        log_dir=source_dir,
        log_name="yt-dlp",
        on_stdout_line=handle_yt_dlp_line,
        on_stderr_line=handle_yt_dlp_line,
    )

    candidates = sorted(
        [
            p
            for p in source_dir.iterdir()
            if p.is_file() and p.name.startswith("source.")
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if audio_only:
        candidates = [p for p in candidates if p.suffix.lower() in {".m4a", ".webm", ".mp3", ".opus", ".aac", ".ogg", ".wav"}]
        if candidates:
            return candidates[0]
    if not candidates:
        raise RuntimeError("yt-dlp finished but no source file was found")

    def probe_stream_types(path: Path) -> set[str]:
        completed = subprocess.run(
            [
                FFPROBE_BIN,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            creationflags=WINDOW_FLAGS,
        )
        if completed.returncode != 0:
            return set()
        return {line.strip() for line in completed.stdout.splitlines() if line.strip()}

    preferred = source_dir / "source.mp4"
    if preferred.exists():
        stream_types = probe_stream_types(preferred)
        if "video" in stream_types and "audio" in stream_types:
            return preferred

    video_candidates: list[Path] = []
    audio_candidates: list[Path] = []
    for candidate in candidates:
        stream_types = probe_stream_types(candidate)
        if "video" in stream_types:
            video_candidates.append(candidate)
        if stream_types == {"audio"}:
            audio_candidates.append(candidate)

    if video_candidates:
        chosen_video = video_candidates[0]
        chosen_video_types = probe_stream_types(chosen_video)
        if "audio" in chosen_video_types:
            return chosen_video
        if audio_candidates:
            merged_path = source_dir / "source.mp4"
            run_command(
                [
                    FFMPEG_BIN,
                    "-y",
                    "-i",
                    str(chosen_video),
                    "-i",
                    str(audio_candidates[0]),
                    "-c",
                    "copy",
                    str(merged_path),
                ]
            )
            merged_types = probe_stream_types(merged_path)
            if "video" in merged_types:
                return merged_path
        return chosen_video

    return candidates[0]


def ensure_placeholder_video(job_id: str, youtube_url: str) -> Path:
    placeholder = artifact_path(job_id, "source.txt")
    placeholder.write_text(
        f"placeholder source for {youtube_url}\ncreated_at={now_iso()}\n",
        encoding="utf-8",
    )
    return placeholder
