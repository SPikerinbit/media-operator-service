
"""Run the existing media stages directly and checkpoint their artifacts."""
from pathlib import Path
import json
import threading

from fastapi import HTTPException

from app import knowledge
from app import desktop_config
from app import desktop_sources
from app import main as media


RUNNERS = {
    "download": media.run_stage_download,
    "transcribe": media.run_stage_transcribe,
    "translate": media.run_stage_translate,
    "burn": media.run_stage_burn,
    "bilibili_upload": media.run_stage_bilibili_upload,
}
OUTPUTS = {
    "download": "source_video_url",
    "transcribe": "english_srt_url",
    "translate": "bilingual_srt_url",
    "burn": "final_video_url",
}
TRANSCRIPTION_SLOTS = threading.BoundedSemaphore(1)
BATCH_SLOTS = {}
DOWNLOAD_CONTEXTS = {}


def download_context(request):
    context = DOWNLOAD_CONTEXTS.get((request.operator_batch_id, request.operator_item_id))
    if context:
        return context
    from app import workbench_cache as cache
    cache.initialize()
    cookies = desktop_sources.cookies_for(request.source_value, "")
    reused = cache.reused_probe(request.source_value)
    if reused:
        return reused, cookies
    return (desktop_sources.probe(request.source_value, request.source_kind), cookies)


def probe_source(source, *, refresh=False):
    """Preflight and execute reuse a verified local file before opening the network."""
    from app import workbench_cache as cache
    cache.initialize()
    if not refresh:
        reused = cache.reused_probe(source.source_value)
        if reused:
            return with_share_duration(reused, source)
        info = desktop_sources.probe(source.source_value, source.source_kind, source.session_id)
    else:
        info = desktop_sources.probe(source.source_value, source.source_kind, source.session_id, refresh=True)
    return with_share_duration(info, source)


def same_source(left, right):
    if left == right:
        return True
    from app.sites.resolve import identity
    return identity(left) == identity(right)


def reuse_source(source):
    if not source.continue_from:
        return None
    _, previous = batch_item(*source.continue_from)
    if (previous.status != "succeeded" or not same_source(previous.source_value, source.source_value)
            or previous.source_kind != source.source_kind or previous.media_type != "video"
            or not (previous.result or {}).get("transcript_id")):
        raise ValueError("原任务没有可继续处理的字幕")
    return previous


def reusable_media(cache_key, need_video):
    found = knowledge.cached_id(cache_key)
    if not found:
        return None
    record = knowledge.read_transcript(found)
    playable = record.get("playable")
    if not playable:
        return None
    path = Path(playable)
    try:
        path.resolve().relative_to(media.JOBS_DIR.resolve())
    except (OSError, ValueError):
        return None
    if not path.is_file():
        return None
    kind = path.suffix.lower().lstrip(".")
    video = kind in desktop_sources.VIDEO_EXTS
    audio = kind in desktop_sources.AUDIO_EXTS
    if video or (audio and not need_video):
        return record, path
    return None


def cached_transcription(source, language, model, inference):
    if inference == 'gpu_only':return None
    from app import workbench_cache as cache
    cache.initialize()
    return cache.read(cache.signature('transcribe', source, {'source_video_url':source,
                      'language':language,'whisper_model':model,'whisper_inference_mode':inference}))


def transcript_lane(transcript_id, fallback):
    # Older releases stored transcript provenance in task history rather than the
    # stage cache. Only a completed recorded artifact establishes a reuse mark.
    for batch in stored_batches():
        if any((item.result or {}).get('transcript_id') == transcript_id for item in batch.items):
            return 'notes' if batch.request.get('knowledge_only') else 'publish'
    return fallback


def with_share_duration(info, source):
    hint = getattr(source, "expected_duration", None)
    if not hint:
        return info
    return {**info, "share_duration": hint, "duration": info.get("duration") or hint}


def plan_batch(request):
    stages = list(RUNNERS)
    planned = {}
    sources = request.sources or []
    if len({source.client_row_id for source in sources}) != len(sources):
        raise HTTPException(400, "素材标识重复")
    for source in sources:
        row_id = source.client_row_id
        info = {}
        try:
            info = probe_source(source)
            media_type = info["media_type"]
            if media_type == "note":
                if not request.knowledge_only:
                    raise desktop_sources.SourceError("note_only", "没有可烧录的视频。请改到笔记。")
                planned[row_id] = {
                    "ready": True, "title": info.get("title"), "media_type": "note", "stop_after": "download",
                    "planned_stages": ["download"], "platform": info.get("platform"), "duration": info.get("duration"),
                }
                continue
            stop = source.stop_after or ("transcribe" if request.knowledge_only else "bilibili_upload")
            if media_type != "video":
                stop = "transcribe"
            if media_type == "unknown" and not source.allow_unknown_audio:
                raise ValueError("未能识别媒体类型，请选择按字幕导入")
            settings = media.batch_item_settings(request.model_dump(), source)
            steps = stages[:stages.index(stop) + 1]
            if stop != "translate" and settings.get("subtitle_output_mode") == "en_only" and "translate" in steps:
                steps.remove("translate")
            previous = reuse_source(source)
            if "transcribe" in steps:
                if not info["has_audio"]:
                    raise ValueError("此素材没有音轨")
                if (source.source_kind != "local" and stop in {"transcribe", "translate"} and media_type == "video"
                        and not info["audio_direct"] and not source.allow_muxed_audio):
                    raise desktop_sources.SourceError("muxed_audio", "只有合流。请先允许下载视频并提取音轨。")
                model = settings["whisper_model"]
                inference = settings["whisper_inference_mode"]
                cache_key = knowledge.transcription_key(source.source_kind, source.source_value,
                                                       settings["source_language"], model, inference)
                explicit = request.transcript_ids.get(row_id)
                if explicit:
                    transcript = knowledge.read_transcript(explicit)
                    if not same_source(transcript["source"], source.source_value) or transcript["source_kind"] != source.source_kind:
                        raise ValueError("所选字幕与来源不匹配")
                    if inference == "gpu_only" and not previous:
                        raise ValueError("严格 GPU 模式需要重新转录，请直接添加素材")
                if not (explicit or previous or (inference != "gpu_only" and knowledge.cached_id(cache_key))
                        or cached_transcription(source.source_value, settings['source_language'], model, inference)):
                    if not media.whisper_model_status(model)["available"]:
                        raise ValueError(f"请在设置中下载 Whisper {model}")
                    if inference == "gpu_only" and desktop_config.worker_environment()["WHISPER_DEVICE"] != "cuda":
                        raise ValueError("请先在设置中检测并启用 NVIDIA 转录加速")
            if "translate" in steps and not media.TRANSLATE_API_KEY:
                raise ValueError("请先在设置中配置 DeepSeek")
            if "bilibili_upload" in steps:
                if not media.bilibili_configured():
                    raise ValueError("请先在设置中配置 B 站投稿凭据")
                upload = media.BilibiliUploadSettings.model_validate(settings["bilibili_upload"])
                validate_upload_category(upload)
                if upload.copyright == 2:
                    address = upload.source if upload.source_mode == "custom" else source.source_value
                    if not media.is_http_url(address):
                        raise ValueError("转载须填写来源网址")
            plan = {"media_type": media_type, "stop_after": stop, "planned_stages": steps,
                    "platform": info["platform"], "duration": info.get("duration")}
            planned[row_id] = {"ready": True, "title": info.get("title"), **plan}
        except (HTTPException, ValueError, OSError) as error:
            planned[row_id] = {"ready": False, "title": info.get("title") or source.source_title,
                               "code": getattr(error, "code", "blocked"),
                               "message": error.detail if isinstance(error, HTTPException) else str(error)}
    return planned


def batch_item(batch_id, item_id):
    batch = media.load_batch(batch_id)
    item = next((item for item in batch.items if item.item_id == item_id), None)
    if item is None:
        raise FileNotFoundError(item_id)
    return batch, item


def douyin_item(item):
    return (getattr(item, "platform", "") == "抖音") or "douyin.com" in (getattr(item, "source_value", "") or "")


def douyin_result_stale(item):
    if not douyin_item(item):
        return False
    result = item.result or {}
    subtitle = result.get("english_srt_url")
    if subtitle:
        try:
            _, path = media.resolve_local_artifact_from_url(subtitle)
            knowledge.load_cues(path)
        except Exception:
            return True
    expected = item.duration
    actual = result.get("duration")
    if expected and actual is not None and not desktop_sources.duration_matches(actual, expected):
        return True
    return False


def reusable_stage(item, stage, previous, payload):
    if previous.status != "succeeded":
        return None
    if stage != "bilibili_upload" and any(previous.request.get(key) != value for key, value in payload.items()):
        return None
    result = previous.result or {}
    if stage == "transcribe":
        try:
            _, path = media.resolve_local_artifact_from_url(result["english_srt_url"])
            knowledge.load_cues(path)
        except Exception:
            return None
    if stage == "download" and douyin_item(item):
        expected = item.duration
        actual = result.get("duration")
        if expected and actual is not None and not desktop_sources.duration_matches(actual, expected):
            return None
    if stage in OUTPUTS:
        try:
            media.resolve_local_artifact_from_url(result[OUTPUTS[stage]])
        except (FileNotFoundError, ValueError, KeyError):
            return None
    return result


def stage_result(batch_id, item_id, stage, payload, transcript_id=None):
    from app import workbench_cache as cache
    cache.initialize()
    batch, item = batch_item(batch_id, item_id)
    if stage == 'bilibili_upload' or (stage == 'transcribe' and payload.get('whisper_inference_mode') == 'gpu_only'):
        return _stage_result_uncached(batch_id, item_id, stage, payload, transcript_id)
    key = cache.signature(stage, item.source_value, payload)
    lane = 'notes' if batch.request.get('knowledge_only') else 'publish'
    def waiting():
        media.update_batch_item(batch_id, item_id, stage=stage, message='等待已有任务完成可共享步骤')
    flight_key=cache.signature(stage,item.source_value,{**payload,'audio_only':False}) if stage=='download' else key
    with cache.flight(flight_key, waiting):
        found = cache.read(key)
        if not found and stage == 'download' and payload.get('audio_only'):
            found = cache.read(cache.signature(stage, item.source_value, {**payload, 'audio_only': False}))
        if found:
            _, current = batch_item(batch_id, item_id)
            steps = current.planned_stages or list(RUNNERS)
            progress = ({'download':15,'transcribe':60,'translate':80}.get(stage,current.progress) if batch.request.get('notes_auto') else
                        min(99, round((steps.index(stage)+1)/len(steps)*100)) if stage in steps else current.progress)
            media.update_batch_item(batch_id, item_id, stage=stage, status='running', progress=max(current.progress, progress),
                                    message='已复用' + {'download':'源媒体','transcribe':'原文字幕','translate':'译文','burn':'成片'}.get(stage,stage),
                                    stage_details={**current.stage_details, stage: {'status':'succeeded','progress':100,'reused':True,'origin_lane':found['lane']}})
            return {**found['result'], 'reuse': [{'stage': stage, 'origin_lane': found['lane']}]}
        result = _stage_result_uncached(batch_id, item_id, stage, payload, transcript_id)
        origin=transcript_lane(transcript_id,lane) if stage=='transcribe' and transcript_id else lane
        cache.save(key, stage, origin, result, item.source_value)
        if transcript_id and stage=='transcribe':result={**result,'reuse':[{'stage':stage,'origin_lane':origin}]}
        return result


def _stage_result_uncached(batch_id, item_id, stage, payload, transcript_id=None):
    _, item = batch_item(batch_id, item_id)
    payload = {**payload, "operator_batch_id": batch_id, "operator_item_id": item_id}
    previous_id = item.stage_jobs.get(stage)
    if previous_id:
        try:
            previous = media.load_state(previous_id)
            result = reusable_stage(item, stage, previous, payload)
            if result is not None:
                return result
        except (FileNotFoundError, ValueError, KeyError):
            pass

    state = media.create_stage_job(stage, payload)
    if stage == "transcribe":
        with TRANSCRIPTION_SLOTS:
            if transcript_id:
                try:
                    path = knowledge.subtitle_file(transcript_id, media.artifact_path(state.job_id, "english.srt"))
                    media.report_stage_progress(state.job_id, stage, 100, "已复用原文字幕",
                                                status="succeeded", force=True, result={
                        "english_srt_url": media.public_file_url(state.job_id, path.name),
                    })
                except Exception as error:
                    media.fail_job(state.job_id, stage, error)
            else:
                RUNNERS[stage](state.job_id)
    else:
        RUNNERS[stage](state.job_id)

    finished = media.load_state(state.job_id)
    if finished.status != "succeeded":
        error = finished.error or {}
        raise RuntimeError(error.get("message") or finished.message)
    return finished.result or {}


def note_material(result, item):
    body = result.get("body") or ""
    images = []
    try:
        _, path = media.resolve_local_artifact_from_url(result["source_video_url"])
    except (KeyError, ValueError, OSError):
        return body or item.source_title or "图文笔记", []
    meta = path.with_name("note.json")
    if meta.is_file():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        body = data.get("body") or body
        root = media.DATA_DIR.resolve()
        for name in data.get("images") or []:
            image = (path.parent / str(name)).resolve()
            if image.is_file() and root in image.parents:
                images.append(str(image))
    return body or item.source_title or result.get("title") or "图文笔记", images


def ensure_note_srt(result, body):
    _, path = media.resolve_local_artifact_from_url(result["source_video_url"])
    target = path.with_name("note.srt")
    text = " ".join((body or "").split()).replace("-->", "—")[:4000] or "图文笔记"
    target.write_text(f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n\n", encoding="utf-8")
    return target


def finish_note(batch_id, item_id, item, result, download_payload, transcript_id, explicit_transcripts,
                cache_key, source_title, output_name, run):
    if explicit_transcripts.get(item.client_row_id) and transcript_id:
        transcript = knowledge.read_transcript(transcript_id)
        if not same_source(transcript["source"], item.source_value) or transcript["source_kind"] != item.source_kind:
            raise ValueError("所选字幕与来源不匹配")
    if not transcript_id:
        run("download", download_payload)
        body, images = note_material(result, item)
        transcript_id = knowledge.register(
            ensure_note_srt(result, body), source_kind=item.source_kind, source=item.source_value,
            title=source_title or result.get("title") or "图文笔记", cache_key=cache_key,
            media_type="note", asset_type="note", note_body=body, note_images=images,
        )
        result["body"] = body
    else:
        record = knowledge.read_transcript(transcript_id)
        result["body"] = record.get("note_body") or result.get("body") or ""
        result["title"] = result.get("title") or record.get("title") or source_title
    result.update(transcript_id=transcript_id, media_type="note", asset_type="note", has_audio=False)
    batch, _ = batch_item(batch_id, item_id)
    if batch.request.get('notes_auto'):
        from app import workbench_notes
        path = media.artifact_path('note_' + str(transcript_id), 'body.srt')
        path.parent.mkdir(parents=True, exist_ok=True)
        # Sequential slots are an internal translation transport only; UI references remain paragraphs.
        cues = knowledge.read_transcript(transcript_id)['cues']
        import srt
        from datetime import timedelta
        path.write_text(srt.compose([srt.Subtitle(c['number'],timedelta(seconds=c['number']*2),timedelta(seconds=c['number']*2+1),c['text']) for c in cues]), encoding='utf-8')
        result['english_srt_url'] = media.public_file_url(path.parent.name, path.name)
        workbench_notes.complete(batch_id, item_id, result, batch.request, run)
    result.setdefault("images", [])
    media.update_batch_item(batch_id, item_id, status="succeeded", stage="done", progress=100,
                            message="图文笔记已保存", result={**result, "output_name": output_name}, clear_error=True)


def run_item(batch_id, item_id):
    stage = "download"
    result = {}
    with media.batch_lock:
        try:
            _, existing = batch_item(batch_id, item_id)
        except (FileNotFoundError, ValueError):
            return
        if existing.status == "cancelled":
            return
        if existing.status == "queued":
            media.update_batch_item(batch_id, item_id, status="running", message=existing.message or "正在处理")
    try:
        batch, item = batch_item(batch_id, item_id)
        if item.status == "cancelled":
            return
        settings = media.batch_item_settings(batch.request, item)
        knowledge_only = bool(batch.request.get("knowledge_only"))
        managed = item.planned_stages is not None
        planned = item.planned_stages or []
        source = next((media.SourceInput.model_validate(entry) for entry in batch.request.get("sources", [])
                       if entry.get("client_row_id") == item.client_row_id), None) if managed else None
        previous = reuse_source(source) if source else None
        output_name = item.output_name or f"source{item.index}"
        source_title = item.source_title
        language = settings.get("source_language") or "auto"
        model = settings.get("whisper_model") or media.WHISPER_MODEL
        inference = settings.get("whisper_inference_mode") or media.WHISPER_INFERENCE_MODE
        try:
            from app import workbench_cache as cache
            cache.remember_source(item.source_value, item.source_value, "", {
                "title": source_title or "", "platform": item.platform or "", "media_type": item.media_type or "",
                "language": language, "model": model, "inference": inference, "kind": item.source_kind or "",
            }, kind=item.source_kind or "")
        except Exception:
            pass
        mode = settings.get("subtitle_output_mode") or "en_only"
        explicit_transcripts = batch.request.get("transcript_ids") or {}
        if inference == "gpu_only" and explicit_transcripts.get(item.client_row_id) and not previous:
            raise ValueError("严格 GPU 模式需要重新转录，请直接添加视频素材。")
        cache_key = knowledge.transcription_key(item.source_kind, item.source_value, language, model, inference)
        transcript_id = (previous.result["transcript_id"] if previous else None) or explicit_transcripts.get(item.client_row_id) or (
            knowledge.cached_id(cache_key) if inference != "gpu_only" else None
        )
        if not transcript_id and (not managed or "transcribe" in planned) and not cached_transcription(item.source_value,language,model,inference):
            stage = "transcribe"
            if not media.whisper_model_status(model)["available"]:
                raise ValueError(f"本地 Whisper {model} 未准备好，请在「设置 → 转录与本地资源」下载后重试。")
            if inference == "gpu_only" and desktop_config.worker_environment()["WHISPER_DEVICE"] != "cuda":
                raise ValueError("严格 GPU 模式需要启用 NVIDIA 转录加速，请先在设置中检测和启用。")

        def run(name, payload, transcript_id=None):
            nonlocal stage, source_title
            stage = name
            output = stage_result(batch_id, item_id, name, payload, transcript_id)
            reuse = [*(result.get('reuse') or []), *(output.pop('reuse', []) or [])]
            result.update(output)
            if reuse:
                result['reuse'] = reuse
            if name == "download":
                source_title = media.source_display_title(item.source_kind, item.source_value, result.get("title") or "") or source_title
            media.update_batch_item(batch_id, item_id, result={**result, "output_name": output_name},
                                    source_title=source_title if name == "download" else None)

        download_payload = {
            "source_kind": item.source_kind, "source_value": item.source_value, "rights_confirmed": True,
            "resolution": settings.get("resolution"), "fps": settings.get("fps"),
            "title": Path(item.source_value).stem if item.source_kind == "local" else item.source_value,
            "audio_only": (item.source_kind != "local" and (item.media_type != "video"
                           or item.stop_after in {"transcribe", "translate"})) if managed
                          else knowledge_only and item.source_kind != "local",
        }
        if source:
            download_payload.update(managed=True, allow_muxed_audio=source.allow_muxed_audio,
                                    retain_cover="burn" in planned)
        if item.media_type == "note":
            finish_note(batch_id, item_id, item, result, download_payload, transcript_id, explicit_transcripts,
                        cache_key, source_title, output_name, run)
            return
        original = previous.result if previous else {}
        existing = original.get("source_video_url") if original.get("asset_type") == "video" else None
        if existing:
            try:
                media.resolve_local_artifact_from_url(existing)
            except (ValueError, OSError):
                existing = None
        if not existing and inference != "gpu_only" and knowledge_only:
            reused = reusable_media(cache_key, not download_payload["audio_only"])
            if reused:
                record, path = reused
                existing = media.public_file_url(path.parent.name, path.name)
                original = {
                    "source_video_url": existing, "source_media_url": existing, "title": record.get("title") or "",
                    "asset_type": "video" if path.suffix.lower().lstrip(".") in desktop_sources.VIDEO_EXTS else "audio",
                    "has_audio": True,
                }
                transcript_id = transcript_id or record["id"]
        if existing:
            result.update({key: original[key] for key in ("source_video_url", "source_media_url", "title",
                           "original_description", "asset_type", "duration", "has_audio") if key in original})
            if transcript_id:
                result['reuse']=[{'stage':'download','origin_lane':transcript_lane(transcript_id,'notes' if knowledge_only else 'publish')}]
            media.update_batch_item(batch_id, item_id, result={**result, "output_name": output_name},
                                    stage_details={**item.stage_details, "download": {
                                        "status": "succeeded", "progress": 100, "message": "已复用源视频",
                                    }})
        else:
            run("download", download_payload)
        if managed and "transcribe" not in planned:
            media.update_batch_item(batch_id, item_id, status="succeeded", stage="done", progress=100,
                                    message="素材已导入", result={**result, "output_name": output_name}, clear_error=True)
            return
        if managed and result.get("has_audio") is False:
            stage = "transcribe"
            raise ValueError("下载产物没有可用音轨，无法提取字幕")
        if explicit_transcripts.get(item.client_row_id):
            transcript = knowledge.read_transcript(transcript_id)
            if not same_source(transcript["source"], item.source_value) or transcript["source_kind"] != item.source_kind:
                raise ValueError("所选字幕与视频来源不匹配")
        run("transcribe", {
            "source_video_url": result["source_video_url"], "language": language, "whisper_model": model,
            "whisper_inference_mode": inference,
        }, transcript_id)

        _, srt_path = media.resolve_local_artifact_from_url(result["english_srt_url"])
        _, source_path = media.resolve_local_artifact_from_url(result["source_video_url"])
        stage = "transcribe"
        try:
            if not transcript_id:
                transcript_id = knowledge.register(
                    srt_path, source_kind=item.source_kind, source=item.source_value,
                    title=source_title or item.platform or {"youtube": "YouTube 视频", "bilibili": "B 站视频"}.get(item.source_kind, "在线素材"),
                    playable=source_path, cache_key=cache_key,
                    media_type=item.media_type, asset_type=result.get("asset_type"),
                )
        except ValueError:
            if knowledge_only or managed:
                raise
        if transcript_id:
            result["transcript_id"] = transcript_id

        translate = "translate" in planned if managed else not knowledge_only and mode != "en_only"
        if translate and not batch.request.get('notes_auto'):
            run("translate", {
                "english_srt_url": result["english_srt_url"],
                **{key: settings[key] for key in (
                    "target_lang", "translate_model", "subtitle_output_mode", "translation_context_profile_id",
                    "translation_context_note", "translation_glossary",
                ) if key in settings},
                **({"subtitle_output_mode": "bilingual"} if mode == "en_only" else {}),
            })
        if batch.request.get('notes_auto') and transcript_id:
            from app import workbench_notes
            stage = 'extract'
            workbench_notes.complete(batch_id, item_id, result, settings, run)
        burn = "burn" in planned if managed else not knowledge_only
        if burn:
            run("burn", {
                "source_video_url": result["source_video_url"], "english_srt_url": result["english_srt_url"],
                "bilingual_srt_url": result.get("bilingual_srt_url", result["english_srt_url"]),
                "output_name": output_name,
                **{key: settings[key] for key in (
                    "aspect_ratio", "subtitle_font_size", "subtitle_color", "subtitle_outline_color",
                    "subtitle_position", "subtitle_margin", "subtitle_output_mode", "subtitle_style", "burn_encoder",
                ) if key in settings},
            })
            upload = media.BilibiliUploadSettings.model_validate(settings.get("bilibili_upload") or {})
            publish = "bilibili_upload" in planned if managed else upload.enabled
            if publish:
                run("bilibili_upload", {
                    "final_video_url": result["final_video_url"], "original_source": item.source_value,
                    "source_video_url": result["source_video_url"], "english_srt_url": result["english_srt_url"],
                    "translate_model": settings.get("translate_model") or "",
                    "output_name": output_name, "original_title": result.get("title", output_name),
                    "original_description": result.get("original_description"),
                    "upload_settings": {**upload.model_dump(), "enabled": True},
                })
        media.update_batch_item(batch_id, item_id, status="succeeded", stage="done", progress=100,
                                message="已完成", result={**result, "output_name": output_name}, clear_error=True)
    except Exception as error:
        message = str(error)
        if stage == "bilibili_upload":
            _, current = batch_item(batch_id, item_id)
            result.update(current.result or {})
        failure = {"stage": stage, "message": message}
        reason = desktop_sources.refresh_reason(error)
        if reason:
            failure["refresh_reason"] = reason
        media.update_batch_item(batch_id, item_id, status="failed", stage=stage, message=message,
                                result=result or None, error=failure)
    finally:
        DOWNLOAD_CONTEXTS.pop((batch_id, item_id), None)


def enqueue(batch, item_id, upload_job_id=None):
    slots = BATCH_SLOTS.setdefault(batch.batch_id, threading.BoundedSemaphore(
        batch.request.get("batch_concurrency") or media.BATCH_WORKER_CONCURRENCY,
    ))

    def work():
        with slots:
            if upload_job_id:
                run_history_upload(batch.batch_id, item_id, upload_job_id)
            else:
                run_item(batch.batch_id, item_id)

    media.batch_executor.submit(work)


def validate_upload_category(upload):
    if upload.tid is None and not (upload.auto_metadata and media.TRANSLATE_API_KEY):
        raise HTTPException(400, "请手动选择 B 站投稿分区，或配置 DeepSeek 后使用自动分区")


def submit_desktop_batch(request):
    if any(source.stop_after is not None or source.source_kind == "url" for source in request.sources or []):
        decisions = plan_batch(request)
        if any(not decision["ready"] for decision in decisions.values()):
            raise HTTPException(409, next(decision["message"] for decision in decisions.values() if not decision["ready"]))
        publishing = {row_id for row_id, plan in decisions.items() if "bilibili_upload" in plan["planned_stages"]}
        if set(request.publish_confirmed) != publishing:
            raise HTTPException(409, "请确认本批实际会投稿的视频")
        plans = {row_id: {key: plan[key] for key in ("media_type", "stop_after", "planned_stages", "platform", "duration")}
                 for row_id, plan in decisions.items()}
        contexts = {}
        for source in request.sources:
            info = probe_source(source)
            contexts[source.client_row_id] = (info, desktop_sources.cookies_for(source.source_value, source.session_id))
            source.source_title = str(info.get("title") or source.source_title)[:500]
        batch = media.create_batch(request, plans)
        for item in batch.items:
            DOWNLOAD_CONTEXTS[batch.batch_id, item.item_id] = contexts[item.client_row_id]
            enqueue(batch, item.item_id)
        for source in request.sources:
            desktop_sources.forget_session(source.session_id)
        return batch
    if any(source.source_kind != "local" and media.video_url_kind(source.source_value) != source.source_kind
           for source in request.sources):
        raise HTTPException(400, "请输入有效的 YouTube 或 B 站链接")
    if not request.knowledge_only:
        for override in [{}, *request.item_overrides.values()]:
            if not isinstance(override, dict):
                continue
            mode = override.get("subtitle_output_mode", request.subtitle_output_mode)
            if mode != "en_only" and not media.TRANSLATE_API_KEY:
                raise HTTPException(400, "请先在设置中配置 DeepSeek，或选择原文字幕")
            upload = media.BilibiliUploadSettings.model_validate({
                **request.bilibili_upload.model_dump(), **(override.get("bilibili_upload") or {}),
            })
            if upload.enabled:
                if not media.bilibili_configured():
                    raise HTTPException(400, "请先在设置中配置 B 站投稿凭据")
                validate_upload_category(upload)
    batch = media.create_batch(request)
    for item in batch.items:
        enqueue(batch, item.item_id)
    return batch


def stored_batches():
    batches = []
    for path in media.BATCHES_DIR.glob("batch_*"):
        try:
            batches.append(media.load_batch(path.name))
        except (FileNotFoundError, ValueError, OSError):
            continue
    return sorted(batches, key=lambda batch: batch.created_at, reverse=True)


def recover_interrupted():
    for batch in stored_batches():
        for item in batch.items:
            if item.status in {"queued", "running"}:
                message = "应用上次关闭时任务尚未完成，可以重试"
                media.update_batch_item(batch.batch_id, item.item_id, status="failed", message=message,
                                        error={"stage": item.stage, "message": message})


def previous_upload(item):
    job_id = item.stage_jobs.get("bilibili_upload")
    try:
        return media.load_state(job_id) if job_id else None
    except (FileNotFoundError, ValueError):
        return None


def upload_candidate(item):
    previous = previous_upload(item)
    result = item.result or {}
    submitted = result.get("bilibili_url") or result.get("bvid") or result.get("aid")
    if submitted or (previous and previous.status == "succeeded"
                     and not (previous.result or {}).get("bilibili_upload_skipped")):
        return {"state": "posted", "message": "已有成功投稿记录"}
    if item.status in {"queued", "running"}:
        return {"state": "busy", "message": "任务正在处理"}
    if not result.get("final_video_url"):
        return {"state": "missing", "message": "任务尚未生成成片"}
    try:
        _, path = media.resolve_local_artifact_from_url(result["final_video_url"])
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError("missing video")
    except (ValueError, OSError):
        return {"state": "missing", "message": "原成片已移走或不可读取"}
    if item.stage == "bilibili_upload" or item.stage_jobs.get("bilibili_upload"):
        return {"state": "retry", "message": "复用成片和原投稿参数"}
    return {"state": "ready", "message": "复用成片，使用当前批次默认投稿参数"}


def upload_candidates(batch_id):
    batch = media.load_batch(batch_id)
    if batch.request.get("knowledge_only"):
        return {}
    return {item.item_id: upload_candidate(item) for item in batch.items}


def run_history_upload(batch_id, item_id, job_id):
    with media.batch_lock:
        try:
            _, item = batch_item(batch_id, item_id)
        except (FileNotFoundError, ValueError):
            return
        if item.status == "cancelled":
            return
    try:
        RUNNERS["bilibili_upload"](job_id)
    except Exception as error:
        media.fail_job(job_id, "bilibili_upload", error)
    finished = media.load_state(job_id)
    with media.batch_lock:
        _, item = batch_item(batch_id, item_id)
        if item.stage_jobs.get("bilibili_upload") != job_id:
            return
        if finished.status == "succeeded":
            media.update_batch_item(batch_id, item_id, status="succeeded", stage="done", progress=100,
                                    message="投稿完成", result={**(item.result or {}), **(finished.result or {})},
                                    clear_error=True)
        else:
            error = finished.error or {"stage": "bilibili_upload", "message": finished.message}
            media.update_batch_item(batch_id, item_id, status="failed", stage="bilibili_upload",
                                    message=str(error.get("message") or "投稿失败"), error=error)


def queue_history_uploads(batch_id, item_ids, confirmed, defaults=None, use_current_settings=False):
    if not confirmed:
        raise HTTPException(409, "请先到 B 站核对稿件状态，再确认投稿")
    if not media.bilibili_configured():
        raise HTTPException(400, "请先在设置中配置 B 站投稿凭据")
    if len(set(item_ids)) != len(item_ids):
        raise HTTPException(400, "投稿选项中包含重复任务")
    with media.batch_lock:
        batch = media.load_batch(batch_id)
        if batch.request.get("knowledge_only"):
            raise HTTPException(409, "字幕分析任务没有可投稿的成片")
        indexed = {item.item_id: item for item in batch.items}
        planned = []
        for item_id in item_ids:
            item = indexed.get(item_id)
            if item is None:
                raise FileNotFoundError(item_id)
            state = upload_candidate(item)
            if state["state"] not in {"retry", "ready"}:
                raise HTTPException(409, f"第 {item.index} 项无法投稿：{state['message']}")
            previous = previous_upload(item)
            reuse_settings = state["state"] == "retry" and not use_current_settings
            previous_request = previous.request if previous and reuse_settings else {}
            settings = media.batch_item_settings(batch.request, item)
            if reuse_settings:
                old = previous_request.get("upload_settings") or settings.get("bilibili_upload")
                upload = media.BilibiliUploadSettings.model_validate({**(old or {}), "enabled": True})
            else:
                if defaults is None:
                    raise HTTPException(400, "请为首次投稿的成片提供投稿参数")
                upload = defaults
            validate_upload_category(upload)
            if upload.copyright == 2:
                source = upload.source if upload.source_mode == "custom" else item.source_value
                if not media.is_http_url(source):
                    raise HTTPException(400, f"第 {item.index} 项是转载，请在投稿参数中填写有效的来源网址")
            result = item.result or {}
            planned.append((item, media.StageBilibiliUploadRequest(
                final_video_url=result["final_video_url"], original_source=item.source_value,
                source_video_url=result.get("source_video_url") or "",
                english_srt_url=result.get("english_srt_url") or "",
                translate_model=previous_request.get("translate_model") or "",
                bilibili_metadata=previous_request.get("bilibili_metadata"),
                output_name=item.output_name or f"source{item.index}",
                original_title=str(previous_request.get("original_title") or result.get("title") or item.output_name or f"source{item.index}"),
                original_description=previous_request.get("original_description", result.get("original_description")),
                upload_settings=upload, allow_automatic_retry=False,
                operator_batch_id=batch_id, operator_item_id=item_id,
            )))

        queued = []
        for item, payload in planned:
            job = media.create_stage_job("bilibili_upload", payload.model_dump())
            item.stage_jobs["bilibili_upload"] = job.job_id
            item.stage_details["bilibili_upload"] = {
                "job_id": job.job_id, "status": "queued", "progress": 0, "message": "等待投稿",
            }
            item.status = "queued"
            item.stage = "bilibili_upload"
            item.progress = media.stage_overall_progress("bilibili_upload", 0)
            item.local_progress = 0
            item.message = "等待投稿"
            item.progress_detail = ""
            item.log_tail = []
            item.error = None
            item.active_stage_job_id = job.job_id
            item.updated_at = media.now_iso()
            queued.append((item.item_id, job.job_id))
        data = batch.model_dump()
        data["updated_at"] = media.now_iso()
        media.recompute_batch_counts(data)
        batch = media.save_batch(media.BatchState.model_validate(data))
        for item_id, job_id in queued:
            enqueue(batch, item_id, job_id)
        return batch


def cancel_queued(batch_id, item_id):
    """Atomically cancel a queued item that has not started. Returns (ok, message)."""
    with media.batch_lock:
        try:
            _, item = batch_item(batch_id, item_id)
        except (FileNotFoundError, ValueError):
            return False, "任务记录不可用"
        if item.status == "cancelled":
            return True, ""
        if item.status != "queued":
            if item.stage == "bilibili_upload":
                return False, "投稿已开始，不能删除"
            return False, "任务已开始执行，不能删除"
        job_id = (item.stage_jobs or {}).get("bilibili_upload") or (
            item.active_stage_job_id if item.stage == "bilibili_upload" else "")
        if job_id:
            try:
                state = media.load_state(job_id)
            except (FileNotFoundError, ValueError, OSError):
                state = None
            if state is not None and state.status in {"running", "succeeded"}:
                return False, "投稿已开始，不能删除"
        media.update_batch_item(batch_id, item_id, status="cancelled", stage="cancelled", message="已取消")
        return True, ""


def retry(batch_id, item_id, confirmed, session_id=""):
    with media.batch_lock:
        batch, item = batch_item(batch_id, item_id)
        if item.status != "failed":
            raise HTTPException(409, "任务当前无法重试")
        if item.stage == "bilibili_upload":
            return queue_history_uploads(batch_id, [item_id], confirmed)
        if douyin_result_stale(item):
            kept = {key: value for key, value in item.stage_jobs.items() if key not in {"download", "transcribe", "translate"}}
            details = {key: value for key, value in (item.stage_details or {}).items()
                       if key not in {"download", "transcribe", "translate"}}
            media.update_batch_item(batch_id, item_id, stage_jobs=kept, stage_details=details, result={},
                                    stage="download", progress=0, message="重新下载抖音正片")
            batch, item = batch_item(batch_id, item_id)
        from app import workbench_cache as cache
        cache.initialize()
        if not cache.media_ready(item.source_value):
            reason = ""
            if isinstance(item.error, dict):
                reason = item.error.get("refresh_reason") or desktop_sources.refresh_reason(
                    desktop_sources.SourceError(item.error.get("code") or item.error.get("stage") or "", item.message))
            if not reason:
                reason = desktop_sources.refresh_reason(
                    desktop_sources.SourceError("", item.message)) or "no_media"
            try:
                info = dict(desktop_sources.probe(item.source_value, item.source_kind, session_id, refresh=True))
                info["refresh_reason"] = reason
                try:
                    cookies = desktop_sources.cookies_for(item.source_value, session_id)
                except desktop_sources.SourceError:
                    cookies = desktop_sources.cookies_for(item.source_value, "")
                    reason = reason or "login"
                    info["refresh_reason"] = reason
                DOWNLOAD_CONTEXTS[batch_id, item_id] = (info, cookies)
                kept = dict(item.result or {})
                kept["refresh_reason"] = reason
                if info.get("resolved_fetch_url"):
                    kept["resolved_fetch_url"] = info["resolved_fetch_url"]
                media.update_batch_item(batch_id, item_id, result=kept)
            except desktop_sources.SourceError as error:
                kept_reason = desktop_sources.refresh_reason(error) or reason or "no_media"
                media.update_batch_item(
                    batch_id, item_id,
                    error={"stage": item.stage, "message": str(error), "refresh_reason": kept_reason},
                )
                raise HTTPException(400, str(error)) from error
            finally:
                if session_id:
                    desktop_sources.forget_session(session_id)
        elif session_id:
            desktop_sources.forget_session(session_id)
        updated = media.update_batch_item(batch_id, item_id, status="queued", message="等待重试", clear_error=True)
        enqueue(batch, item_id)
    return updated
