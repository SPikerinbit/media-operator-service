
"""Desktop-only HTTP endpoints for the two workspaces."""
import os
from pathlib import Path
import shutil
import tempfile
import threading
import subprocess
import sys
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import desktop_config as config, desktop_gpu as gpu, desktop_jobs as jobs, desktop_models, knowledge, obsidian
from app import main as media

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
         "title": Path(batch.items[0].source_value).name if batch.items else ""}
        for batch in jobs.stored_batches() if bool(batch.request.get("knowledge_only")) == knowledge_only
    ]


class Retry(BaseModel):
    upload_checked: bool = False


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
        return jobs.retry(batch_id, item_id, request.upload_checked)
    except FileNotFoundError as error:
        raise HTTPException(404, "找不到任务") from error


class ImportRequest(BaseModel):
    kind: media.SourceKind
    source: str = Field(min_length=1)
    rights_confirmed: bool = False
    language: str = Field(default="auto", pattern=r"^(auto|[a-z]{2,3})$")


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
                    path, source_kind="subtitle", source=source, title=path.stem,
                )}
        batch = jobs.submit_desktop_batch(media.BatchCreateRequest(
            sources=[media.SourceInput(source_kind=request.kind, source_value=source)],
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
    data["playable"] = bool(playable and Path(playable).is_file())
    return data


@router.get("/knowledge/{transcript_id}/media")
def get_media(transcript_id: int):
    data = transcript_or_404(transcript_id)
    if not data["playable"] or not Path(data["playable"]).is_file():
        raise HTTPException(404, "音视频文件已移动或不可用")
    return FileResponse(data["playable"])


class Consent(BaseModel):
    send_subtitles: bool = False


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
        return {"added": knowledge.generate_cards(transcript_id, media.TRANSLATE_API_KEY, model)}
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
        "version": "0.2.0-preview",
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
