
"""Desktop-only HTTP endpoints for the two workspaces."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import subprocess
import sys
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app import desktop_config as config, desktop_gpu as gpu, desktop_jobs as jobs, desktop_models, knowledge, obsidian
from app import main as media
from app.version import VERSION
from app import desktop_sources, share_text, site_profiles

router = APIRouter(prefix="/desktop")
GENERATING = set()
GENERATING_LOCK = threading.Lock()


def sync_credentials():
    for name, value in config.credentials().items():
        setattr(media, name, value)


class Preferences(BaseModel):
    data_dir: str | None = None
    obsidian_vault: str | None = None
    ai_model: str | None = Field(default=None, min_length=1, max_length=120)
    gpu_enabled: bool | None = None
    secrets: dict[str, str | None] = Field(default_factory=dict)


@router.get("/settings")
def settings():
    preferences = config.settings()
    keys = config.credentials()
    gpu_path = config.gpu_dir(media.DATA_DIR)
    return {
        "data_dir": str(config.data_dir()),
        "active_data_dir": str(media.DATA_DIR),
        "obsidian_vault": preferences.get("obsidian_vault", ""),
        "ai_model": preferences.get("ai_model", media.TRANSLATE_MODEL),
        "has_ai_key": bool(keys["TRANSLATE_API_KEY"]),
        "has_bilibili_credentials": media.bilibili_configured(),
        "gpu_enabled": bool(preferences.get("gpu_enabled")),
        "gpu_ready": config.gpu_ready(gpu_path),
        "gpu_install_dir": str(gpu_path.parent),
        "gpu": dict(gpu.PROGRESS),
        "site_logins": site_profiles.status_all()["sites"],
    }


@router.put("/settings")
def save_settings(preferences: Preferences):
    try:
        changes = preferences.model_dump(exclude_none=True, exclude={"secrets"})
        if changes.get("obsidian_vault"):
            changes["obsidian_vault"] = str(obsidian.vault_root(changes["obsidian_vault"]))
        config.update(changes, preferences.secrets)
        sync_credentials()
        if "ai_model" in changes:
            media.TRANSLATE_MODEL = changes["ai_model"]
    except config.CredentialError as error:
        raise HTTPException(503, str(error)) from error
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error
    return settings()


@router.post("/deepseek/test")
def test_deepseek():
    key = config.credentials().get("TRANSLATE_API_KEY") or ""
    if not key:
        raise HTTPException(400, "还没有 DeepSeek 密钥")
    model = config.settings().get("ai_model") or media.TRANSLATE_MODEL
    try:
        import httpx
        response = httpx.post(
            "https://api.deepseek.com/chat/completions",
            timeout=20,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]},
        )
    except Exception as error:
        raise HTTPException(502, "无法连接 DeepSeek") from error
    if response.status_code != 200:
        raise HTTPException(502, "DeepSeek 没有接受这个密钥")
    return {"ok": True, "model": model}


class OutputDefaults(BaseModel):
    source_language: str = Field(default="auto", pattern=r"^(auto|[a-z]{2,3})$")
    target_lang: str = Field(default="zh-CN", max_length=80)
    whisper_model: str = "small"
    whisper_inference_mode: media.WhisperInferenceMode = "auto"
    subtitle_output_mode: media.SubtitleOutputMode = "en_only"
    burn_encoder: media.BurnEncoder = "auto"
    aspect_ratio: media.AspectRatio = "source"
    resolution: media.Resolution = "best"
    fps: media.Fps = "source"
    output_name_mode: media.OutputNameMode = "sequence"
    output_name_prefix: str = Field(default="", max_length=255)

    @field_validator("whisper_model")
    @classmethod
    def supported_model(cls, name):
        if name not in desktop_models.MODELS:
            raise ValueError("不支持的 Whisper 模型")
        return name


class VideoDefaults(BaseModel):
    output: OutputDefaults | None = None
    subtitle_style: media.SubtitleStyle | None = None


@router.get("/video-defaults")
def video_defaults():
    preferences = config.settings()
    return {"output": preferences.get("video_output_defaults"),
            "subtitle_style": preferences.get("video_subtitle_style_defaults")}


@router.put("/video-defaults")
def save_video_defaults(defaults: VideoDefaults):
    changes = {}
    if defaults.output is not None:
        changes["video_output_defaults"] = defaults.output.model_dump()
    if defaults.subtitle_style is not None:
        changes["video_subtitle_style_defaults"] = defaults.subtitle_style.model_dump()
    if changes:
        try:
            config.update(changes, {})
        except OSError as error:
            raise HTTPException(400, "无法写入默认值，请检查设置目录") from error
    return video_defaults()


class GpuInstall(BaseModel):
    directory: str = Field(min_length=1)


@router.post("/gpu")
def prepare_gpu(request: GpuInstall):
    try:
        gpu.install(Path(request.directory))
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from error
    return settings()


@router.get("/resources")
def resources():
    return {"models": [desktop_models.status(media.DATA_DIR, name) for name in desktop_models.MODELS]}


@router.get("/fonts/{filename}")
def bundled_font(filename: str):
    if filename not in {"SourceHanSansCN-Regular.otf", "SourceHanSansCN-Bold.otf",
                        "SourceHanSerifCN-Regular.otf", "SourceHanSerifCN-Bold.otf"}:
        raise HTTPException(404, "找不到字体")
    directory = os.getenv("MEDIA_BUNDLED_FONTS")
    path = Path(directory) / filename if directory else None
    if not path or not path.is_file():
        raise HTTPException(404, "找不到字体")
    return FileResponse(path, media_type="font/otf")


@router.post("/resources/models/{name}")
def prepare_model(name: str):
    try:
        desktop_models.prepare(media.DATA_DIR, name, media.online_media_proxy("https://huggingface.co/"))
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error
    return resources()


@router.get("/resources/check")
def check_resources():
    def check(command, expected=None, env=None):
        try:
            result = subprocess.run(command, capture_output=True, timeout=15,
                                    creationflags=media.WINDOW_FLAGS, cwd=media.ROOT_DIR, env=env)
            return result.returncode == 0 and (expected is None or expected in result.stdout)
        except (OSError, subprocess.TimeoutExpired):
            return False

    tools = [
        {"label": "FFmpeg / 字幕压制", "ready": check([media.FFMPEG_BIN, "-hide_banner", "-filters"], b" ass ")},
        {"label": "NVIDIA NVENC / GPU 视频编码", "ready": media.ffmpeg_nvenc_available()},
        {"label": "ffprobe / 媒体检测", "ready": check([media.FFPROBE_BIN, "-version"])},
        {"label": "yt-dlp / 在线素材", "ready": check([media.YT_DLP_BIN, "--ignore-config", "--version"])},
        {"label": "Deno / YouTube 脚本", "ready": check([str(Path(media.YT_DLP_BIN).with_name("deno.exe")), "--version"])},
        {"label": "WebView2 / 桌面界面", "ready": True},
        {"label": "思源字幕字体", "ready": all(
            (Path(os.getenv("MEDIA_BUNDLED_FONTS", "")) / f"{family}-{weight}.otf").is_file()
            for family in ("SourceHanSansCN", "SourceHanSerifCN") for weight in ("Light", "Regular", "Bold")
        )},
    ]
    env = config.worker_environment(enable_gpu=True)
    worker = ([str(Path(sys.executable).with_name("MediaWhisper.exe"))] if getattr(sys, "frozen", False)
              else [sys.executable, "-m", "app.whisper_worker"])
    tools.append({"label": "NVIDIA / CUDA、cuDNN 和 GPU 推理",
                  "ready": env["WHISPER_DEVICE"] == "cuda" and check([*worker, "--check-gpu"], b"CUDA_READY", env)})
    writable = False
    try:
        with tempfile.TemporaryFile(dir=media.DATA_DIR):
            writable = True
    except OSError:
        pass
    tools.append({"label": "资料目录写入", "ready": writable})
    return {**resources(), "checks": tools, "free_bytes": shutil.disk_usage(media.DATA_DIR).free}


@router.get("/batches")
def history(knowledge_only: bool = False):
    return [
        {"batch_id": batch.batch_id, "created_at": batch.created_at, "status": batch.status,
         "total": batch.total}
        for batch in jobs.stored_batches() if bool(batch.request.get("knowledge_only")) == knowledge_only
    ]


@router.post("/source-title")
def get_source_title(request: media.SourceInput):
    source = request.source_value
    if request.source_kind == "local":
        return {"title": media.source_display_title("local", source)}
    if media.video_url_kind(source) != request.source_kind:
        raise HTTPException(400, "请输入有效的 YouTube 或 B 站链接")
    try:
        metadata = media.load_youtube_preview_metadata(source)
        return {"title": media.source_display_title(request.source_kind, source, str(metadata.get("title") or ""))}
    except (OSError, RuntimeError, ValueError):
        return {"title": ""}


@router.post("/sources/probe")
def probe_source(request: media.SourceInput, refresh: bool = False):
    try:
        info = desktop_sources.probe(request.source_value, request.source_kind, request.session_id, refresh=refresh)
        payload = {"ready": True, **{key: info.get(key) for key in
                   ("title", "platform", "media_type", "duration", "has_audio", "audio_direct")},
                   "description": str(info.get("description") or "")[:5000]}
        if info.get("author"):
            payload["author"] = info["author"]
        if info.get("canonical_url"):
            payload["canonical_url"] = info["canonical_url"]
        if info.get("body"):
            payload["body"] = str(info["body"])[:20000]
        return payload
    except desktop_sources.SourceError as error:
        return {"ready": False, "code": error.code, "message": str(error)}


class ShareText(BaseModel):
    text: str = Field(min_length=1, max_length=100000)


@router.post("/sources/parse")
def parse_sources(request: ShareText):
    return {"items": share_text.parse(request.text)}


@router.post("/sources/classify")
def classify_sources(request: ShareText):
    return {"items": share_text.classify_letters(request.text)}


@router.get("/sites")
def site_status():
    return site_profiles.status_all()


@router.get("/sites/{site}")
def one_site(site: str):
    try:
        return site_profiles.status(site)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.post("/sites/{site}/login")
def start_site_login(site: str):
    try:
        return site_profiles.start_login(site)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from error


@router.delete("/sites/{site}")
def site_logout(site: str):
    try:
        return site_profiles.logout(site)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.post("/sources/session")
def source_session(source: str = Form(), file: UploadFile = File()):
    try:
        return {"session_id": desktop_sources.register_session(source, file.file.read(512 * 1024 + 1))}
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error
    finally:
        file.file.close()


@router.delete("/sources/session/{session_id}")
def delete_source_session(session_id: str):
    desktop_sources.forget_session(session_id)
    return {"ok": True}


@router.post("/batches/preflight")
def batch_preflight(request: media.BatchCreateRequest):
    return jobs.plan_batch(request)


class Retry(BaseModel):
    upload_checked: bool = False
    session_id: str = ""


class BatchUpload(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=300)
    upload_checked: bool = False
    use_current_settings: bool = False
    upload_settings: media.BilibiliUploadSettings | None = None


@router.get("/batches/{batch_id}/upload-candidates")
def upload_candidates(batch_id: str):
    try:
        return jobs.upload_candidates(batch_id)
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到批次") from error


@router.post("/batches/{batch_id}/upload")
def upload_batch(batch_id: str, request: BatchUpload):
    try:
        defaults = request.upload_settings
        if defaults is not None:
            defaults = media.BilibiliUploadSettings.model_validate({**defaults.model_dump(), "enabled": True})
        return jobs.queue_history_uploads(
            batch_id, request.item_ids, request.upload_checked, defaults, request.use_current_settings,
        )
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到批次或任务") from error
    except ValueError as error:
        raise HTTPException(400, "投稿参数无效，请检查原任务参数或当前投稿设置") from error


@router.post("/batches/{batch_id}/{item_id}/retry")
def retry(batch_id: str, item_id: str, request: Retry):
    try:
        return jobs.retry(batch_id, item_id, request.upload_checked, request.session_id)
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到任务") from error


class ImportRequest(BaseModel):
    kind: media.SourceKind
    source: str = Field(min_length=1)
    rights_confirmed: bool = False
    language: str = Field(default="auto", pattern=r"^(auto|[a-z]{2,3})$")
    allow_muxed_audio: bool = False
    session_id: str = ""


@router.post("/knowledge/import")
def import_source(request: ImportRequest):
    if not request.rights_confirmed:
        raise HTTPException(400, "请确认素材可用于本次处理")
    try:
        source = request.source.strip()
        if request.kind == "local":
            path = media.normalize_local_source_path(source)
            source = str(path)
            if path.suffix.lower() in {".srt", ".vtt"}:
                return {"transcript_id": knowledge.register(
                    path, source_kind="subtitle", source=source, title=path.name,
                )}
        batch = jobs.submit_desktop_batch(media.BatchCreateRequest(
            sources=[media.SourceInput(source_kind=request.kind, source_value=source, client_row_id="knowledge",
                                       stop_after="transcribe", allow_muxed_audio=request.allow_muxed_audio,
                                       session_id=request.session_id, allow_unknown_audio=True)],
            rights_confirmed=True, knowledge_only=True, source_language=request.language,
            subtitle_output_mode="en_only", batch_concurrency=1, whisper_inference_mode="auto",
        ))
        return {"batch_id": batch.batch_id}
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error


@router.get("/knowledge")
def list_knowledge(q: str = ""):
    return knowledge.list_transcripts(q)


def transcript_or_404(transcript_id):
    try:
        return knowledge.read_transcript(transcript_id)
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到字幕") from error


@router.get("/knowledge/{transcript_id}")
def transcript(transcript_id: int):
    data = transcript_or_404(transcript_id)
    playable = data.pop("playable")
    data.pop("cache_key")
    data.pop("digest")
    body = data.pop("note_body", None) or ""
    raw_images = data.pop("note_images", None) or "[]"
    try:
        images = json.loads(raw_images) if isinstance(raw_images, str) else list(raw_images or [])
    except (TypeError, ValueError):
        images = []
    data["body"] = body
    data["images"] = [f"/desktop/knowledge/{transcript_id}/images/{index}" for index, _ in enumerate(images, 1)]
    data["playable"] = bool(playable and Path(playable).is_file())
    if data["playable"] and not data.get("asset_type"):
        try:
            data["asset_type"] = desktop_sources.inspect_file(playable)["media_type"]
        except (ValueError, OSError, subprocess.SubprocessError):
            pass
    return data


@router.get("/knowledge/{transcript_id}/images/{index}")
def note_image(transcript_id: int, index: int):
    try:
        path = knowledge.note_image(transcript_id, index)
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到图片") from error
    kinds = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
    return FileResponse(path, media_type=kinds.get(path.suffix.lower(), "application/octet-stream"))


@router.get("/knowledge/{transcript_id}/media")
def get_media(transcript_id: int):
    data = transcript_or_404(transcript_id)
    if not data["playable"] or not Path(data["playable"]).is_file():
        raise HTTPException(404, "音视频文件已移动或不可用")
    return FileResponse(data["playable"])


class Consent(BaseModel):
    send_subtitles: bool = False
    mode: Literal["curated", "comprehensive"] = "curated"


@router.post("/knowledge/{transcript_id}/generate")
def generate(transcript_id: int, consent: Consent):
    if not consent.send_subtitles:
        raise HTTPException(400, "请确认发送所选素材的字幕给 DeepSeek")
    if not media.TRANSLATE_API_KEY:
        raise HTTPException(400, "请先在设置中配置 DeepSeek API Key")
    transcript_or_404(transcript_id)
    with GENERATING_LOCK:
        if transcript_id in GENERATING:
            raise HTTPException(409, "这份字幕正在提取观点")
        GENERATING.add(transcript_id)
    try:
        model = config.settings().get("ai_model", media.TRANSLATE_MODEL)
        return {"added": knowledge.generate_cards(transcript_id, media.TRANSLATE_API_KEY, model, consent.mode)}
    except Exception as error:
        raise HTTPException(502, "DeepSeek 请求失败或返回的引用无效，请检查模型配置后重试。") from error
    finally:
        with GENERATING_LOCK:
            GENERATING.discard(transcript_id)


@router.put("/knowledge/{transcript_id}/cards/{card_id}")
def edit_card(transcript_id: int, card_id: int, request: knowledge.CardText):
    if not request.claim.strip():
        raise HTTPException(400, "主张不能为空")
    try:
        knowledge.update_card(transcript_id, card_id, request)
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到观点卡") from error
    return transcript(transcript_id)


class PublishRequest(BaseModel):
    card_ids: list[int] = Field(min_length=1, max_length=300)
    new_version: bool = False


def configured_vault():
    try:
        return obsidian.vault_root(config.settings().get("obsidian_vault", ""))
    except (OSError, ValueError) as error:
        raise HTTPException(400, "请先在设置中选择可用的 Obsidian Vault") from error


@router.post("/knowledge/{transcript_id}/publish")
def publish_cards(transcript_id: int, request: PublishRequest):
    vault = configured_vault()
    try:
        return {"results": obsidian.publish(vault, transcript_id, request.card_ids, request.new_version)}
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到字幕") from error


@router.post("/obsidian/{publication_id}/open")
def open_obsidian_note(publication_id: str):
    vault = configured_vault()
    try:
        uri = obsidian.note_uri(vault, publication_id)
    except (OSError, ValueError) as error:
        raise HTTPException(404, f"找不到已发布笔记。可在 Obsidian 中搜索发布 ID {publication_id}") from error
    try:
        os.startfile(uri)
    except OSError as error:
        raise HTTPException(409, "Windows 无法打开 Obsidian。笔记仍保存在 Vault 中。") from error
    return {"opened": True}


class Export(BaseModel):
    destination: str = Field(min_length=1)
    artifact_url: str | None = None
    transcript_id: int | None = None
    format: Literal["artifact", "markdown", "srt", "diagnostics"]


def diagnostics():
    return {
        "application": "Media Operator Desktop",
        "version": VERSION,
        "platform": os.name,
        "ffmpeg_available": Path(media.FFMPEG_BIN).is_file(),
        "yt_dlp_available": Path(media.YT_DLP_BIN).is_file(),
        "nvidia_runtime_available": (config.gpu_dir(media.DATA_DIR) / ".ready").is_file(),
        "batch_states": [batch.status for batch in jobs.stored_batches()],
    }


@router.post("/export")
def export(request: Export):
    destination = Path(request.destination)
    if not destination.is_absolute() or not destination.parent.is_dir():
        raise HTTPException(400, "请选择可写入的导出目录")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
        if request.format == "artifact":
            if not request.artifact_url:
                raise ValueError("缺少要导出的文件")
            _, source = media.resolve_local_artifact_from_url(request.artifact_url)
            if source.suffix.lower() not in {".mp4", ".srt"}:
                raise ValueError("只支持导出视频和字幕")
            shutil.copyfile(source, temporary)
        elif request.format == "diagnostics":
            media.write_json(temporary, diagnostics())
        elif request.transcript_id is None:
            raise ValueError("请选择字幕")
        elif request.format == "srt":
            knowledge.subtitle_file(request.transcript_id, temporary)
        else:
            temporary.write_text(knowledge.markdown(request.transcript_id), encoding="utf-8")
        temporary.replace(destination)
        return {"saved": True}
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
