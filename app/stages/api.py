from __future__ import annotations

# ruff: noqa: F821
"""HTTP API for the headless service and the shared preview routes.

Executed inside app.main so callers and tests keep patching that module.
"""

@app.on_event("startup")
def on_startup() -> None:
    ensure_dirs()


STATIC_DIR = ROOT_DIR / "app" / "static"
MEDIA_UI_DIR = STATIC_DIR / "desktop-ui"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        whisper_runtime = resolve_whisper_runtime(WHISPER_MODEL)
    except Exception as exc:
        whisper_runtime = {"error": str(exc)}
    return {
        "ok": True,
        "service": APP_NAME,
        "data_dir": str(DATA_DIR),
        "jobs_dir": str(JOBS_DIR),
        "allow_placeholder_artifacts": ALLOW_PLACEHOLDER_ARTIFACTS,
        "yt_dlp_bin": YT_DLP_BIN,
        "yt_dlp_proxy": YT_DLP_PROXY or None,
        "yt_dlp_ffmpeg_location": yt_dlp_ffmpeg_location() or None,
        "yt_dlp_socket_timeout": YT_DLP_SOCKET_TIMEOUT,
        "yt_dlp_retries": YT_DLP_RETRIES,
        "yt_dlp_fragment_retries": YT_DLP_FRAGMENT_RETRIES,
        "ffmpeg_bin": FFMPEG_BIN,
        "ffprobe_bin": FFPROBE_BIN,
        "ffmpeg": {
            "burn_encoder": FFMPEG_BURN_ENCODER,
            "selected_burn_encoder": selected_burn_encoder(),
            "nvenc_available": ffmpeg_nvenc_available(),
            "cuda_hwaccel_available": ffmpeg_cuda_hwaccel_available(),
            "nvenc_preset": FFMPEG_NVENC_PRESET,
            "nvenc_tune": FFMPEG_NVENC_TUNE,
            "nvenc_cq": FFMPEG_NVENC_CQ,
        },
        "whisper": {
            "backend": WHISPER_BACKEND,
            "device": WHISPER_DEVICE,
            "compute_type": WHISPER_COMPUTE_TYPE or None,
            "model": WHISPER_MODEL,
            "inference_mode": WHISPER_INFERENCE_MODE,
            "device_index": WHISPER_DEVICE_INDEX,
            "cpu_threads": WHISPER_CPU_THREADS,
            "num_workers": WHISPER_NUM_WORKERS,
            "batched_inference": WHISPER_BATCHED_INFERENCE,
            "batch_size": WHISPER_BATCH_SIZE,
            "gap_threshold_seconds": WHISPER_GAP_THRESHOLD_SECONDS,
            "beam_size": WHISPER_BEAM_SIZE,
            "best_of": WHISPER_BEST_OF,
            "condition_on_previous_text": WHISPER_CONDITION_ON_PREVIOUS_TEXT,
            "cuda": detect_cuda_runtime(),
            "runtime_preview": whisper_runtime,
            "timing": {
                "word_timestamps": WHISPER_WORD_TIMESTAMPS,
                "vad_enabled": WHISPER_VAD_ENABLED,
                "vad_padding_ms": WHISPER_VAD_PADDING_MS,
                "tail_padding_ms": SUBTITLE_TAIL_PADDING_MS,
                "max_duration_ms": SUBTITLE_MAX_DURATION_MS,
                "max_gap_ms": SUBTITLE_MAX_GAP_MS,
                "max_chars": SUBTITLE_MAX_CHARS,
                "max_cps": SUBTITLE_MAX_CPS,
                "min_duration_ms": SUBTITLE_MIN_DURATION_MS,
                "merge_short_chars": SUBTITLE_MERGE_SHORT_CHARS,
                "coherence_merge": SUBTITLE_COHERENCE_MERGE,
                "coherence_max_chars": SUBTITLE_COHERENCE_MAX_CHARS,
                "coherence_max_duration_ms": SUBTITLE_COHERENCE_MAX_DURATION_MS,
                "coherence_max_gap_ms": SUBTITLE_COHERENCE_MAX_GAP_MS,
                "orphan_max_chars": SUBTITLE_ORPHAN_MAX_CHARS,
                "repeat_token_limit": SUBTITLE_REPEAT_TOKEN_LIMIT,
                "drop_repeated_hallucinations": SUBTITLE_DROP_REPEATED_HALLUCINATIONS,
                "repeat_handling": SUBTITLE_REPEAT_HANDLING,
                "repeat_compress_text": SUBTITLE_REPEAT_COMPRESS_TEXT,
                "repeat_min_span_ms": SUBTITLE_REPEAT_MIN_SPAN_MS,
                "repeat_min_blocks": SUBTITLE_REPEAT_MIN_BLOCKS,
            },
        },
        "translation": {
            "provider": TRANSLATE_PROVIDER or None,
            "api_base": TRANSLATE_API_BASE or None,
            "model": TRANSLATE_MODEL or None,
            "prompt_concurrency": TRANSLATE_PROMPT_CONCURRENCY,
            "configured": bool(TRANSLATE_PROVIDER and TRANSLATE_API_BASE and TRANSLATE_MODEL and TRANSLATE_API_KEY),
        },
        "bilibili": {
            "configured": bilibili_configured(),
            "upload_concurrency": BILI_UPLOAD_CONCURRENCY,
            "line": BILI_UPLOAD_LINE,
            "fallback_lines": BILI_UPLOAD_FALLBACK_LINES,
            "proxy_configured": bool(BILI_PROXY),
        },
        "batch": {
            "batch_worker_concurrency": BATCH_WORKER_CONCURRENCY,
            "batch_worker_max_concurrency": BATCH_WORKER_MAX_CONCURRENCY,
        },
    }


@app.get("/media-ui")
def media_ui() -> Response:
    if not DESKTOP:
        raise HTTPException(404, "桌面界面由 Media Operator 应用提供")
    index_path = MEDIA_UI_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(503, "桌面界面尚未构建。请在 frontend 目录运行 npm run build。")
    return FileResponse(index_path)


@app.get("/ui/whisper-models")
def ui_whisper_models() -> dict[str, Any]:
    if DESKTOP:
        from app.desktop_models import MODELS
        models = list(MODELS)
    else:
        models = ["base", "small", "medium", "large-v3"]
    return {
        "default": WHISPER_MODEL,
        "default_inference_mode": WHISPER_INFERENCE_MODE,
        "inference_modes": ["auto", "gpu_only", "standard", "auto_repair", "batched"] if DESKTOP else ["standard", "auto_repair", "batched"],
        "models": [whisper_model_status(model) for model in models],
    }


@app.get("/ui/bilibili/status")
def ui_bilibili_status() -> dict[str, Any]:
    return {
        "configured": bilibili_configured(),
        "required": ["BILI_SESSDATA", "BILI_JCT", "BILI_BUVID3"],
        "optional": ["BILI_DEDEUSERID", "BILI_AC_TIME_VALUE", "BILI_PROXY"],
        "upload_concurrency": BILI_UPLOAD_CONCURRENCY,
        "line": BILI_UPLOAD_LINE,
        "fallback_lines": BILI_UPLOAD_FALLBACK_LINES,
        "proxy_configured": bool(BILI_PROXY),
    }


@app.get("/ui/bilibili/collections")
def ui_bilibili_collections() -> dict[str, Any]:
    if not bilibili_configured():
        raise HTTPException(status_code=400, detail="Bilibili credential is not configured")
    headers = {
        "Cookie": bilibili_cookie_header(),
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://member.bilibili.com/platform/upload-manager/article",
    }
    candidates = [
        (
            "series",
            "https://member.bilibili.com/x/web/archives/series/list",
            {"pn": "1", "ps": "50"},
        ),
        (
            "seasons",
            "https://member.bilibili.com/x2/creative/web/seasons",
            {"pn": "1", "ps": "50"},
        ),
    ]
    collections: list[dict[str, Any]] = []
    errors: list[str] = []
    debug_errors: list[str] = []
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), proxy=BILI_PROXY or None) as client:
        for kind, url, params in candidates:
            try:
                response = client.get(url, headers=headers, params=params)
                try:
                    payload = response.json()
                except Exception as parse_exc:
                    debug_errors.append(f"{kind}: {parse_exc}")
                    continue
                if response.status_code >= 400 or int(payload.get("code") or 0) != 0:
                    message = f"{kind}: {payload.get('message') or response.status_code}"
                    if kind == "series":
                        debug_errors.append(message)
                    else:
                        errors.append(message)
                    continue
                data = payload.get("data") or {}
                raw_items = data.get("items") or data.get("list") or data.get("series") or data.get("seasons") or []
                if isinstance(raw_items, dict):
                    raw_items = raw_items.get("items") or raw_items.get("list") or []
                if not isinstance(raw_items, list):
                    raw_items = []
                for raw in raw_items:
                    if not isinstance(raw, dict):
                        continue
                    item_data = raw
                    if isinstance(raw.get("season"), dict):
                        item_data = raw["season"]
                    elif isinstance(raw.get("series"), dict):
                        item_data = raw["series"]
                    collection_id = (
                        item_data.get("series_id")
                        or item_data.get("id")
                        or item_data.get("sid")
                        or item_data.get("season_id")
                    )
                    name = (
                        item_data.get("name")
                        or item_data.get("title")
                        or item_data.get("season_title")
                        or f"{kind} {collection_id}"
                    )
                    if collection_id:
                        collection_type = "season" if kind == "seasons" else kind
                        collections.append(
                            {
                                "id": str(collection_id),
                                "name": str(name),
                                "type": collection_type,
                                "writable": kind == "series",
                                "raw": raw,
                            }
                        )
            except Exception as exc:
                message = f"{kind}: {exc}"
                if kind == "series":
                    debug_errors.append(message)
                else:
                    errors.append(message)
    return {"collections": collections, "errors": errors, "debug_errors": debug_errors}


@app.get("/ui/bilibili/zones")
def ui_bilibili_zones() -> dict[str, Any]:
    try:
        from bilibili_api import video_zone
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"bilibili video_zone unavailable: {exc}") from exc
    tree = video_zone.get_zone_list_sub()
    flat = video_zone.get_zone_list()
    return {"zones": tree, "flat": flat}


@app.get("/ui/translation-contexts")
def list_translation_contexts() -> dict[str, Any]:
    return {"profiles": load_translation_context_profiles()}


@app.post("/ui/translation-contexts")
def create_translation_context(profile: TranslationContextProfileInput) -> dict[str, Any]:
    name = profile.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="profile name is required")
    with batch_lock:
        profiles = load_translation_context_profiles()
        now = now_iso()
        created = TranslationContextProfile(
            profile_id=f"context_{uuid.uuid4().hex[:12]}",
            name=name,
            note=normalize_saved_translation_text(profile.note),
            glossary=normalize_saved_translation_text(profile.glossary),
            created_at=now,
            updated_at=now,
        )
        profiles.append(created.model_dump())
        save_translation_context_profiles(profiles)
        return created.model_dump()


@app.put("/ui/translation-contexts/{profile_id}")
def update_translation_context(profile_id: str, profile: TranslationContextProfileInput) -> dict[str, Any]:
    name = profile.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="profile name is required")
    with batch_lock:
        profiles = load_translation_context_profiles()
        for index, existing in enumerate(profiles):
            if existing.get("profile_id") != profile_id:
                continue
            updated = TranslationContextProfile(
                profile_id=profile_id,
                name=name,
                note=normalize_saved_translation_text(profile.note),
                glossary=normalize_saved_translation_text(profile.glossary),
                created_at=str(existing.get("created_at") or now_iso()),
                updated_at=now_iso(),
            )
            profiles[index] = updated.model_dump()
            save_translation_context_profiles(profiles)
            return updated.model_dump()
    raise HTTPException(status_code=404, detail="translation context profile not found")


@app.delete("/ui/translation-contexts/{profile_id}")
def delete_translation_context(profile_id: str) -> dict[str, Any]:
    with batch_lock:
        profiles = load_translation_context_profiles()
        kept = [profile for profile in profiles if profile.get("profile_id") != profile_id]
        if len(kept) == len(profiles):
            raise HTTPException(status_code=404, detail="translation context profile not found")
        save_translation_context_profiles(kept)
    return {"deleted": True, "profile_id": profile_id}


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/media-ui" if DESKTOP else "/health")


@app.post("/ui/batches")
def create_ui_batch(request: BatchCreateRequest) -> dict[str, Any]:
    if not request.rights_confirmed:
        raise HTTPException(status_code=400, detail="rights_confirmed must be true")
    if not DESKTOP:
        raise HTTPException(404, "批处理界面由 Media Operator 应用提供")
    from app.desktop_jobs import submit_desktop_batch

    return submit_desktop_batch(request).model_dump()


@app.get("/ui/batches/{batch_id}")
def get_ui_batch(batch_id: str) -> dict[str, Any]:
    try:
        return load_batch(batch_id).model_dump()
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="batch not found") from error


@app.get("/ui/batches/{batch_id}/events")
def batch_events(batch_id: str) -> StreamingResponse:
    def stream():
        last_payload = ""
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline:
            try:
                batch = load_batch(batch_id)
                payload = json.dumps(batch.model_dump(), ensure_ascii=False)
            except FileNotFoundError:
                payload = json.dumps({"error": "batch not found"}, ensure_ascii=False)
                yield f"event: error\ndata: {payload}\n\n"
                return
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            if batch.status in {"succeeded", "failed"} and batch.queued == 0 and batch.running == 0:
                return
            time.sleep(1)
        yield ": keepalive\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


def preview_cache_key(*parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def load_youtube_preview_metadata(youtube_url: str) -> dict[str, Any]:
    ensure_dirs()
    cache_path = PREVIEW_CACHE_DIR / f"metadata_{preview_cache_key(youtube_url)}.json"
    if cache_path.exists() and time.time() - cache_path.stat().st_mtime < PREVIEW_METADATA_TTL_SECONDS:
        cached = read_json(cache_path)
        if isinstance(cached, dict):
            return cached

    cmd = [YT_DLP_BIN, *yt_dlp_network_flags(youtube_url), "--dump-single-json", "--no-download", "--no-playlist", youtube_url]
    if DESKTOP:
        cmd[1:1] = ["--socket-timeout", "12", "--retries", "1", "--extractor-retries", "1"]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8" if DESKTOP else None,
                                   errors="replace", check=False, timeout=45, creationflags=WINDOW_FLAGS)
    except subprocess.TimeoutExpired as exc:
        if DESKTOP:
            raise RuntimeError(online_media_error(youtube_url, "timeout")) from exc
        raise
    except Exception as exc:
        if DESKTOP:
            raise RuntimeError("无法启动素材读取工具，请检查应用安装后重试。") from exc
        raise RuntimeError(f"preview metadata failed: {exc}") from exc
    if completed.returncode != 0:
        if DESKTOP:
            cache_path.with_suffix(".log").write_text(completed.stderr, encoding="utf-8")
            raise RuntimeError(online_media_error(youtube_url, completed.stderr))
        raise RuntimeError(completed.stderr.strip() or "preview metadata failed")
    try:
        data = json.loads(completed.stdout)
    except Exception as exc:
        raise RuntimeError(f"preview metadata parse failed: {exc}") from exc
    if isinstance(data, dict):
        write_json(cache_path, data)
        return data
    raise RuntimeError("preview metadata is not an object")


def best_thumbnail_url(data: dict[str, Any]) -> str:
    thumbnails = data.get("thumbnails") if isinstance(data.get("thumbnails"), list) else []
    if thumbnails:
        best = sorted(
            (item for item in thumbnails if isinstance(item, dict) and item.get("url")),
            key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0),
            reverse=True,
        )
        if best:
            return str(best[0].get("url") or "")
    return str(data.get("thumbnail") or "")


def ranked_preview_formats(data: dict[str, Any]) -> list[dict[str, Any]]:
    formats = data.get("formats") if isinstance(data.get("formats"), list) else []
    candidates: list[dict[str, Any]] = []
    for item in formats:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        if str(item.get("vcodec") or "").lower() == "none":
            continue
        protocol = str(item.get("protocol") or "").lower()
        url = str(item.get("url") or "")
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        if protocol and protocol not in {"http", "https", "m3u8", "m3u8_native", "m3u8_frag_urls"}:
            continue
        candidates.append(item)

    if not candidates and data.get("url") and str(data.get("vcodec") or "").lower() != "none":
        candidates.append(data)
    if not candidates:
        return []

    def format_score(item: dict[str, Any]) -> tuple[int, int, int, int, int, int, float]:
        protocol = str(item.get("protocol") or "").lower()
        ext = str(item.get("ext") or "").lower()
        height = int(item.get("height") or 0)
        fps = float(item.get("fps") or 0)
        tbr = float(item.get("tbr") or 0)
        native_http = 1 if protocol in {"http", "https"} else 0
        mp4 = 1 if ext == "mp4" else 0
        progressive = 1 if str(item.get("acodec") or "").lower() != "none" else 0
        within_max = 1 if height and height <= PREVIEW_MAX_HEIGHT else 0
        near_target = -abs((height or PREVIEW_TARGET_HEIGHT) - PREVIEW_TARGET_HEIGHT)
        normal_fps = 1 if fps <= 30 else 0
        light_bitrate = -tbr
        return native_http, mp4, progressive, within_max, near_target, normal_fps, light_bitrate

    return sorted(candidates, key=format_score, reverse=True)


def select_preview_format(data: dict[str, Any]) -> dict[str, Any] | None:
    formats = ranked_preview_formats(data)
    return formats[0] if formats else None


def preview_time_seconds(data: dict[str, Any], percent: float) -> tuple[float, float, float]:
    try:
        duration = float(data.get("duration") or 0)
    except Exception:
        duration = 0.0
    if duration <= 0:
        window = float(PREVIEW_WINDOW_SECONDS)
        return min(5.0, window), 0.0, window
    window = min(duration, float(PREVIEW_WINDOW_SECONDS))
    seconds = window * max(0.0, min(100.0, percent)) / 100.0
    if window > 1:
        seconds = min(max(seconds, 0.5), max(0.5, window - 0.5))
    return seconds, duration, window


def ffmpeg_headers_args(headers: Any) -> list[str]:
    if not isinstance(headers, dict):
        return []
    lines = []
    for key, value in headers.items():
        if value is None:
            continue
        lines.append(f"{key}: {value}")
    if not lines:
        return []
    return ["-headers", "\r\n".join(lines) + "\r\n"]


def run_preview_ffmpeg(cmd: list[str], timeout_seconds: int = PREVIEW_FRAME_TIMEOUT_SECONDS) -> None:
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        creationflags=WINDOW_FLAGS,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or f"ffmpeg failed with exit code {completed.returncode}"
        raise RuntimeError(stderr)


def extract_preview_frame(
    preview_job_id: str,
    data: dict[str, Any],
    selected_format: dict[str, Any],
    seconds: float,
) -> Path:
    format_id = str(selected_format.get("format_id") or "unknown")
    raw_path = artifact_path(preview_job_id, f"raw_{preview_cache_key(format_id, round(seconds, 2))}.jpg")
    if raw_path.exists():
        return raw_path

    headers = selected_format.get("http_headers") or data.get("http_headers") or {}
    media_url = str(selected_format.get("url"))
    proxy = online_media_proxy(media_url) if DESKTOP else None
    proxy_args = ["-http_proxy", proxy] if proxy and proxy.lower().startswith("http://") else []
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-nostdin",
        "-loglevel",
        "error",
        "-rw_timeout",
        str(PREVIEW_FRAME_TIMEOUT_SECONDS * 1_000_000),
        *proxy_args,
        *ffmpeg_headers_args(headers),
        "-ss",
        f"{seconds:.3f}",
        "-i",
        media_url,
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(raw_path),
    ]
    run_preview_ffmpeg(cmd)
    if not raw_path.exists():
        raise RuntimeError("ffmpeg finished but no preview frame was produced")
    return raw_path


def extract_preview_frame_from_path(preview_job_id: str, source_path: Path, seconds: float) -> Path:
    raw_path = artifact_path(preview_job_id, f"raw_{preview_cache_key(source_path.name, round(seconds, 2))}.jpg")
    if raw_path.exists():
        return raw_path
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        f"{seconds:.3f}",
        "-i",
        str(source_path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(raw_path),
    ]
    run_preview_ffmpeg(cmd)
    if not raw_path.exists():
        raise RuntimeError("ffmpeg finished but no preview frame was produced")
    return raw_path


def download_thumbnail_for_preview(preview_job_id: str, thumbnail: str) -> Path:
    if not thumbnail:
        raise RuntimeError("no preview thumbnail found")
    thumbnail_path = artifact_path(preview_job_id, "thumbnail.jpg")
    if thumbnail_path.exists():
        return thumbnail_path
    with httpx.Client(timeout=30, follow_redirects=True, proxy=online_media_proxy(thumbnail), trust_env=not DESKTOP) as client:
        image_response = client.get(thumbnail)
        image_response.raise_for_status()
        thumbnail_path.write_bytes(image_response.content)
    return thumbnail_path


def render_preview_with_subtitle(
    preview_job_id: str,
    source_image_path: Path,
    request: PreviewFrameRequest,
    render_width: int,
    render_height: int,
) -> Path:
    style_payload = request.subtitle_style.model_dump() if request.subtitle_style else {}
    rendered_path = artifact_path(
        preview_job_id,
        f"preview_{preview_cache_key('v2', source_image_path.name, request.aspect_ratio, request.subtitle_output_mode, style_payload)}.jpg",
    )
    if rendered_path.exists():
        return rendered_path

    example = "I did not expect that answer."
    if request.subtitle_output_mode != "en_only":
        example += "\n我完全没想到会这样回答。"
    sample_srt = artifact_path(preview_job_id, "sample.srt")
    sample_srt.write_text(
        srt.compose(
            [
                srt.Subtitle(
                    index=1,
                    start=timedelta(seconds=0),
                    end=timedelta(seconds=5),
                    content=example,
                )
            ]
        ),
        encoding="utf-8",
    )
    style = request.subtitle_style or SubtitleStyle()
    if style.font_size_mode == "auto":
        style = style.model_copy(update={"font_size": subtitle_font_size_value("auto", render_height)})
    subtitle_render_path = write_subtitle_mode_srt(
        preview_job_id,
        sample_srt,
        output_mode=request.subtitle_output_mode,
        bilingual_order=style.bilingual_order,
    )
    ass_path = build_ass_from_srt(
        preview_job_id,
        subtitle_render_path,
        font_name=style.font_family or DEFAULT_FONT,
        font_size=scaled_style_value(style.font_size, render_height, minimum=10),
        margin_v=subtitle_margin_from_style(style, render_height),
        primary_color=style.primary_color,
        outline_color=style.outline_color,
        alignment=subtitle_alignment_from_position(style.position),
        font_weight=style.font_weight,
        outline_width=scaled_style_value(style.outline_width, render_height, minimum=0, maximum=48),
        shadow=scaled_style_value(style.shadow, render_height, minimum=0, maximum=48),
        margin_l=subtitle_horizontal_margin(style, render_width),
        margin_r=subtitle_horizontal_margin(style, render_width),
        background_enabled=style.background_enabled,
        background_color=style.background_color,
        background_opacity=style.background_opacity,
        play_res_x=render_width,
        play_res_y=render_height,
    )
    subtitle_filter = f"ass='{ffmpeg_escape_path(ass_path)}'"
    fonts_dir = subtitle_fonts_dir(style.font_family)
    if fonts_dir.exists():
        subtitle_filter += f":fontsdir='{ffmpeg_escape_path(fonts_dir)}'"
    filters = [fixed_canvas_filter(render_width, render_height), subtitle_filter]
    run_preview_ffmpeg(
        [
            FFMPEG_BIN,
            "-y",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(source_image_path),
            "-vf",
            ",".join(filters),
            "-frames:v",
            "1",
            str(rendered_path),
        ],
        timeout_seconds=30,
    )
    return rendered_path


def normalize_bilibili_cover_image(job_id: str, source_image_path: Path) -> Path:
    cover_path = artifact_path(job_id, "cover.jpg")
    filters = [
        "scale=1146:717:force_original_aspect_ratio=decrease",
        "pad=1146:717:(ow-iw)/2:(oh-ih)/2:color=black",
        "setsar=1",
    ]
    run_command(
        [
            FFMPEG_BIN,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source_image_path),
            "-vf",
            ",".join(filters),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(cover_path),
        ],
        log_dir=job_dir(job_id),
        log_name="ffmpeg-bilibili-cover-normalize",
    )
    return cover_path


def generate_bilibili_cover_from_source(request: BilibiliCoverPreviewRequest, job_id: str) -> dict[str, Any]:
    if request.source_kind == "local" or is_local_source_url(request.source_value):
        if request.cover_source_mode == "youtube_thumbnail":
            raise ValueError("local source does not have a YouTube thumbnail")
        source_path = normalize_local_source_path(request.source_value)
        duration = detect_video_duration_seconds(source_path)
        seconds, duration, preview_window = preview_time_seconds({"duration": duration}, request.preview_time_percent)
        source_image_path = extract_preview_frame_from_path(job_id, source_path, seconds)
        cover_path = normalize_bilibili_cover_image(job_id, source_image_path)
        return {
            "cover_asset_url": public_file_url(job_id, cover_path.name),
            "cover_image_url": public_file_url(job_id, cover_path.name),
            "preview_time_seconds": seconds,
            "duration_seconds": duration,
            "preview_window_seconds": preview_window,
            "preview_time_percent": request.preview_time_percent,
            "preview_source": "local_file",
            "title": source_path.stem,
            "render_width": 1146,
            "render_height": 717,
        }

    if DESKTOP and request.source_kind == "url":
        from app import desktop_sources

        info = desktop_sources.probe(request.source_value, "url")
        if not info.get("thumbnail"):
            raise ValueError("该来源没有公开封面，可上传封面或使用成片画面")
        image = desktop_sources.download_thumbnail(info["thumbnail"], artifact_path(job_id, "source-cover.img"))
        cover = normalize_bilibili_cover_image(job_id, image)
        return {"cover_asset_url": public_file_url(job_id, cover.name),
                "cover_image_url": public_file_url(job_id, cover.name), "preview_source": "source_thumbnail"}
    if video_url_kind(request.source_value) != request.source_kind:
        raise ValueError("请输入有效的 YouTube 或 B 站链接")
    data = load_youtube_preview_metadata(request.source_value)
    if request.cover_source_mode == "youtube_thumbnail":
        thumbnail = best_thumbnail_url(data)
        if not thumbnail:
            raise RuntimeError("no YouTube thumbnail found")
        source_image_path = download_thumbnail_for_preview(job_id, thumbnail)
        cover_path = normalize_bilibili_cover_image(job_id, source_image_path)
        duration = float(data.get("duration") or 0)
        return {
            "cover_asset_url": public_file_url(job_id, cover_path.name),
            "cover_image_url": public_file_url(job_id, cover_path.name),
            "thumbnail_url": thumbnail,
            "preview_time_seconds": 0,
            "duration_seconds": duration,
            "preview_window_seconds": min(duration, 300) if duration else 300,
            "preview_time_percent": request.preview_time_percent,
            "preview_source": "youtube_thumbnail",
            "title": data.get("title") or "",
            "render_width": 1146,
            "render_height": 717,
        }
    seconds, duration, preview_window = preview_time_seconds(data, request.preview_time_percent)
    preview_formats = ranked_preview_formats(data)
    frame_errors: list[str] = []
    source_image_path: Path | None = None
    format_id = ""
    for candidate_format in preview_formats[:4]:
        format_id = str(candidate_format.get("format_id") or "")
        try:
            source_image_path = extract_preview_frame(job_id, data, candidate_format, seconds)
            break
        except Exception as frame_exc:
            frame_errors.append(f"{format_id or 'unknown'}: {frame_exc}")
    if source_image_path is None:
        thumbnail = best_thumbnail_url(data)
        if not thumbnail:
            raise RuntimeError("; ".join(frame_errors) or "no cover frame produced")
        source_image_path = download_thumbnail_for_preview(job_id, thumbnail)
        format_id = "thumbnail_fallback"
    cover_path = normalize_bilibili_cover_image(job_id, source_image_path)
    return {
        "cover_asset_url": public_file_url(job_id, cover_path.name),
        "cover_image_url": public_file_url(job_id, cover_path.name),
        "preview_time_seconds": seconds,
        "duration_seconds": duration,
        "preview_window_seconds": preview_window,
        "preview_time_percent": request.preview_time_percent,
        "preview_source": format_id or "video",
        "title": data.get("title") or "",
        "render_width": 1146,
        "render_height": 717,
    }


@app.post("/ui/bilibili/cover-preview")
def bilibili_cover_preview(request: BilibiliCoverPreviewRequest) -> dict[str, Any]:
    job_id = f"cover_{preview_cache_key(request.source_kind, request.source_value, request.preview_time_percent, request.cover_source_mode)}"
    job_dir(job_id).mkdir(parents=True, exist_ok=True)
    try:
        return generate_bilibili_cover_from_source(request, job_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/ui/bilibili/cover-upload")
async def bilibili_cover_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "cover.jpg").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="cover file must be jpg, png, or webp")
    job_id = f"cover_upload_{uuid.uuid4().hex[:12]}"
    folder = job_dir(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    raw_path = artifact_path(job_id, f"uploaded{suffix}")
    with raw_path.open("wb") as handle:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    try:
        cover_path = normalize_bilibili_cover_image(job_id, raw_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"cover image is invalid: {exc}") from exc
    return {
        "cover_asset_url": public_file_url(job_id, cover_path.name),
        "cover_image_url": public_file_url(job_id, cover_path.name),
        "filename": file.filename or raw_path.name,
        "render_width": 1146,
        "render_height": 717,
    }


@app.post("/ui/preview-frame")
def preview_frame(request: PreviewFrameRequest) -> dict[str, Any]:
    if request.source_kind == "local" or is_local_source_url(request.source_value):
        try:
            source_path = normalize_local_source_path(request.source_value)
            source_width, source_height = detect_video_size(source_path)
            render_width, render_height = compute_render_canvas(source_width, source_height, request.aspect_ratio)
            duration = detect_video_duration_seconds(source_path)
            seconds, duration, preview_window = preview_time_seconds({"duration": duration}, request.preview_time_percent)
            preview_job_id = f"preview_{preview_cache_key(request.source_value)}"
            job_dir(preview_job_id).mkdir(parents=True, exist_ok=True)
            source_image_path = extract_preview_frame_from_path(preview_job_id, source_path, seconds)
            rendered_path = render_preview_with_subtitle(preview_job_id, source_image_path, request, render_width, render_height)
            preview_url = public_file_url(preview_job_id, rendered_path.name)
            return {
                "preview_image_url": preview_url,
                "thumbnail_url": "",
                "rendered_subtitle": True,
                "preview_error": "",
                "preview_source": "local_file",
                "preview_time_seconds": seconds,
                "duration_seconds": duration,
                "preview_window_seconds": preview_window,
                "preview_time_percent": request.preview_time_percent,
                "format_id": "local",
                "title": source_path.stem,
                "source_width": source_width,
                "source_height": source_height,
                "render_width": render_width,
                "render_height": render_height,
                "aspect_ratio": request.aspect_ratio,
                "resolution": request.resolution,
                "fps": request.fps,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    if DESKTOP and request.source_kind == "url":
        from app import desktop_sources

        try:
            info = desktop_sources.probe(request.source_value, "url")
            if not info.get("thumbnail"):
                raise ValueError("该来源没有公开封面，导入视频后可抓取画面")
            job_id = f"preview_{uuid.uuid4().hex[:12]}"
            job_dir(job_id).mkdir(parents=True, exist_ok=True)
            image = desktop_sources.download_thumbnail(info["thumbnail"], artifact_path(job_id, "source-cover.img"))
            width, height = compute_render_canvas(1280, 720, request.aspect_ratio)
            rendered = render_preview_with_subtitle(job_id, image, request, width, height)
            return {"preview_image_url": public_file_url(job_id, rendered.name), "preview_source": "thumbnail_fallback"}
        except (ValueError, OSError, RuntimeError) as error:
            raise HTTPException(400, str(error)) from error
    if video_url_kind(request.source_value) != request.source_kind:
        raise HTTPException(status_code=400, detail="请输入有效的 YouTube 或 B 站链接")
    try:
        data = load_youtube_preview_metadata(request.source_value)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    thumbnail = best_thumbnail_url(data)
    source_width = int(data.get("width") or 1080)
    source_height = int(data.get("height") or 1920)
    render_width, render_height = compute_render_canvas(source_width, source_height, request.aspect_ratio)
    seconds, duration, preview_window = preview_time_seconds(data, request.preview_time_percent)
    preview_formats = ranked_preview_formats(data)
    selected_format = preview_formats[0] if preview_formats else None
    preview_source = "video"
    format_id = str(selected_format.get("format_id") or "") if selected_format else ""
    preview_job_id = f"preview_{preview_cache_key(request.source_value)}"
    job_dir(preview_job_id).mkdir(parents=True, exist_ok=True)
    preview_url = ""
    rendered_subtitle = False
    preview_error = ""

    try:
        if not preview_formats:
            raise RuntimeError("no usable video stream found for preview")
        frame_errors: list[str] = []
        source_image_path: Path | None = None
        for candidate_format in preview_formats[:4]:
            selected_format = candidate_format
            format_id = str(selected_format.get("format_id") or "")
            try:
                source_image_path = extract_preview_frame(preview_job_id, data, selected_format, seconds)
                break
            except Exception as frame_exc:
                frame_errors.append(f"{format_id or 'unknown'}: {frame_exc}")
        if source_image_path is None:
            raise RuntimeError("; ".join(frame_errors) or "no preview frame produced")
        rendered_path = render_preview_with_subtitle(preview_job_id, source_image_path, request, render_width, render_height)
        preview_url = public_file_url(preview_job_id, rendered_path.name)
        rendered_subtitle = True
    except Exception as exc:
        preview_source = "thumbnail_fallback"
        preview_error = str(exc)
        if DESKTOP:
            (job_dir(preview_job_id) / "preview-frame.log").write_text(preview_error, encoding="utf-8")
            preview_error = "暂时无法读取视频帧，已改用封面图预览。"
        try:
            thumbnail_path = download_thumbnail_for_preview(preview_job_id, thumbnail)
            rendered_path = render_preview_with_subtitle(preview_job_id, thumbnail_path, request, render_width, render_height)
            preview_url = public_file_url(preview_job_id, rendered_path.name)
            rendered_subtitle = True
        except Exception as fallback_exc:
            if DESKTOP:
                raise HTTPException(502, "无法取得视频帧或封面图，请检查网络后重试。") from fallback_exc
            if not thumbnail:
                raise HTTPException(status_code=404, detail=f"real preview failed and no thumbnail fallback found: {preview_error}") from fallback_exc
            preview_url = thumbnail
            rendered_subtitle = False
            preview_error = f"{preview_error}; thumbnail render failed: {fallback_exc}"

    return {
        "preview_image_url": preview_url,
        "thumbnail_url": thumbnail,
        "rendered_subtitle": rendered_subtitle,
        "preview_error": preview_error,
        "preview_source": preview_source,
        "preview_time_seconds": seconds,
        "duration_seconds": duration,
        "preview_window_seconds": preview_window,
        "preview_time_percent": request.preview_time_percent,
        "format_id": format_id,
        "title": data.get("title") or "",
        "source_width": source_width,
        "source_height": source_height,
        "render_width": render_width,
        "render_height": render_height,
        "aspect_ratio": request.aspect_ratio,
        "resolution": request.resolution,
        "fps": request.fps,
    }


@app.post("/jobs/youtube-bilingual-video")
def create_pipeline_job(request: VideoJobRequest) -> dict[str, Any]:
    state = submit_job(request)
    return {
        "job_id": state.job_id,
        "status": state.status,
        "stage": state.stage,
        "query_url": public_job_url(state.job_id),
        "message": state.message,
    }


@app.post("/operator/run")
def run_operator(request: OperatorRunRequest) -> dict[str, Any]:
    if request.operator != "youtube_bilingual_video":
        raise HTTPException(status_code=400, detail="unsupported operator")
    state = submit_job(request.input)
    return {
        "operator": request.operator,
        "job_id": state.job_id,
        "status": state.status,
        "stage": state.stage,
        "query_url": public_job_url(state.job_id),
        "message": state.message,
    }


@app.get("/operator/jobs/{job_id}")
def get_operator_job(job_id: str) -> dict[str, Any]:
    return get_job(job_id)


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    try:
        state = load_state(job_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="job not found") from error
    return state.model_dump()


@app.post("/jobs/query")
def query_job(request: JobQueryRequest) -> dict[str, Any]:
    return get_job(request.job_id)


@app.get("/files/{job_id}/{filename}")
def get_file(job_id: str, filename: str) -> FileResponse:
    path = safe_job_artifact(job_id, filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path)


@app.post("/stage/download", response_class=PlainTextResponse)
def stage_download(request: StageDownloadRequest) -> str:
    if not request.rights_confirmed:
        raise HTTPException(status_code=400, detail="rights_confirmed must be true")
    source_value = request.source_value or request.youtube_url
    stage_job_id = f"stage_{uuid.uuid4().hex[:12]}"
    try:
        if request.source_kind == "local" or is_local_source_url(source_value):
            source_path = import_local_source(stage_job_id, source_value)
        else:
            if not is_youtube_url(source_value):
                raise ValueError("source_value must be a YouTube link or local source")
            source_path = download_youtube(
                stage_job_id,
                source_value,
                build_yt_dlp_format_selector(request.resolution, request.fps),
            )
    except Exception as exc:
        if ALLOW_PLACEHOLDER_ARTIFACTS:
            source_path = ensure_placeholder_video(stage_job_id, source_value)
        else:
            raise HTTPException(status_code=500, detail=f"download failed: {exc}") from exc
    return public_file_url(stage_job_id, source_path.name)


@app.post("/stage-jobs/download", response_class=PlainTextResponse)
def submit_stage_download(request: StageDownloadRequest) -> str:
    return submit_stage_job("download", request.model_dump())


@app.get("/stage-jobs/{job_id}")
def get_stage_job(job_id: str, hold_seconds: int = 0) -> dict[str, Any]:
    try:
        state = wait_for_state_change(job_id, hold_seconds=hold_seconds)
    except FileNotFoundError as error:
        return stage_result_payload(
            job_id=job_id,
            stage="unknown",
            status="failed",
            progress=100,
            message=f"stage job not found: {job_id}",
            error={
                "stage": "unknown",
                "message": f"stage job not found: {job_id}",
                "type": error.__class__.__name__,
            },
        )
    payload = state.model_dump()
    payload["result_url"] = None
    if state.result:
        payload["result_url"] = state.result.get("result_url")
    payload["log_tail"] = read_stage_log_tail(job_id)
    return payload


@app.get("/stage-jobs/{job_id}/log", response_class=PlainTextResponse)
def get_stage_job_log(job_id: str) -> str:
    path = stage_progress_log_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="stage log not found")
    return path.read_text(encoding="utf-8", errors="replace")


@app.post("/stage/transcribe", response_class=PlainTextResponse)
def stage_transcribe(request: StageTranscribeRequest) -> str:
    try:
        stage_job_id, source_path = resolve_local_artifact_from_url(request.source_video_url)
        srt_path = transcribe_video(
            stage_job_id,
            source_path,
            language=request.language,
            model_name=request.whisper_model,
        )
    except Exception as exc:
        if ALLOW_PLACEHOLDER_ARTIFACTS:
            stage_job_id, source_path = resolve_local_artifact_from_url(request.source_video_url)
            srt_path = placeholder_srt(stage_job_id, request.title or "video", source_path.name)
        else:
            raise HTTPException(status_code=500, detail=f"transcribe failed: {exc}") from exc
    return public_file_url(stage_job_id, srt_path.name)


@app.post("/stage-jobs/transcribe", response_class=PlainTextResponse)
def submit_stage_transcribe(request: StageTranscribeRequest) -> str:
    return submit_stage_job("transcribe", request.model_dump())


@app.post("/stage/translate", response_class=PlainTextResponse)
def stage_translate(request: StageTranslateRequest) -> str:
    try:
        if request.subtitle_output_mode == "en_only":
            return request.english_srt_url
        stage_job_id, english_path = resolve_local_artifact_from_url(request.english_srt_url)
        bilingual_path = translate_srt(
            stage_job_id,
            english_path,
            target_lang=request.target_lang,
            model_name=request.translate_model,
            context_note=request.translation_context_note,
            glossary=request.translation_glossary,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"translate failed: {exc}") from exc
    return public_file_url(stage_job_id, bilingual_path.name)


@app.post("/stage-jobs/translate", response_class=PlainTextResponse)
def submit_stage_translate(request: StageTranslateRequest) -> str:
    return submit_stage_job("translate", request.model_dump())


@app.post("/stage/burn", response_class=PlainTextResponse)
def stage_burn(request: StageBurnRequest) -> str:
    try:
        video_job_id, source_path = resolve_local_artifact_from_url(request.source_video_url)
        subtitle_url = request.english_srt_url if request.subtitle_output_mode == "en_only" and request.english_srt_url else request.bilingual_srt_url
        subtitle_job_id, subtitle_path = resolve_local_artifact_from_url(subtitle_url)
        if video_job_id != subtitle_job_id:
            raise ValueError("video and subtitle must belong to same stage job")
        final_path = burn_subtitle(
            video_job_id,
            source_path,
            subtitle_path,
            aspect_ratio=request.aspect_ratio,
            subtitle_font_size=request.subtitle_font_size,
            subtitle_color=request.subtitle_color,
            subtitle_outline_color=request.subtitle_outline_color,
            subtitle_position=request.subtitle_position,
            subtitle_margin=request.subtitle_margin,
            subtitle_output_mode=request.subtitle_output_mode,
            subtitle_style=request.subtitle_style,
            output_name=request.output_name,
        )
    except Exception as exc:
        if ALLOW_PLACEHOLDER_ARTIFACTS:
            video_job_id, source_path = resolve_local_artifact_from_url(request.source_video_url)
            final_path = source_path
        else:
            raise HTTPException(status_code=500, detail=f"burn failed: {exc}") from exc
    return public_file_url(video_job_id, final_path.name)


@app.post("/stage-jobs/burn", response_class=PlainTextResponse)
def submit_stage_burn(request: StageBurnRequest) -> str:
    return submit_stage_job("burn", request.model_dump())


@app.post("/stage-jobs/bilibili-upload", response_class=PlainTextResponse)
def submit_stage_bilibili_upload(request: StageBilibiliUploadRequest) -> str:
    return submit_stage_job("bilibili_upload", request.model_dump())
