from __future__ import annotations

# ruff: noqa: F821
"""ASS subtitles and burning them into video.

Executed inside app.main so callers and tests keep patching that module.
"""

def ffmpeg_escape_path(file_path: Path) -> str:
    return str(file_path).replace("\\", "/").replace(":", r"\:")


def ass_timestamp(total_seconds: float) -> str:
    if total_seconds < 0:
        total_seconds = 0.0
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    centiseconds = int(round((total_seconds - int(total_seconds)) * 100))
    if centiseconds >= 100:
        seconds += 1
        centiseconds -= 100
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def srt_text_to_ass_text(text: str) -> str:
    text = text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    return text.replace("\n", r"\N")


def ass_color(hex_color: str, default: str) -> str:
    return ass_color_with_alpha(hex_color, default, 0)


def ass_color_with_alpha(hex_color: str, default: str, alpha: int) -> str:
    value = (hex_color or default).strip()
    if value.startswith("#"):
        value = value[1:]
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        value = default.lstrip("#")
    red = value[0:2]
    green = value[2:4]
    blue = value[4:6]
    alpha = max(0, min(255, int(alpha)))
    return f"&H{alpha:02X}{blue.upper()}{green.upper()}{red.upper()}"


def subtitle_alignment(position: SubtitlePosition) -> int:
    return {"bottom": 2, "middle": 5, "top": 8}[position]


def subtitle_margin_v(position: SubtitlePosition, margin: SubtitleMargin, height: int) -> int:
    if margin == "compact":
        factor = 0.045
    elif margin == "normal":
        factor = 0.08
    elif margin == "high":
        factor = 0.13
    else:
        factor = 0.08 if position == "bottom" else 0.07
    return max(18, min(260, int(height * factor)))


def subtitle_font_size_value(size: SubtitleFontSize, height: int) -> int:
    if size == "small":
        factor = 0.024
    elif size == "medium":
        factor = 0.032
    elif size == "large":
        factor = 0.042
    else:
        factor = 0.028
    return max(18, min(64, int(height * factor)))


def subtitle_style_from_legacy(
    *,
    subtitle_font_size: SubtitleFontSize,
    subtitle_color: str,
    subtitle_outline_color: str,
    subtitle_position: SubtitlePosition,
    subtitle_margin: SubtitleMargin,
    height: int,
) -> SubtitleStyle:
    return SubtitleStyle(
        font_family=DEFAULT_FONT,
        font_size=subtitle_font_size_value(subtitle_font_size, height),
        font_size_mode="auto" if subtitle_font_size == "auto" else "manual",
        font_weight=700,
        primary_color=subtitle_color,
        outline_color=subtitle_outline_color,
        outline_width=3,
        shadow=1,
        position=subtitle_position,
        y_offset_percent=max(0, min(30, int(subtitle_margin_v(subtitle_position, subtitle_margin, height) / max(height, 1) * 100))),
        max_width_percent=86,
        line_spacing=1.15,
        bilingual_order="en_top_zh_bottom",
        background_enabled=False,
    )


def subtitle_alignment_from_position(position: SubtitlePosition) -> int:
    return {"bottom": 2, "middle": 5, "top": 8}[position]


def scaled_style_value(value: int | float, canvas_height: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    scaled = int(round(float(value) * canvas_height / 1080))
    if maximum is not None:
        scaled = min(maximum, scaled)
    return max(minimum, scaled)


def subtitle_margin_from_style(style: SubtitleStyle, height: int) -> int:
    if style.position == "middle":
        return 0
    return max(8, int(height * style.y_offset_percent / 100))


def subtitle_horizontal_margin(style: SubtitleStyle, width: int) -> int:
    side_percent = max(0, (100 - style.max_width_percent) / 2)
    return max(0, int(width * side_percent / 100))


def split_bilingual_content(content: str) -> tuple[str, str]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return "", ""
    english = lines[0]
    translated = "\n".join(lines[1:]).strip()
    return english, translated


def write_subtitle_mode_srt(
    job_id: str,
    subtitle_path: Path,
    *,
    output_mode: SubtitleOutputMode,
    bilingual_order: SubtitleBilingualOrder,
) -> Path:
    if (DESKTOP and output_mode == "en_only") or (output_mode == "bilingual" and bilingual_order == "en_top_zh_bottom"):
        return subtitle_path
    subtitles = list(srt.parse(subtitle_path.read_text(encoding="utf-8")))
    transformed: list[srt.Subtitle] = []
    for index, subtitle in enumerate(subtitles, start=1):
        english, translated = split_bilingual_content(subtitle.content)
        if output_mode == "en_only":
            content = english or subtitle.content.strip()
        elif output_mode == "zh_only":
            content = translated or english or subtitle.content.strip()
        elif bilingual_order == "zh_top_en_bottom" and translated:
            content = f"{translated}\n{english}" if english else translated
        else:
            content = subtitle.content.strip()
        transformed.append(srt.Subtitle(index=index, start=subtitle.start, end=subtitle.end, content=content))
    mode_path = artifact_path(job_id, f"{output_mode}.srt")
    mode_path.write_text(srt.compose(transformed), encoding="utf-8")
    return mode_path


def build_ass_from_srt(
    job_id: str,
    subtitle_path: Path,
    *,
    font_name: str,
    font_size: int,
    margin_v: int,
    primary_color: str = "#ffffff",
    outline_color: str = "#000000",
    alignment: int = 2,
    font_weight: int = 700,
    outline_width: int = 3,
    shadow: int = 1,
    margin_l: int = 80,
    margin_r: int = 80,
    background_enabled: bool = False,
    background_color: str = "#000000",
    background_opacity: int = 45,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> Path:
    srt_text = subtitle_path.read_text(encoding="utf-8")
    subtitles = list(srt.parse(srt_text))
    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {play_res_x}",
            f"PlayResY: {play_res_y}",
            "",
            "[V4+ Styles]",
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
            f"Style: Default,{font_name},{font_size},{ass_color(primary_color, '#ffffff')},&H000000FF,{ass_color(outline_color, '#000000')},{ass_color_with_alpha(background_color, '#000000', int((100 - background_opacity) * 255 / 100))},{-1 if font_weight >= 700 else 0},0,0,0,100,100,0,0,{3 if background_enabled else 1},{outline_width},{shadow},{alignment},{margin_l},{margin_r},{margin_v},1",
            "",
            "[Events]",
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
        ]
    )
    event_lines: list[str] = []
    for subtitle in subtitles:
        start = ass_timestamp(subtitle.start.total_seconds())
        end = ass_timestamp(subtitle.end.total_seconds())
        text = srt_text_to_ass_text(subtitle.content.strip())
        event_lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    ass_path = artifact_path(job_id, "bilingual.ass")
    ass_path.write_text(header + "\n" + "\n".join(event_lines) + "\n", encoding="utf-8")
    return ass_path


def detect_video_size(source_path: Path) -> tuple[int, int]:
    cmd = [
        FFPROBE_BIN,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0:s=x",
        str(source_path),
    ]
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        creationflags=WINDOW_FLAGS,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffprobe failed")
    raw = completed.stdout.strip()
    if "x" not in raw:
        raise RuntimeError("ffprobe did not return width/height")
    width_text, height_text = raw.split("x", 1)
    return int(width_text), int(height_text)


def detect_video_duration_seconds(source_path: Path) -> float:
    cmd = [
        FFPROBE_BIN,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(source_path),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False, creationflags=WINDOW_FLAGS)
    if completed.returncode != 0:
        return 0.0
    try:
        return max(0.0, float(completed.stdout.strip() or 0.0))
    except Exception:
        return 0.0


def even_dimension(value: float) -> int:
    return max(2, int(value // 2) * 2)


def aspect_ratio_value(aspect_ratio: AspectRatio) -> float | None:
    values = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0}
    return values.get(aspect_ratio)


def compute_render_canvas(source_width: int, source_height: int, aspect_ratio: AspectRatio) -> tuple[int, int]:
    standard = {
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
    }.get(aspect_ratio)
    if standard is not None:
        return standard
    if source_width <= 0 or source_height <= 0:
        return 1080, 1920
    return even_dimension(source_width), even_dimension(source_height)


def aspect_ratio_filter(aspect_ratio: AspectRatio) -> str | None:
    canvas = {
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
    }.get(aspect_ratio)
    if canvas is None:
        return None
    width, height = canvas
    return fixed_canvas_filter(width, height)


def fixed_canvas_filter(width: int, height: int) -> str:
    width = even_dimension(width)
    height = even_dimension(height)
    ratio = width / height
    return (
        f"scale=w='if(gt(a,{ratio}),{width},-2)':h='if(gt(a,{ratio}),-2,{height})',"
        f"pad=w={width}:h={height}:x=(ow-iw)/2:y=(oh-ih)/2:color=black,setsar=1"
    )


def burn_subtitle(
    job_id: str,
    source_path: Path,
    subtitle_path: Path,
    *,
    aspect_ratio: AspectRatio = "source",
    subtitle_font_size: SubtitleFontSize = "auto",
    subtitle_color: str = "#ffffff",
    subtitle_outline_color: str = "#000000",
    subtitle_position: SubtitlePosition = "bottom",
    subtitle_margin: SubtitleMargin = "auto",
    subtitle_output_mode: SubtitleOutputMode = "bilingual",
    subtitle_style: SubtitleStyle | None = None,
    burn_encoder: BurnEncoder | None = None,
    output_name: str | None = None,
    progress_callback: Callable[[int, str, str | None], None] | None = None,
) -> Path:
    selected_encoder = selected_burn_encoder(burn_encoder)
    if burn_encoder == "nvenc" and selected_encoder != "nvenc":
        raise RuntimeError("NVIDIA NVENC 无法启动。请在「设置 → 检测本地环境」检查驱动，或选择自动/CPU。")
    output_path = artifact_path(job_id, "final.mp4")
    width = 1920
    height = 1080
    try:
        width, height = detect_video_size(source_path)
    except Exception:
        pass
    duration_seconds = detect_video_duration_seconds(source_path)
    if progress_callback:
        progress_callback(8, "probing video and building subtitle style", None)
    canvas_width, canvas_height = compute_render_canvas(width, height, aspect_ratio)
    style = subtitle_style or subtitle_style_from_legacy(
        subtitle_font_size=subtitle_font_size,
        subtitle_color=subtitle_color,
        subtitle_outline_color=subtitle_outline_color,
        subtitle_position=subtitle_position,
        subtitle_margin=subtitle_margin,
        height=canvas_height,
    )
    if style.font_size_mode == "auto":
        style = style.model_copy(update={"font_size": subtitle_font_size_value("auto", canvas_height)})
    font_size = scaled_style_value(style.font_size, canvas_height, minimum=10)
    outline_width = scaled_style_value(style.outline_width, canvas_height, minimum=0, maximum=48)
    shadow = scaled_style_value(style.shadow, canvas_height, minimum=0, maximum=48)
    subtitle_render_path = write_subtitle_mode_srt(
        job_id,
        subtitle_path,
        output_mode=subtitle_output_mode,
        bilingual_order=style.bilingual_order,
    )
    ass_path = build_ass_from_srt(
        job_id,
        subtitle_render_path,
        font_name=style.font_family or DEFAULT_FONT,
        font_size=font_size,
        margin_v=subtitle_margin_from_style(style, canvas_height),
        primary_color=style.primary_color,
        outline_color=style.outline_color,
        alignment=subtitle_alignment_from_position(style.position),
        font_weight=style.font_weight,
        outline_width=outline_width,
        shadow=shadow,
        margin_l=subtitle_horizontal_margin(style, canvas_width),
        margin_r=subtitle_horizontal_margin(style, canvas_width),
        background_enabled=style.background_enabled,
        background_color=style.background_color,
        background_opacity=style.background_opacity,
        play_res_x=canvas_width,
        play_res_y=canvas_height,
    )
    subtitle_filter = f"ass='{ass_path.name if DESKTOP else ffmpeg_escape_path(ass_path)}'"
    fonts_dir = subtitle_fonts_dir(style.font_family)
    system_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    if fonts_dir.exists() and (not DESKTOP or fonts_dir != system_fonts):
        subtitle_filter += f":fontsdir='{ffmpeg_escape_path(fonts_dir)}'"
    video_filters = []
    ratio_filter = aspect_ratio_filter(aspect_ratio)
    if ratio_filter:
        video_filters.append(ratio_filter)
    video_filters.append(subtitle_filter)
    def build_ffmpeg_burn_cmd(encoder: str) -> list[str]:
        return [
            FFMPEG_BURN_BIN if encoder == "nvenc" else FFMPEG_BIN,
            "-y",
            "-i",
            str(source_path),
            "-vf",
            ",".join(video_filters),
            *ffmpeg_video_encoder_args(encoder),
            "-c:a",
            "aac" if DESKTOP else "copy",
            *(["-movflags", "+faststart"] if DESKTOP else []),
            "-progress",
            "pipe:1",
            "-nostats",
            str(output_path),
        ]

    def handle_ffmpeg_progress(line: str) -> None:
        if not progress_callback:
            return
        if line.startswith("out_time_ms=") and duration_seconds > 0:
            try:
                out_ms = float(line.split("=", 1)[1] or 0)
            except Exception:
                return
            local = min(98, max(10, int(10 + (out_ms / 1_000_000.0 / duration_seconds) * 86)))
            progress_callback(local, f"rendered {out_ms / 1_000_000.0:.1f}s / {duration_seconds:.1f}s", line)
        elif line == "progress=end":
            progress_callback(99, "finalizing output video", line)

    actual_encoder = selected_encoder
    fallback_error = ""
    if progress_callback:
        progress_callback(10, "NVIDIA NVENC 编码" if actual_encoder == "nvenc" else "CPU 编码", None)
    try:
        run_command_streaming(
            build_ffmpeg_burn_cmd(actual_encoder),
            cwd=job_dir(job_id) if DESKTOP else ROOT_DIR,
            log_dir=job_dir(job_id),
            log_name=f"ffmpeg-burn-{actual_encoder}",
            on_stdout_line=handle_ffmpeg_progress,
        )
    except Exception as exc:
        if actual_encoder != "nvenc":
            raise
        if burn_encoder == "nvenc":
            raise RuntimeError(f"NVIDIA NVENC 编码失败：{exc}") from exc
        fallback_error = str(exc)
        actual_encoder = "cpu"
        if progress_callback:
            progress_callback(12, "NVIDIA 编码失败，改用 CPU", fallback_error[:500])
        run_command_streaming(
            build_ffmpeg_burn_cmd(actual_encoder),
            cwd=job_dir(job_id) if DESKTOP else ROOT_DIR,
            log_dir=job_dir(job_id),
            log_name=f"ffmpeg-burn-{actual_encoder}",
            on_stdout_line=handle_ffmpeg_progress,
        )
    artifact_path(job_id, "burn_runtime.json").write_text(
        json.dumps(
            {
                "configured_encoder": burn_encoder or FFMPEG_BURN_ENCODER,
                "selected_encoder": selected_encoder,
                "actual_encoder": actual_encoder,
                "nvenc_available": ffmpeg_nvenc_available(),
                "cuda_hwaccel_available": ffmpeg_cuda_hwaccel_available(),
                "nvenc_preset": FFMPEG_NVENC_PRESET,
                "nvenc_tune": FFMPEG_NVENC_TUNE,
                "nvenc_cq": FFMPEG_NVENC_CQ,
                "fallback_error": fallback_error,
                "filters": video_filters,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if output_name:
        download_name_path = artifact_path(job_id, f"{safe_download_filename(output_name)}.mp4")
        if download_name_path.name != output_path.name:
            try:
                shutil.copyfile(output_path, download_name_path)
            except Exception:
                pass
    return output_path
