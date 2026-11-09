
"""Run the existing media stages directly and checkpoint their artifacts."""
from pathlib import Path
import threading

from fastapi import HTTPException

from app import knowledge
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


def batch_item(batch_id, item_id):
    batch = media.load_batch(batch_id)
    item = next((item for item in batch.items if item.item_id == item_id), None)
    if item is None:
        raise FileNotFoundError(item_id)
    return batch, item


def stage_result(batch_id, item_id, stage, payload, transcript_id=None):
    _, item = batch_item(batch_id, item_id)
    payload = {**payload, "operator_batch_id": batch_id, "operator_item_id": item_id}
    previous_id = item.stage_jobs.get(stage)
    if previous_id:
        try:
            previous = media.load_state(previous_id)
            if previous.status == "succeeded" and (stage == "bilibili_upload" or all(
                previous.request.get(key) == value for key, value in payload.items()
            )):
                result = previous.result or {}
                if stage in OUTPUTS:
                    media.resolve_local_artifact_from_url(result[OUTPUTS[stage]])
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


def run_item(batch_id, item_id):
    stage = "download"
    result = {}
    try:
        batch, item = batch_item(batch_id, item_id)
        settings = media.batch_item_settings(batch.request, item)
        knowledge_only = bool(batch.request.get("knowledge_only"))
        output_name = item.output_name or f"source{item.index}"
        language = settings.get("source_language") or "auto"
        model = settings.get("whisper_model") or media.WHISPER_MODEL
        inference = settings.get("whisper_inference_mode") or media.WHISPER_INFERENCE_MODE
        mode = settings.get("subtitle_output_mode") or "en_only"

        def run(name, payload, transcript_id=None):
            nonlocal stage
            stage = name
            result.update(stage_result(batch_id, item_id, name, payload, transcript_id))
            media.update_batch_item(batch_id, item_id, result={**result, "output_name": output_name})

        run("download", {
            "source_kind": item.source_kind, "source_value": item.source_value, "rights_confirmed": True,
            "resolution": settings.get("resolution"), "fps": settings.get("fps"),
            "title": Path(item.source_value).stem if item.source_kind == "local" else item.source_value,
            "audio_only": knowledge_only and item.source_kind == "youtube",
        })
        cache_key = knowledge.transcription_key(item.source_kind, item.source_value, language, model, inference)
        explicit_transcripts = batch.request.get("transcript_ids") or {}
        transcript_id = explicit_transcripts.get(item.client_row_id) or knowledge.cached_id(cache_key)
        if explicit_transcripts.get(item.client_row_id):
            transcript = knowledge.read_transcript(transcript_id)
            if transcript["source"] != item.source_value or transcript["source_kind"] != item.source_kind:
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
                    title=str(result.get("title") or output_name), playable=source_path, cache_key=cache_key,
                )
        except ValueError:
            if knowledge_only:
                raise
        if transcript_id:
            result["transcript_id"] = transcript_id

        if not knowledge_only:
            if mode != "en_only":
                run("translate", {
                    "english_srt_url": result["english_srt_url"],
                    **{key: settings[key] for key in (
                        "target_lang", "translate_model", "subtitle_output_mode", "translation_context_profile_id",
                        "translation_context_note", "translation_glossary",
                    ) if key in settings},
                })
            run("burn", {
                "source_video_url": result["source_video_url"], "english_srt_url": result["english_srt_url"],
                "bilingual_srt_url": result.get("bilingual_srt_url", result["english_srt_url"]),
                "output_name": output_name,
                **{key: settings[key] for key in (
                    "aspect_ratio", "subtitle_font_size", "subtitle_color", "subtitle_outline_color",
                    "subtitle_position", "subtitle_margin", "subtitle_output_mode", "subtitle_style",
                ) if key in settings},
            })
            upload = media.BilibiliUploadSettings.model_validate(settings.get("bilibili_upload") or {})
            if upload.enabled:
                run("bilibili_upload", {
                    "final_video_url": result["final_video_url"], "original_source": item.source_value,
                    "output_name": output_name, "original_title": result.get("title", output_name),
                    "upload_settings": upload.model_dump(),
                })
        media.update_batch_item(batch_id, item_id, status="succeeded", stage="done", progress=100,
                                message="已完成", result={**result, "output_name": output_name}, clear_error=True)
    except Exception as error:
        message = str(error)
        media.update_batch_item(batch_id, item_id, status="failed", stage=stage, message=message,
                                result=result or None, error={"stage": stage, "message": message})


def enqueue(batch, item_id):
    slots = BATCH_SLOTS.setdefault(batch.batch_id, threading.BoundedSemaphore(batch.request["batch_concurrency"]))

    def work():
        with slots:
            run_item(batch.batch_id, item_id)

    media.batch_executor.submit(work)


def submit_desktop_batch(request):
    if any(source.source_kind == "youtube" and not media.is_youtube_url(source.source_value)
           for source in request.sources):
        raise HTTPException(400, "请输入有效的 YouTube 链接")
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
            if upload.enabled and not media.bilibili_configured():
                raise HTTPException(400, "请先在设置中配置 B 站投稿凭据")
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


def retry(batch_id, item_id, confirmed):
    with media.batch_lock:
        batch, item = batch_item(batch_id, item_id)
        if item.status != "failed":
            raise HTTPException(409, "任务当前无法重试")
        if item.stage == "bilibili_upload" and not confirmed:
            raise HTTPException(409, "请先到 B 站核对稿件状态，再确认重试")
        updated = media.update_batch_item(batch_id, item_id, status="queued", message="等待重试", clear_error=True)
        enqueue(batch, item_id)
    return updated
