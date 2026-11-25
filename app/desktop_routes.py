
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
import httpx

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
    saved = config.settings()
    if saved.get("ai_api_base"):
        media.TRANSLATE_API_BASE = saved["ai_api_base"]
    if saved.get("ai_model"):
        media.TRANSLATE_MODEL = saved["ai_model"]


class Preferences(BaseModel):
    data_dir: str | None = None
    obsidian_vault: str | None = None
    obsidian_viewpoint_vault: str | None = None
    obsidian_summary_vault: str | None = None
    ai_model: str | None = Field(default=None, min_length=1, max_length=120)
    ai_api_base: str | None = Field(default=None, max_length=300)
    gpu_enabled: bool | None = None
    onboarding_complete: bool | None = None
    secrets: dict[str, str | None] = Field(default_factory=dict)


def _normalize_ai_api_base(value: str) -> str:
    clean = value.strip().rstrip("/")
    if not clean:
        return "https://api.deepseek.com"
    from urllib.parse import urlsplit
    parsed = urlsplit(clean)
    if parsed.scheme == "https" and parsed.netloc:
        return clean
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return clean
    raise ValueError("API 地址需使用 https://，本地模型服务可使用 http://127.0.0.1 或 http://localhost")


@router.get("/settings")
def settings():
    preferences = config.settings()
    keys = config.credentials()
    gpu_path = config.gpu_dir(media.DATA_DIR)
    viewpoint_vault = preferences.get("obsidian_viewpoint_vault") or preferences.get("obsidian_vault", "")
    summary_vault = preferences.get("obsidian_summary_vault", "")
    return {
        "data_dir": str(config.data_dir()),
        "active_data_dir": str(media.DATA_DIR),
        "log_dir": str(config.HOME),
        "obsidian_vault": viewpoint_vault,
        "obsidian_viewpoint_vault": viewpoint_vault,
        "obsidian_summary_vault": summary_vault,
        "ai_model": preferences.get("ai_model", media.TRANSLATE_MODEL),
        "ai_api_base": preferences.get("ai_api_base") or media.TRANSLATE_API_BASE or "https://api.deepseek.com",
        "has_ai_key": bool(keys["TRANSLATE_API_KEY"]),
        "has_bilibili_credentials": media.bilibili_configured(),
        "gpu_enabled": bool(preferences.get("gpu_enabled")),
        "onboarding_complete": bool(preferences.get("onboarding_complete")),
        "gpu_ready": config.gpu_ready(gpu_path),
        "gpu_install_dir": str(gpu_path.parent),
        "gpu": dict(gpu.PROGRESS),
        "site_logins": site_profiles.status_all()["sites"],
        "version": VERSION,
    }


@router.put("/settings")
def save_settings(preferences: Preferences):
    try:
        changes = preferences.model_dump(exclude_none=True, exclude={"secrets"})
        if "ai_api_base" in changes:
            changes["ai_api_base"] = _normalize_ai_api_base(changes["ai_api_base"])
        if "obsidian_viewpoint_vault" in changes:
            if changes["obsidian_viewpoint_vault"]:
                changes["obsidian_viewpoint_vault"] = str(obsidian.vault_root(changes["obsidian_viewpoint_vault"]))
            changes["obsidian_vault"] = changes["obsidian_viewpoint_vault"]
        elif "obsidian_vault" in changes:
            if changes["obsidian_vault"]:
                changes["obsidian_vault"] = str(obsidian.vault_root(changes["obsidian_vault"]))
            changes["obsidian_viewpoint_vault"] = changes["obsidian_vault"]
        if changes.get("obsidian_summary_vault"):
            changes["obsidian_summary_vault"] = str(obsidian.vault_root(changes["obsidian_summary_vault"]))
        config.update(changes, preferences.secrets)
        sync_credentials()
        if "ai_model" in changes:
            media.TRANSLATE_MODEL = changes["ai_model"]
        if "ai_api_base" in changes:
            media.TRANSLATE_API_BASE = changes["ai_api_base"]
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
        from app.note_engine import _endpoint_url
        response = httpx.post(
            _endpoint_url(),
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
    from app import gpu_queue
    return {
        "models": [desktop_models.status(media.DATA_DIR, name) for name in desktop_models.MODELS],
        "gpu_queue": gpu_queue.snapshot(),
    }


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


@router.delete("/resources/models/{name}")
def delete_model(name: str):
    busy = any(batch.queued or batch.running for batch in jobs.stored_batches())
    if busy:
        raise HTTPException(409, "当前有任务正在运行，请等待结束后再删除模型")
    try:
        freed = desktop_models.remove_model(media.DATA_DIR, name)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from error
    return {**resources(), "freed_bytes": freed}


def _dir_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def _storage_snapshot():
    root = media.DATA_DIR
    models_bytes = _dir_bytes(root / "models")
    jobs_bytes = _dir_bytes(root / "jobs")
    previews_bytes = _dir_bytes(root / "previews") + _dir_bytes(root / "tmp") + _dir_bytes(root / "covers")
    db_bytes = sum(_dir_bytes(p) for p in root.glob("*.sqlite3*"))
    free_bytes = shutil.disk_usage(root).free if root.exists() else 0
    return {
        "data_dir": str(root),
        "log_dir": str(config.HOME),
        "models_bytes": models_bytes,
        "jobs_bytes": jobs_bytes,
        "cleanable_bytes": previews_bytes,
        "database_bytes": db_bytes,
        "total_bytes": models_bytes + jobs_bytes + previews_bytes + db_bytes,
        "free_bytes": free_bytes,
    }


@router.get("/storage")
def storage_info():
    return _storage_snapshot()


@router.post("/storage/clean-cache")
def clean_storage_cache():
    busy = any(batch.queued or batch.running for batch in jobs.stored_batches())
    if busy or desktop_models.is_running():
        raise HTTPException(409, "有任务或模型下载正在进行，请稍后再清理缓存")
    root = media.DATA_DIR.resolve()
    freed = 0
    for folder_name in ("previews", "tmp", "covers"):
        folder = (root / folder_name).resolve()
        if root not in folder.parents or not folder.is_dir():
            continue
        for child in list(folder.iterdir()):
            size = _dir_bytes(child)
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                freed += size
            except OSError:
                pass
    return {"freed_bytes": freed, "storage": _storage_snapshot()}


class OpenPathRequest(BaseModel):
    target: Literal["data_dir", "log_dir", "obsidian_vault", "obsidian_viewpoint_vault", "obsidian_summary_vault", "artifact"]
    artifact_url: str | None = None


@router.post("/open-path")
def open_local_path(req: OpenPathRequest):
    reveal_file = False
    if req.target == "data_dir":
        path = media.DATA_DIR.resolve()
    elif req.target == "log_dir":
        path = config.HOME.resolve()
    elif req.target in {"obsidian_vault", "obsidian_viewpoint_vault"}:
        path = configured_vault("viewpoint").resolve()
    elif req.target == "obsidian_summary_vault":
        path = configured_vault("summary").resolve()
    else:
        if not req.artifact_url:
            raise HTTPException(400, "缺少要打开的产物地址")
        try:
            _, path = media.resolve_local_artifact_from_url(req.artifact_url)
            path = path.resolve()
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        reveal_file = True
    if not path.exists():
        raise HTTPException(404, "目标路径不存在")
    if os.name == "nt":
        try:
            if reveal_file and path.is_file():
                subprocess.Popen(["explorer.exe", f"/select,{path}"])
            else:
                os.startfile(str(path))
        except OSError as error:
            raise HTTPException(500, f"无法打开资源管理器：{error}") from error
    return {"opened": True, "path": str(path)}


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
    proxy_url = media.online_media_proxy("https://www.youtube.com/")
    return {
        **resources(),
        "checks": tools,
        "free_bytes": shutil.disk_usage(media.DATA_DIR).free,
        "proxy": proxy_url or "",
        "storage": _storage_snapshot(),
    }


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
        from app.note_pages import page
        return page(transcript_id)
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到字幕") from error


@router.get("/knowledge/{transcript_id}")
def transcript(
    transcript_id: int,
    cue_after: int = 0,
    card_after: int = 0,
    view_mode: Literal["auto", "summary", "curated", "comprehensive"] = "auto",
):
    from app.note_pages import page
    try:
        data = page(transcript_id, max(0, cue_after), max(0, card_after), view_mode=view_mode)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
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
    mode: Literal["summary", "curated", "comprehensive"] = "curated"
    derive_siblings: bool = True


@router.post("/knowledge/{transcript_id}/generate")
def generate(transcript_id: int, consent: Consent):
    if not consent.send_subtitles:
        raise HTTPException(400, "请确认发送所选素材的字幕给 DeepSeek")
    if not media.TRANSLATE_API_KEY:
        raise HTTPException(400, "请先在设置中配置 DeepSeek API Key")
    transcript_or_404(transcript_id)
    with GENERATING_LOCK:
        if transcript_id in GENERATING:
            raise HTTPException(409, "这份字幕正在整理中")
        GENERATING.add(transcript_id)
    try:
        model = config.settings().get("ai_model", media.TRANSLATE_MODEL)
        added = (
            knowledge.generate_cards(transcript_id, media.TRANSLATE_API_KEY, model, consent.mode)
            if consent.derive_siblings
            else knowledge.generate_cards(
                transcript_id, media.TRANSLATE_API_KEY, model, consent.mode, derive_siblings=False
            )
        )
        return {"added": added}
    except httpx.TimeoutException as error:
        raise HTTPException(504, 'DeepSeek 请求超时，已有观点和编辑已保留，可重试。') from error
    except httpx.HTTPStatusError as error:
        if error.response.status_code in {401, 403}:
            raise HTTPException(502, 'DeepSeek 密钥无效或无访问权限，请到设置更新密钥。') from error
        raise HTTPException(502, 'DeepSeek 服务暂不可用，已有观点和编辑已保留，可稍后重试。') from error
    except Exception as error:
        raise HTTPException(502, "DeepSeek 请求失败或返回的引用无效，请检查模型配置后重试。") from error
    finally:
        with GENERATING_LOCK:
            GENERATING.discard(transcript_id)


@router.post("/knowledge/{transcript_id}/cards")
def add_card(transcript_id: int, request: knowledge.CardText):
    try:
        card_id = knowledge.create_card(transcript_id, request)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    view_mode = request.mode if request.mode in {"curated", "comprehensive"} else "auto"
    return {**transcript(transcript_id, card_after=0, view_mode=view_mode), "created_card_id": card_id}


@router.put("/knowledge/{transcript_id}/cards/{card_id}")
def edit_card(transcript_id: int, card_id: int, request: knowledge.CardText):
    if not request.claim.strip():
        raise HTTPException(400, "主张不能为空")
    try:
        knowledge.update_card(transcript_id, card_id, request)
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到观点卡") from error
    with knowledge.database() as db:
        row = db.execute("SELECT mode FROM card WHERE id=? AND transcript_id=?", (card_id, transcript_id)).fetchone()
    view_mode = row["mode"] if row and row["mode"] in {"curated", "comprehensive"} else "auto"
    return transcript(transcript_id, card_after=max(0, card_id - 1), view_mode=view_mode)


@router.delete("/knowledge/{transcript_id}/cards/{card_id}")
def remove_card(transcript_id: int, card_id: int):
    with knowledge.database() as db:
        row = db.execute("SELECT mode FROM card WHERE id=? AND transcript_id=?", (card_id, transcript_id)).fetchone()
    view_mode = row["mode"] if row and row["mode"] in {"curated", "comprehensive"} else "auto"
    try:
        knowledge.delete_card(transcript_id, card_id)
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到观点卡") from error
    return transcript(transcript_id, card_after=0, view_mode=view_mode)


class TreeNodeEdit(BaseModel):
    title: str = Field(default="", max_length=120)
    summary: str = Field(min_length=1, max_length=4000)


@router.put("/knowledge/{transcript_id}/tree-nodes/{node_id}")
def edit_tree_node(transcript_id: int, node_id: int, request: TreeNodeEdit):
    from app import note_engine
    try:
        updated = note_engine.update_tree_node(transcript_id, node_id, request.title, request.summary)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    return {**transcript(transcript_id, view_mode="summary"), "updated_node": updated}


class PublishRequest(BaseModel):
    card_ids: list[int] = Field(min_length=1, max_length=300)
    new_version: bool = False


class PublishSummaryRequest(BaseModel):
    run_id: str | None = None
    new_version: bool = False


def configured_vault(kind: Literal["viewpoint", "summary"] = "viewpoint"):
    prefs = config.settings()
    if kind == "summary":
        raw = prefs.get("obsidian_summary_vault", "")
        msg = "请先在设置中选择可用的「摘要 Obsidian Vault」"
    else:
        raw = prefs.get("obsidian_viewpoint_vault") or prefs.get("obsidian_vault", "")
        msg = "请先在设置中选择可用的「观点 Obsidian Vault」"
    try:
        return obsidian.vault_root(raw)
    except (OSError, ValueError) as error:
        raise HTTPException(400, msg) from error


def _available_vaults(preferred: Literal["summary", "viewpoint"] | None = None):
    prefs = config.settings()
    order = ("summary", "viewpoint") if preferred == "summary" else ("viewpoint", "summary")
    vaults = []
    for kind in order:
        raw = (
            prefs.get("obsidian_summary_vault", "")
            if kind == "summary"
            else (prefs.get("obsidian_viewpoint_vault") or prefs.get("obsidian_vault", ""))
        )
        if not raw:
            continue
        try:
            vaults.append(obsidian.vault_root(raw))
        except (OSError, ValueError):
            continue
    return vaults


@router.post("/knowledge/{transcript_id}/publish")
def publish_cards(transcript_id: int, request: PublishRequest):
    vault = configured_vault("viewpoint")
    try:
        return {"results": obsidian.publish(vault, transcript_id, request.card_ids, request.new_version)}
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到字幕") from error


@router.post("/knowledge/{transcript_id}/publish-summary")
def publish_summary_tree(transcript_id: int, request: PublishSummaryRequest):
    vault = configured_vault("summary")
    try:
        return {"result": obsidian.publish_summary(vault, transcript_id, request.run_id, request.new_version)}
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到字幕") from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.post("/obsidian/{publication_id}/open")
def open_obsidian_note(publication_id: str, vault_kind: Literal["summary", "viewpoint"] | None = None):
    vaults = _available_vaults(vault_kind)
    if not vaults:
        configured_vault(vault_kind or "viewpoint")
    try:
        uri = obsidian.note_uri_any(vaults, publication_id)
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
    view_mode: Literal["summary", "curated", "comprehensive"] | None = None


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
            from app.note_pages import markdown_to
            markdown_to(request.transcript_id, temporary, view_mode=request.view_mode)
        temporary.replace(destination)
        return {"saved": True}
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class TranslatePageRequest(BaseModel):
    cue_after: int = Field(default=0, ge=0)
    limit: int = Field(default=32, ge=1, le=64)


@router.post("/knowledge/{transcript_id}/translate-page")
def translate_knowledge_page(transcript_id: int, request: TranslatePageRequest):
    if not media.TRANSLATE_API_KEY:
        raise HTTPException(400, "请先在设置中配置 DeepSeek API Key")
    transcript_or_404(transcript_id)
    from app import note_engine, note_pages
    try:
        model = config.settings().get("ai_model", media.TRANSLATE_MODEL)
        translated = note_engine.translate_page(
            transcript_id, media.TRANSLATE_API_KEY, model,
            cue_after=request.cue_after, limit=request.limit,
        )
        page_data = note_pages.page(transcript_id, cue_after=request.cue_after, limit=request.limit)
        return {**page_data, "translated_count": translated}
    except httpx.TimeoutException as error:
        raise HTTPException(504, "DeepSeek 翻译请求超时，可稍后重试。") from error
    except httpx.HTTPStatusError as error:
        if error.response.status_code in {401, 403}:
            raise HTTPException(502, "DeepSeek 密钥无效或无访问权限，请到设置更新密钥。") from error
        raise HTTPException(502, "DeepSeek 翻译服务暂不可用，请稍后重试。") from error
    except Exception as error:
        raise HTTPException(502, f"翻译本页原文失败：{error}") from error


@router.get('/knowledge/{transcript_id}/cards/{card_id}/references')
def note_references(transcript_id: int, card_id: int, after: int = 0):
    from app.note_pages import references
    try:
        return references(transcript_id,card_id,max(0,after))
    except FileNotFoundError as error:
        raise HTTPException(404,str(error)) from error


@router.get('/knowledge/{transcript_id}/tree-nodes/{node_id}/references')
def tree_node_references(transcript_id: int, node_id: int, after: int = 0):
    from app.note_pages import node_references
    try:
        return node_references(transcript_id, node_id, max(0, after))
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error


@router.get('/knowledge/{transcript_id}/candidates/{candidate_id}/references')
def candidate_span_references(transcript_id: int, candidate_id: int, after: int = 0):
    from app.note_pages import candidate_references
    try:
        return candidate_references(transcript_id, candidate_id, max(0, after))
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error


@router.get('/knowledge/{transcript_id}/source/{number}')
def note_source(transcript_id: int, number: int, offset: int = 0):
    from app.note_pages import source_page
    try:
        return source_page(transcript_id,number,max(0,offset))
    except FileNotFoundError as error:
        raise HTTPException(404,str(error)) from error


@router.get('/knowledge/{transcript_id}/run')
def note_run_status(transcript_id: int):
    from app.note_engine import status
    return status(transcript_id)
