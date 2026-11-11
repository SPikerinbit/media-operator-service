from __future__ import annotations

# ruff: noqa: F821
"""Stage runners that chain download, transcription, translation, burn, and upload.

Executed inside app.main so callers and tests keep patching that module.
"""

def artifact_urls(job_id: str, paths: dict[str, Path]) -> dict[str, str]:
    return {key: public_file_url(job_id, path.name) for key, path in paths.items()}


def finalize_success(job_id: str, request: VideoJobRequest, source_path: Path, english_srt: Path, bilingual_srt: Path, final_video: Path | None) -> JobState:
    result: dict[str, Any] = {
        "job_id": job_id,
        "status": "succeeded",
        "stage": "done",
        "query_url": public_job_url(job_id),
        "source_video_url": public_file_url(job_id, source_path.name),
        "english_srt_url": public_file_url(job_id, english_srt.name),
        "bilingual_srt_url": public_file_url(job_id, bilingual_srt.name),
        "final_video_url": public_file_url(job_id, final_video.name) if final_video else None,
        "title": request.title or source_path.stem,
        "output_name": build_output_name(
            request.output_name_mode,
            request.output_name_prefix,
            request.output_index,
            request.title or source_path.stem,
        ),
        "target_lang": request.target_lang,
        "whisper_model": request.whisper_model,
        "translate_model": request.translate_model,
        "aspect_ratio": request.aspect_ratio,
        "resolution": request.resolution,
        "fps": request.fps,
        "subtitle_output_mode": request.subtitle_output_mode,
    }
    if request.need_burn_subtitle and final_video is not None:
        result["final_video_path"] = str(final_video)
    state = update_state(
        job_id,
        status="succeeded",
        stage="done",
        progress=100,
        message="completed",
        result=result,
    )
    return state


def fail_job(job_id: str, stage: str, error: Exception) -> None:
    diagnostics = exception_diagnostics(error)
    error_payload = {"stage": stage, **diagnostics}
    message = str(diagnostics.get("message") or "stage failed")
    report_stage_progress(
        job_id,
        status="failed",
        stage=stage,
        progress=100,
        message=message,
        error=error_payload,
        raw=json.dumps(error_payload, ensure_ascii=False),
        force=True,
    )


def stage_result_payload(
    *,
    job_id: str,
    stage: str,
    status: Literal["queued", "running", "succeeded", "failed"],
    progress: int,
    message: str,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage_job_id": job_id,
        "stage": stage,
        "status": status,
        "progress": progress,
        "message": message,
        "result_url": None,
        "result": result or {},
        "error": error,
        "log_tail": read_stage_log_tail(job_id),
    }
    if result:
        payload.update(result)
        payload["result_url"] = result.get("result_url")
    return payload


def run_stage_download(job_id: str) -> None:
    try:
        state = load_state(job_id)
        request = StageDownloadRequest.model_validate(state.request)
        if not request.rights_confirmed:
            raise PermissionError("rights_confirmed must be true")
        source_value = request.source_value or request.youtube_url
        if DESKTOP and request.managed:
            from app import desktop_jobs, desktop_sources

            info, cookies = desktop_jobs.download_context(request)
            def progress(percent, message):
                report_stage_progress(job_id, "download", percent, message, status="running")

            progress(1, "正在导入素材")
            path, info, actual = desktop_sources.download(job_id, request, info, cookies, progress)
            metadata = {key: info.get(key) for key in ("title", "description")}
            if request.retain_cover and info.get("thumbnail"):
                try:
                    cover = desktop_sources.download_thumbnail(info["thumbnail"], path.with_name("source-cover.img"))
                    metadata["thumbnail"] = public_file_url(job_id, cover.name)
                except desktop_sources.SourceError:
                    pass
            path.with_name("source-metadata.jsonl").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            url = public_file_url(job_id, path.name)
            downloaded = {
                "source_video_url": url, "source_media_url": url, "result_url": url,
                "title": metadata.get("title") or ("" if actual["media_type"] == "note" else path.stem),
                "original_description": metadata["description"],
                "asset_type": actual["media_type"], "duration": actual["duration"], "has_audio": actual["has_audio"],
            }
            if actual["media_type"] == "note":
                downloaded.update(media_type="note", body=info.get("body") or "", author=info.get("author") or "",
                                  images=[public_file_url(job_id, name) for name in info.get("image_names") or []])
            report_stage_progress(job_id, "download", 100, "素材已导入", status="succeeded", force=True, result=downloaded)
            return
        completion_message = "download completed"

        if request.source_kind == "local" or is_local_source_url(source_value):
            report_stage_progress(job_id, "download", 5, "importing local source", status="running", force=True)
            try:
                source_path = import_local_source(job_id, source_value)
                completion_message = "local source imported"
            except Exception as exc:
                if ALLOW_PLACEHOLDER_ARTIFACTS:
                    source_path = ensure_placeholder_video(job_id, source_value)
                    report_stage_progress(job_id, "download", 70, "local fallback created", status="running", force=True)
                else:
                    raise RuntimeError(f"local source import failed: {exc}") from exc
        else:
            if video_url_kind(source_value) != request.source_kind:
                raise ValueError("请输入有效的 YouTube 或 B 站链接")

            report_stage_progress(job_id, "download", 5, "starting download", status="running", force=True)
            try:
                source_path = download_youtube(
                    job_id,
                    source_value,
                    "bestaudio/best" if DESKTOP and request.audio_only else build_yt_dlp_format_selector(request.resolution, request.fps),
                    progress_callback=lambda progress, message, raw=None: report_stage_progress(
                        job_id, "download", progress, message, status="running", raw=raw
                    ),
                    audio_only=DESKTOP and request.audio_only,
                )
            except Exception as exc:
                if ALLOW_PLACEHOLDER_ARTIFACTS:
                    source_path = ensure_placeholder_video(job_id, source_value)
                    report_stage_progress(job_id, "download", 70, "download fallback created", status="running", force=True)
                else:
                    if DESKTOP:
                        raise RuntimeError(online_media_error(source_value, str(exc))) from exc
                    raise RuntimeError(f"download failed: {exc}") from exc

        metadata = read_source_download_metadata(source_path) if DESKTOP else {}
        result = {
            "result_url": public_file_url(job_id, source_path.name),
            "source_video_url": public_file_url(job_id, source_path.name),
            "title": metadata.get("title") or request.title or source_path.stem,
            "original_description": metadata.get("description"),
            "artifact_name": source_path.name,
            "resolution": request.resolution,
            "fps": request.fps,
            "source_kind": request.source_kind,
            "source_value": source_value,
        }
        report_stage_progress(job_id, "download", 100, completion_message, status="succeeded", result=result, force=True)
    except Exception as error:
        stage = "download"
        fail_job(job_id, stage, error)


def run_stage_transcribe(job_id: str) -> None:
    try:
        state = load_state(job_id)
        request = StageTranscribeRequest.model_validate(state.request)
        report_stage_progress(
            job_id,
            "transcribe",
            5,
            f"starting transcription with {request.whisper_model} ({request.whisper_inference_mode})",
            status="running",
            force=True,
        )
        _, source_path = resolve_local_artifact_from_url(request.source_video_url)
        try:
            srt_path = transcribe_video(
                job_id,
                source_path,
                language=request.language,
                model_name=request.whisper_model,
                inference_mode=request.whisper_inference_mode,
                progress_callback=lambda progress, message, raw=None: report_stage_progress(
                    job_id, "transcribe", progress, message, status="running", raw=raw
                ),
            )
        except Exception as exc:
            if ALLOW_PLACEHOLDER_ARTIFACTS:
                srt_path = placeholder_srt(job_id, request.title or "video", source_path.name)
                report_stage_progress(job_id, "transcribe", 80, "transcription fallback created", status="running", force=True)
            else:
                raise RuntimeError(f"transcription failed: {exc}") from exc

        result = {
            "result_url": public_file_url(job_id, srt_path.name),
            "english_srt_url": public_file_url(job_id, srt_path.name),
            "artifact_name": srt_path.name,
            "whisper_model": request.whisper_model,
            "whisper_inference_mode": request.whisper_inference_mode,
        }
        aligned_words_path = artifact_path(job_id, "aligned_words.json")
        raw_segments_path = artifact_path(job_id, "raw_segments.json")
        diagnostics_path = artifact_path(job_id, "timing_diagnostics.json")
        runtime_path = artifact_path(job_id, "transcribe_runtime.json")
        if aligned_words_path.exists():
            result["aligned_words_url"] = public_file_url(job_id, aligned_words_path.name)
        if raw_segments_path.exists():
            result["raw_segments_url"] = public_file_url(job_id, raw_segments_path.name)
        if diagnostics_path.exists():
            result["timing_diagnostics_url"] = public_file_url(job_id, diagnostics_path.name)
        if runtime_path.exists():
            result["transcribe_runtime_url"] = public_file_url(job_id, runtime_path.name)
        from app import knowledge
        try:
            knowledge.load_cues(srt_path)
        except ValueError as error:
            raise RuntimeError(str(error)) from error
        report_stage_progress(job_id, "transcribe", 100, "transcription completed", status="succeeded", result=result, force=True)
    except Exception as error:
        fail_job(job_id, "transcribe", error)


def run_stage_translate(job_id: str) -> None:
    try:
        state = load_state(job_id)
        request = StageTranslateRequest.model_validate(state.request)
        report_stage_progress(
            job_id,
            "translate",
            5,
            f"starting translation with {request.translate_model}",
            status="running",
            force=True,
        )
        if request.subtitle_output_mode == "en_only":
            result = {
                "result_url": request.english_srt_url,
                "english_srt_url": request.english_srt_url,
                "bilingual_srt_url": request.english_srt_url,
                "artifact_name": Path(urlparse(request.english_srt_url).path).name or "english.srt",
                "translate_model": request.translate_model,
                "subtitle_output_mode": request.subtitle_output_mode,
            }
            report_stage_progress(job_id, "translate", 100, "translation skipped for English-only output", status="succeeded", result=result, force=True)
            return
        _, english_path = resolve_local_artifact_from_url(request.english_srt_url)
        bilingual_path = translate_srt(
            job_id,
            english_path,
            target_lang=request.target_lang,
            model_name=request.translate_model,
            context_note=request.translation_context_note,
            glossary=request.translation_glossary,
            progress_callback=lambda progress, message, raw=None: report_stage_progress(
                job_id, "translate", progress, message, status="running", raw=raw
            ),
        )
        translated = write_subtitle_mode_srt(job_id, bilingual_path, output_mode="zh_only", bilingual_order="en_top_zh_bottom")
        result = {
            "result_url": public_file_url(job_id, bilingual_path.name),
            "translated_srt_url": public_file_url(job_id, translated.name),
            "bilingual_srt_url": public_file_url(job_id, bilingual_path.name),
            "artifact_name": bilingual_path.name,
            "translate_model": request.translate_model,
            "subtitle_output_mode": request.subtitle_output_mode,
        }
        report_stage_progress(job_id, "translate", 100, "translation completed", status="succeeded", result=result, force=True)
    except Exception as error:
        fail_job(job_id, "translate", error)

def run_stage_burn(job_id: str) -> None:
    try:
        state = load_state(job_id)
        request = StageBurnRequest.model_validate(state.request)
        report_stage_progress(job_id, "burn", 5, "starting subtitle burn", status="running", force=True)
        _, source_path = resolve_local_artifact_from_url(request.source_video_url)
        subtitle_url = request.english_srt_url if request.subtitle_output_mode == "en_only" and request.english_srt_url else request.bilingual_srt_url
        _, subtitle_path = resolve_local_artifact_from_url(subtitle_url)
        try:
            final_path = burn_subtitle(
                job_id,
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
                burn_encoder=request.burn_encoder,
                output_name=request.output_name,
                progress_callback=lambda progress, message, raw=None: report_stage_progress(
                    job_id, "burn", progress, message, status="running", raw=raw
                ),
            )
        except Exception as exc:
            if ALLOW_PLACEHOLDER_ARTIFACTS:
                final_path = artifact_path(job_id, "final.mp4")
                try:
                    shutil.copyfile(source_path, final_path)
                except Exception:
                    final_path.write_text(
                        f"placeholder final video for {request.source_video_url}\ncreated_at={now_iso()}\n",
                        encoding="utf-8",
                    )
                report_stage_progress(job_id, "burn", 85, "subtitle burn fallback created", status="running", force=True)
            else:
                raise RuntimeError(f"subtitle burn failed: {exc}") from exc

        result = {
            "result_url": public_file_url(job_id, final_path.name),
            "final_video_url": public_file_url(job_id, final_path.name),
            "artifact_name": final_path.name,
            "download_name": f"{safe_download_filename(request.output_name)}.mp4" if request.output_name else final_path.name,
            "aspect_ratio": request.aspect_ratio,
            "subtitle_output_mode": request.subtitle_output_mode,
        }
        runtime_path = artifact_path(job_id, "burn_runtime.json")
        if runtime_path.is_file():
            result["burn_encoder"] = read_json(runtime_path).get("actual_encoder")
        if DESKTOP and request.subtitle_output_mode == "zh_only" and artifact_path(job_id, "zh_only.srt").is_file():
            result["translated_srt_url"] = public_file_url(job_id, "zh_only.srt")
        report_stage_progress(job_id, "burn", 100, "subtitle burn completed", status="succeeded", result=result, force=True)
    except Exception as error:
        fail_job(job_id, "burn", error)


def submit_stage_job(stage: str, request_payload: dict[str, Any]) -> str:
    state = create_stage_job(stage, request_payload)
    runner_map = {
        "download": run_stage_download,
        "transcribe": run_stage_transcribe,
        "translate": run_stage_translate,
        "burn": run_stage_burn,
        "bilibili_upload": run_stage_bilibili_upload,
    }
    runner = runner_map.get(stage)
    if runner is None:
        raise ValueError(f"unsupported stage: {stage}")
    executor.submit(runner, state.job_id)
    return state.job_id


def pipeline(job_id: str) -> None:
    try:
        state = load_state(job_id)
        request = VideoJobRequest.model_validate(state.request)
        if not request.rights_confirmed:
            raise PermissionError("rights_confirmed must be true before processing")
        if not is_youtube_url(request.youtube_url):
            raise ValueError("youtube_url must be a YouTube link")

        update_state(job_id, status="running", stage="download", progress=5, message="downloading source")
        try:
            source_path = download_youtube(
                job_id,
                request.youtube_url,
                build_yt_dlp_format_selector(request.resolution, request.fps),
            )
        except Exception as exc:
            if ALLOW_PLACEHOLDER_ARTIFACTS:
                source_path = ensure_placeholder_video(job_id, request.youtube_url)
            else:
                raise RuntimeError(f"download failed: {exc}") from exc

        update_state(job_id, stage="transcribe", progress=35, message=f"transcribing audio with {request.whisper_model}")
        try:
            english_srt = transcribe_video(
                job_id,
                source_path,
                language="en",
                model_name=request.whisper_model,
                inference_mode=request.whisper_inference_mode,
            )
        except Exception as exc:
            if ALLOW_PLACEHOLDER_ARTIFACTS:
                english_srt = placeholder_srt(job_id, request.title or "video", source_path.name)
            else:
                raise RuntimeError(f"transcription failed: {exc}") from exc

        bilingual_srt = english_srt
        if request.need_bilingual_srt and request.subtitle_output_mode != "en_only":
            update_state(job_id, stage="translate", progress=60, message=f"translating subtitles with {request.translate_model}")
            bilingual_srt = translate_srt(
                job_id,
                english_srt,
                target_lang=request.target_lang,
                model_name=request.translate_model,
                context_note=request.translation_context_note,
                glossary=request.translation_glossary,
            )
        elif request.subtitle_output_mode == "en_only":
            update_state(job_id, stage="translate", progress=60, message="skipping translation for English-only output")

        final_video: Path | None = None
        if request.need_burn_subtitle:
            update_state(job_id, stage="burn", progress=85, message="burning subtitles")
            try:
                final_video = burn_subtitle(
                    job_id,
                    source_path,
                    bilingual_srt,
                    aspect_ratio=request.aspect_ratio,
                    subtitle_font_size=request.subtitle_font_size,
                    subtitle_color=request.subtitle_color,
                    subtitle_outline_color=request.subtitle_outline_color,
                    subtitle_position=request.subtitle_position,
                    subtitle_margin=request.subtitle_margin,
                    subtitle_output_mode=request.subtitle_output_mode,
                    subtitle_style=request.subtitle_style,
                    output_name=build_output_name(
                        request.output_name_mode,
                        request.output_name_prefix,
                        request.output_index,
                        request.title or source_path.stem,
                    ),
                )
            except Exception as exc:
                if ALLOW_PLACEHOLDER_ARTIFACTS:
                    final_video = source_path
                else:
                    raise RuntimeError(f"subtitle burn failed: {exc}") from exc
        else:
            final_video = source_path

        finalize_success(job_id, request, source_path, english_srt, bilingual_srt, final_video)
    except Exception as error:
        stage = "validation"
        try:
            current = load_state(job_id)
            stage = current.stage or stage
        except Exception:
            pass
        fail_job(job_id, stage, error)


def submit_job(request: VideoJobRequest) -> JobState:
    state = create_job(request)
    executor.submit(pipeline, state.job_id)
    return state


def batch_item_settings(batch_request: dict[str, Any], item: BatchItemState) -> dict[str, Any]:
    settings = dict(batch_request or {})
    overrides = settings.get("item_overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}
    override = {}
    for key in (item.client_row_id, item.source_value):
        if key and isinstance(overrides.get(key), dict):
            override = dict(overrides[key])
            break
    if not override:
        return settings
    for key, value in override.items():
        if key == "bilibili_upload" and isinstance(value, dict):
            merged_upload = dict(settings.get("bilibili_upload") or {})
            merged_upload.update(value)
            settings[key] = merged_upload
        else:
            settings[key] = value
    return settings
