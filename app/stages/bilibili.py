from __future__ import annotations

# ruff: noqa: F821
"""Bilibili credential, cover, and upload.

Executed inside app.main so callers and tests keep patching that module.
"""

def build_bilibili_credential() -> Any:
    require_bilibili_config()
    try:
        from bilibili_api import Credential
    except Exception as exc:
        raise RuntimeError("bilibili-api-python is not installed. Run pip install -r requirements.txt") from exc
    kwargs = {
        "sessdata": BILI_SESSDATA,
        "bili_jct": BILI_JCT,
        "buvid3": BILI_BUVID3,
    }
    if BILI_DEDEUSERID:
        kwargs["dedeuserid"] = BILI_DEDEUSERID
    if BILI_AC_TIME_VALUE:
        kwargs["ac_time_value"] = BILI_AC_TIME_VALUE
    if BILI_PROXY:
        kwargs["proxy"] = BILI_PROXY
    return Credential(**kwargs)


def read_source_download_metadata(source_path: Path) -> dict[str, Any]:
    try:
        with source_path.with_name("source-metadata.jsonl").open(encoding="utf-8") as stream:
            data = json.loads(stream.readline(1048576))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def bilibili_source_metadata(source_value: str, source_video_url: str) -> dict[str, Any]:
    cached = {}
    if source_video_url:
        try:
            _, path = resolve_local_artifact_from_url(source_video_url)
            data = read_source_download_metadata(path)
            cached = data
            if data.get("thumbnail") and "description" in data:
                return data
        except (OSError, ValueError):
            pass
    if not video_url_kind(source_value):
        return cached
    try:
        data = load_youtube_preview_metadata(source_value)
        return {"title": data.get("title") or cached.get("title"), "description": data.get("description"),
                "thumbnail": data.get("thumbnail") or best_thumbnail_url(data) or cached.get("thumbnail")}
    except (OSError, RuntimeError, ValueError):
        return cached


def create_bilibili_cover(
    job_id: str, video_path: Path, settings: BilibiliUploadSettings, source_value: str = "",
    *, source_video_url: str = "", source_thumbnail: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    cover_config = selected_bilibili_cover_config(settings, source_value)
    cover_selection = str(cover_config.pop("_cover_selection", "") or "")
    if not cover_selection:
        cover_selection = "item_override" if settings.cover_scope == "per_item" else "batch_default"
    mode = str(cover_config.get("cover_mode") or settings.cover_mode or "auto_middle_frame")
    cover_source = str(cover_config.get("cover_source") or settings.cover_source or "frame")
    asset_url = str(cover_config.get("cover_asset_url") or settings.cover_asset_url or "").strip()
    if asset_url:
        if asset_url.startswith("/files/") or is_local_source_url(asset_url):
            _, cover_path = resolve_local_artifact_from_url(asset_url)
            return cover_path, {
                "cover_selection": cover_selection,
                "cover_mode": mode,
                "cover_source": cover_source,
                "cover_asset_url": asset_url,
            }
        parsed = urlparse(asset_url)
        if parsed.path.startswith("/files/"):
            _, cover_path = resolve_local_artifact_from_url(asset_url)
            return cover_path, {
                "cover_selection": cover_selection,
                "cover_mode": mode,
                "cover_source": cover_source,
                "cover_asset_url": asset_url,
            }
    if settings.cover_mode == "custom_path" and settings.cover_path:
        cover_path = Path(settings.cover_path)
        if not cover_path.is_absolute() or not cover_path.exists() or not cover_path.is_file():
            raise ValueError(f"custom cover not found: {settings.cover_path}")
        return cover_path, {
            "cover_selection": "custom_path",
            "cover_mode": settings.cover_mode,
            "cover_source": settings.cover_source,
            "cover_asset_url": "",
        }

    if mode == "source_cover":
        if source_thumbnail is None:
            source_thumbnail = str(bilibili_source_metadata(source_value, source_video_url).get("thumbnail") or "")
        if (source_thumbnail or "").startswith("/files/") or is_http_url(source_thumbnail):
            try:
                if source_thumbnail.startswith("/files/"):
                    _, image = resolve_local_artifact_from_url(source_thumbnail)
                else:
                    image = download_thumbnail_for_preview(job_id, source_thumbnail)
                cover_path = normalize_bilibili_cover_image(job_id, image)
                return cover_path, {
                    "cover_selection": cover_selection, "cover_mode": mode, "cover_source": "source_thumbnail",
                    "cover_asset_url": public_file_url(job_id, cover_path.name),
                }
            except (OSError, ValueError, RuntimeError, httpx.HTTPError):
                pass
        original = None
        try:
            if source_video_url:
                _, original = resolve_local_artifact_from_url(source_video_url)
            elif not is_http_url(source_value):
                original = normalize_local_source_path(source_value)
        except (OSError, ValueError):
            pass
        if original and original.is_file() and not is_http_url(source_value):
            try:
                image = artifact_path(job_id, "embedded_cover.jpg")
                run_command([
                    FFMPEG_BIN, "-y", "-i", str(original), "-map", "0:v:disp:attached_pic",
                    "-frames:v", "1", str(image),
                ], log_dir=job_dir(job_id), log_name="ffmpeg-bilibili-cover-embedded")
                cover_path = normalize_bilibili_cover_image(job_id, image)
                return cover_path, {
                    "cover_selection": cover_selection, "cover_mode": mode, "cover_source": "embedded_picture",
                    "cover_asset_url": public_file_url(job_id, cover_path.name),
                }
            except (OSError, RuntimeError):
                pass
        if original and original.is_file():
            video_path = original

    duration = detect_video_duration_seconds(video_path)
    percent = float(cover_config.get("cover_time_percent") or settings.cover_time_percent or 50)
    if mode == "auto_first_frame":
        seconds = 0.0
    elif mode == "selected_frame":
        seconds, _, _ = preview_time_seconds({"duration": duration}, percent)
    else:
        seconds = min(max(duration / 2.0, 0.0), 300.0)
    cover_path = artifact_path(job_id, "bilibili_cover.jpg")
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-ss",
        f"{seconds:.3f}",
        "-i",
        str(video_path),
        *(["-map", "0:V:0"] if mode == "source_cover" else []),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(cover_path),
    ]
    run_command(cmd, log_dir=job_dir(job_id), log_name="ffmpeg-bilibili-cover")
    if not cover_path.exists():
        raise RuntimeError("cover extraction failed")
    return cover_path, {
        "cover_selection": cover_selection if cover_selection in {"item_override", "legacy_per_item"} else "generated_frame",
        "cover_mode": mode,
        "cover_source": "frame" if mode == "source_cover" else cover_source,
        "cover_asset_url": public_file_url(job_id, cover_path.name),
        "cover_time_percent": percent,
    }


def selected_bilibili_cover_config(settings: BilibiliUploadSettings, source_value: str) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if source_value:
        config = dict(settings.per_item_covers.get(source_value) or {})
        if config:
            config["_cover_selection"] = "legacy_per_item"
    return config


def add_bilibili_archive_to_series(aid: Any, series_id: str) -> dict[str, Any]:
    if not series_id or not aid:
        return {"skipped": True, "message": "series_id or aid is empty"}
    require_bilibili_config()
    url = "https://member.bilibili.com/x/web/archives/series/addArchives"
    headers = {
        "Cookie": bilibili_cookie_header(),
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://member.bilibili.com/platform/upload-manager/article",
    }
    data = {
        "series_id": str(series_id),
        "aids": str(aid),
        "csrf": BILI_JCT,
    }
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0), proxy=BILI_PROXY or None) as client:
        response = client.post(url, headers=headers, data=data)
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text[:1000]}
    if response.status_code >= 400:
        raise RuntimeError(f"series add failed with HTTP {response.status_code}: {response.text[:500]}")
    if isinstance(payload, dict) and int(payload.get("code") or 0) != 0:
        raise RuntimeError(f"series add failed: {payload.get('message') or payload}")
    return {"skipped": False, "series_id": series_id, "response": payload}


def add_bilibili_archive_to_collection(aid: Any, settings: BilibiliUploadSettings) -> dict[str, Any]:
    if settings.collection_type == "none" or not settings.collection_id:
        return {"skipped": True, "message": "collection is not selected"}
    if settings.collection_type == "series":
        return add_bilibili_archive_to_series(aid, settings.collection_id)
    return {
        "skipped": True,
        "collection_type": settings.collection_type,
        "collection_id": settings.collection_id,
        "message": "season collection was requested; post-upload add API is not available in this implementation",
    }


def upload_video_to_bilibili(
    job_id: str,
    video_path: Path,
    request: StageBilibiliUploadRequest,
    progress_callback: Callable[[int, str, str | None], None] | None = None,
) -> dict[str, Any]:
    require_bilibili_config()
    try:
        from bilibili_api import sync, video_uploader
    except Exception as exc:
        raise RuntimeError("bilibili-api-python is not installed. Run pip install -r requirements.txt") from exc

    settings = request.upload_settings
    credential = build_bilibili_credential()
    if progress_callback:
        progress_callback(8, "extracting upload cover", None)
    cover_path, cover_metadata = create_bilibili_cover(
        job_id, video_path, settings, request.original_source,
        source_video_url=request.source_video_url, source_thumbnail=request.source_thumbnail,
    )
    if progress_callback:
        progress_callback(
            10,
            f"using {cover_metadata.get('cover_selection', 'unknown')} cover",
            json.dumps(cover_metadata, ensure_ascii=False),
        )

    source = settings.source if settings.source_mode == "custom" else (request.original_source if is_http_url(request.original_source) else "")
    if settings.copyright == 2 and not source:
        raise ValueError("Bilibili转载投稿需要有效来源；本地视频请在前端填写自定义来源")
    title = render_bilibili_title(
        settings.title_template,
        output_name=request.output_name,
        index=1,
        original_title=request.original_title,
        source=request.original_source,
    )
    description = settings.desc or ""
    tags = settings.tags or ["音乐综合", "音乐"]
    events: list[Any] = []

    async def do_upload(line_value: str, include_collection_meta: bool = True) -> dict[str, Any]:
        meta_kwargs = {
            "tid": settings.tid or 130,
            "title": title,
            "tags": tags,
            "desc": description,
            "cover": str(cover_path),
            "no_reprint": settings.no_reprint,
            "original": settings.copyright == 1,
        }
        if settings.dynamic:
            meta_kwargs["dynamic"] = settings.dynamic
        if source:
            meta_kwargs["source"] = source
        vu_meta = video_uploader.VideoMeta(**meta_kwargs)
        meta_for_upload: Any = vu_meta
        if include_collection_meta and settings.collection_type == "season" and settings.collection_id:
            meta_for_upload = vu_meta.__dict__()
            meta_for_upload["season_id"] = int(settings.collection_id)
            meta_for_upload["collection_id"] = int(settings.collection_id)
            meta_for_upload["collection_type"] = "season"
        page = video_uploader.VideoUploaderPage(
            path=str(video_path),
            title=title,
            description=description,
        )
        line = None if line_value == "auto" else getattr(video_uploader.Lines, line_value, None)
        if line is None:
            uploader = video_uploader.VideoUploader([page], meta_for_upload, credential, cover=str(cover_path) if isinstance(meta_for_upload, dict) else "")
        else:
            uploader = video_uploader.VideoUploader(
                [page],
                meta_for_upload,
                credential,
                cover=str(cover_path) if isinstance(meta_for_upload, dict) else "",
                line=line,
            )

        @uploader.on("__ALL__")
        async def ev(data: Any) -> None:
            safe_data = safe_json_payload(data)
            event_record = {"line": line_value, "event": safe_data}
            events.append(event_record)
            raw = json.dumps(event_record, ensure_ascii=False, default=str)[:1600]
            progress = 20
            message = "uploading video"
            if isinstance(safe_data, dict):
                for key in ("percent", "progress", "percent_float"):
                    if key in safe_data:
                        try:
                            progress = min(95, max(20, int(20 + float(safe_data[key]) * 0.75)))
                        except Exception:
                            pass
                message = bilibili_event_message(safe_data, message)
            if progress_callback:
                progress_callback(progress, message, raw)

        response = await uploader.start()
        return {
            "upload_response": response,
            "upload_events": events[-20:],
            "selected_upload_line": line_value,
        }

    collection_submit_warning = ""
    upload_result: dict[str, Any] | None = None
    upload_errors: list[dict[str, Any]] = []
    lines = bilibili_upload_line_candidates(settings.line)
    if not request.allow_automatic_retry:
        lines = lines[:1]
    for line_value in lines:
        if progress_callback:
            progress_callback(15, f"starting bilibili uploader via {line_value}", None)
        try:
            try:
                candidate_result = sync(do_upload(line_value, include_collection_meta=True))
            except Exception as exc:
                if not request.allow_automatic_retry or settings.collection_type != "season":
                    raise
                collection_submit_warning = f"season metadata submit failed, retried without season binding: {exception_diagnostics(exc).get('message')}"
                if progress_callback:
                    progress_callback(16, "season binding failed, retrying plain upload", collection_submit_warning[:500])
                candidate_result = sync(do_upload(line_value, include_collection_meta=False))
            candidate_ids = extract_bilibili_submission_ids(candidate_result)
            if not candidate_ids.get("bvid") and not candidate_ids.get("aid"):
                upload_result = candidate_result
                break
            upload_result = candidate_result
            break
        except Exception as exc:
            diagnostics = exception_diagnostics(exc)
            diagnostics["line"] = line_value
            upload_errors.append(diagnostics)
            if progress_callback:
                progress_callback(
                    18,
                    f"upload line {line_value} failed: {diagnostics.get('message')}",
                    json.dumps(diagnostics, ensure_ascii=False),
                )
    if upload_result is None:
        last = upload_errors[-1] if upload_errors else {"message": "unknown upload error"}
        raise RuntimeError(
            "Bilibili upload failed after trying lines "
            f"{', '.join(lines)}: {last.get('message')}; "
            f"details={json.dumps(upload_errors, ensure_ascii=False)[:1600]}"
        )
    ids = extract_bilibili_submission_ids(upload_result)
    bvid = ids.get("bvid")
    aid = ids.get("aid")
    if not bvid and not aid:
        raise RuntimeError("Bilibili upload returned no bvid/aid; check upload_events and Bilibili creator center before retrying")
    collection_status: dict[str, Any] = {"skipped": True}
    if settings.collection_type != "none" and settings.collection_id:
        if progress_callback:
            progress_callback(96, f"adding archive to {settings.collection_type} {settings.collection_id}", None)
        try:
            collection_status = add_bilibili_archive_to_collection(aid, settings)
        except Exception:
            collection_status = {"skipped": False, "message": "投稿已成功，但加入合集或系列失败，可在 B 站创作中心调整"}
    if collection_submit_warning:
        collection_status = {
            **collection_status,
            "season_submit_warning": collection_submit_warning,
        }
    if progress_callback:
        progress_callback(100, "bilibili upload completed", None)
    return {
        "title": title,
        "aid": aid,
        "bvid": bvid,
        "bilibili_url": f"https://www.bilibili.com/video/{bvid}" if bvid else "",
        "cover_path": str(cover_path),
        **cover_metadata,
        "collection_add_status": collection_status,
        "upload_line_errors": upload_errors,
        **upload_result,
    }


def run_stage_bilibili_upload(job_id: str) -> None:
    try:
        state = load_state(job_id)
        request = StageBilibiliUploadRequest.model_validate(state.request)
        if not request.upload_settings.enabled:
            result = {"result_url": request.final_video_url, "bilibili_upload_skipped": True}
            report_stage_progress(job_id, "bilibili_upload", 100, "bilibili upload skipped", status="succeeded", result=result, force=True)
            return
        if DESKTOP:
            from app import desktop_bilibili

            report_stage_progress(job_id, "bilibili_upload", 2, "准备来源封面和投稿信息", status="running", force=True)
            if request.upload_settings.cover_mode == "source_cover" or (
                request.upload_settings.auto_metadata and (
                    is_http_url(request.original_title) or request.original_description is None)
                and request.bilibili_metadata is None
            ):
                source = bilibili_source_metadata(request.original_source, request.source_video_url)
                request.source_thumbnail = str(source.get("thumbnail") or "")
                request.original_title = str(source.get("title") or request.original_title)
                if "description" in source:
                    request.original_description = source.get("description")
            request.upload_settings, request.bilibili_metadata = desktop_bilibili.prepare_metadata(request)
            state = load_state(job_id)
            state.request.update({
                "original_title": request.original_title, "upload_settings": request.upload_settings.model_dump(),
                "original_description": request.original_description,
                "bilibili_metadata": request.bilibili_metadata,
            })
            state.result = {"bilibili_metadata": request.bilibili_metadata}
            save_state(state)
            if request.operator_batch_id and request.operator_item_id:
                batch = load_batch(request.operator_batch_id)
                item = next(item for item in batch.items if item.item_id == request.operator_item_id)
                update_batch_item(batch.batch_id, item.item_id, result={**(item.result or {}), **state.result})
        report_stage_progress(job_id, "bilibili_upload", 5, "waiting for upload slot", status="running", force=True)
        _, video_path = resolve_local_artifact_from_url(request.final_video_url)
        with BILI_UPLOAD_SEMAPHORE:
            result = upload_video_to_bilibili(
                job_id,
                video_path,
                request,
                progress_callback=lambda progress, message, raw=None: report_stage_progress(
                    job_id, "bilibili_upload", progress, message, status="running", raw=raw
                ),
            )
        result["result_url"] = request.final_video_url
        if request.bilibili_metadata is not None:
            result["bilibili_metadata"] = request.bilibili_metadata
        report_stage_progress(job_id, "bilibili_upload", 100, "bilibili upload completed", status="succeeded", result=result, force=True)
    except Exception as error:
        fail_job(job_id, "bilibili_upload", error)
