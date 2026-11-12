from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import sys
import threading
import time
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlparse
from urllib import request as urllib_request

import httpx
import srt
import numpy as np
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from app.defaults import DEFAULT_TRANSLATE_MODEL
from app.version import VERSION

APP_NAME = "media-operator-service"
DESKTOP = os.getenv("MEDIA_DESKTOP") == "1"
WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if DESKTOP and os.name == "nt" else 0
DEFAULT_TARGET_LANG = "zh-CN"
DEFAULT_YT_DLP_FORMAT = "bestvideo+bestaudio/best"
DEFAULT_WHISPER_MODEL = "small"
DEFAULT_FONT = "Microsoft YaHei"
DEFAULT_FONTS_DIR = os.getenv("SUBTITLE_FONTS_DIR", "/mnt/c/Windows/Fonts")
BUNDLED_FONT_FAMILIES = {"Source Han Sans CN", "Source Han Serif CN"}


def subtitle_fonts_dir(family: str) -> Path:
    bundled = os.getenv("MEDIA_BUNDLED_FONTS")
    if DESKTOP and bundled and family in BUNDLED_FONT_FAMILIES and Path(bundled).is_dir():
        return Path(bundled)
    return Path(DEFAULT_FONTS_DIR)

ROOT_DIR = Path(os.getenv("MEDIA_ROOT_DIR", Path(__file__).resolve().parents[1])).resolve()
DATA_DIR = Path(os.getenv("MEDIA_DATA_DIR", ROOT_DIR / "data")).resolve()
JOBS_DIR = DATA_DIR / "jobs"
BATCHES_DIR = DATA_DIR / "batches"
TRANSLATION_CONTEXTS_PATH = DATA_DIR / "translation_context_profiles.json"
PREVIEW_CACHE_DIR = DATA_DIR / "preview_cache"
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8090").rstrip("/")
WORKER_CONCURRENCY = max(1, int(os.getenv("WORKER_CONCURRENCY", "2")))
BATCH_WORKER_CONCURRENCY = max(1, int(os.getenv("BATCH_WORKER_CONCURRENCY", "2")))
BATCH_WORKER_MAX_CONCURRENCY = max(
    BATCH_WORKER_CONCURRENCY,
    int(os.getenv("BATCH_WORKER_MAX_CONCURRENCY", "5")),
)
ALLOW_PLACEHOLDER_ARTIFACTS = os.getenv("ALLOW_PLACEHOLDER_ARTIFACTS", "false").lower() in {"1", "true", "yes", "on"}
YT_DLP_PROXY = os.getenv("YT_DLP_PROXY", "").strip()
YT_DLP_SOCKET_TIMEOUT = max(1, int(os.getenv("YT_DLP_SOCKET_TIMEOUT", "20")))
YT_DLP_RETRIES = max(0, int(os.getenv("YT_DLP_RETRIES", "3")))
YT_DLP_FRAGMENT_RETRIES = max(0, int(os.getenv("YT_DLP_FRAGMENT_RETRIES", "3")))
PREVIEW_FRAME_TIMEOUT_SECONDS = max(5, int(os.getenv("PREVIEW_FRAME_TIMEOUT_SECONDS", "18")))
PREVIEW_METADATA_TTL_SECONDS = max(60, int(os.getenv("PREVIEW_METADATA_TTL_SECONDS", "600")))
PREVIEW_MAX_HEIGHT = max(144, int(os.getenv("PREVIEW_MAX_HEIGHT", "720")))
PREVIEW_TARGET_HEIGHT = max(144, int(os.getenv("PREVIEW_TARGET_HEIGHT", "360")))
PREVIEW_WINDOW_SECONDS = max(10, int(os.getenv("PREVIEW_WINDOW_SECONDS", "300")))


def resolve_yt_dlp_bin() -> str:
    explicit = os.getenv("YT_DLP_BIN", "").strip()
    if explicit:
        return explicit

    candidates = [
        Path(sys.executable).with_name("yt-dlp"),
        Path(sys.executable).with_name("yt-dlp.exe"),
        Path("yt-dlp"),
        Path("yt-dlp.exe"),
        ROOT_DIR / ".venv-win" / "Scripts" / "yt-dlp.exe",
    ]
    for candidate in candidates:
        if candidate.is_absolute() and candidate.exists():
            return str(candidate)
        if not candidate.is_absolute():
            resolved = shutil.which(str(candidate))
            if resolved:
                return resolved
    return str(candidates[0])


YT_DLP_BIN = resolve_yt_dlp_bin()
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
FFMPEG_BURN_BIN = os.getenv("FFMPEG_BURN_BIN") or FFMPEG_BIN
FFPROBE_BIN = os.getenv("FFPROBE_BIN", "ffprobe")
FFMPEG_BURN_ENCODER = os.getenv("FFMPEG_BURN_ENCODER", "auto").strip().lower()
if FFMPEG_BURN_ENCODER not in {"auto", "cpu", "nvenc"}:
    FFMPEG_BURN_ENCODER = "auto"
FFMPEG_NVENC_PRESET = os.getenv("FFMPEG_NVENC_PRESET", "p5").strip() or "p5"
FFMPEG_NVENC_TUNE = os.getenv("FFMPEG_NVENC_TUNE", "hq").strip() or "hq"
FFMPEG_NVENC_CQ = max(1, min(51, int(os.getenv("FFMPEG_NVENC_CQ", "21"))))
WHISPER_BIN = os.getenv("WHISPER_BIN", "")
WHISPER_BACKEND = os.getenv("WHISPER_BACKEND", "auto").strip().lower()
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto").strip().lower()
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "").strip()
WHISPER_DEVICE_INDEX = int(os.getenv("WHISPER_DEVICE_INDEX", "0"))
WHISPER_CPU_THREADS = max(1, int(os.getenv("WHISPER_CPU_THREADS", "4")))
WHISPER_NUM_WORKERS = max(1, int(os.getenv("WHISPER_NUM_WORKERS", "1")))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", DEFAULT_WHISPER_MODEL)
WHISPER_WORKER_PYTHON = os.getenv("WHISPER_WORKER_PYTHON", "").strip()
WHISPER_WORD_TIMESTAMPS = os.getenv("WHISPER_WORD_TIMESTAMPS", "true").lower() in {"1", "true", "yes", "on"}
WHISPER_VAD_ENABLED = os.getenv("WHISPER_VAD_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
WHISPER_VAD_PADDING_MS = max(0, int(os.getenv("WHISPER_VAD_PADDING_MS", "300")))
WHISPER_BATCHED_INFERENCE = os.getenv("WHISPER_BATCHED_INFERENCE", "true").lower() in {"1", "true", "yes", "on"}
WHISPER_INFERENCE_MODE = os.getenv("WHISPER_INFERENCE_MODE", "standard").strip().lower()
if WHISPER_INFERENCE_MODE not in {"standard", "batched", "auto_repair"}:
    WHISPER_INFERENCE_MODE = "standard"
WHISPER_GAP_THRESHOLD_SECONDS = max(0.5, float(os.getenv("WHISPER_GAP_THRESHOLD_SECONDS", "2.0")))
WHISPER_BATCH_SIZE = max(1, int(os.getenv("WHISPER_BATCH_SIZE", "4")))
WHISPER_BEAM_SIZE = max(1, int(os.getenv("WHISPER_BEAM_SIZE", "5")))
WHISPER_BEST_OF = max(1, int(os.getenv("WHISPER_BEST_OF", "5")))
WHISPER_CONDITION_ON_PREVIOUS_TEXT = os.getenv("WHISPER_CONDITION_ON_PREVIOUS_TEXT", "false").lower() in {"1", "true", "yes", "on"}
WHISPER_COMPRESSION_RATIO_THRESHOLD = float(os.getenv("WHISPER_COMPRESSION_RATIO_THRESHOLD", "2.0"))
WHISPER_LOG_PROB_THRESHOLD = float(os.getenv("WHISPER_LOG_PROB_THRESHOLD", "-0.8"))
WHISPER_NO_SPEECH_THRESHOLD = float(os.getenv("WHISPER_NO_SPEECH_THRESHOLD", "0.55"))
SUBTITLE_TAIL_PADDING_MS = max(0, int(os.getenv("SUBTITLE_TAIL_PADDING_MS", "120")))
SUBTITLE_MAX_DURATION_MS = max(1200, int(os.getenv("SUBTITLE_MAX_DURATION_MS", "5500")))
SUBTITLE_MAX_GAP_MS = max(100, int(os.getenv("SUBTITLE_MAX_GAP_MS", "650")))
SUBTITLE_MAX_CHARS = max(16, int(os.getenv("SUBTITLE_MAX_CHARS", "44")))
SUBTITLE_MAX_CPS = max(6.0, float(os.getenv("SUBTITLE_MAX_CPS", "22")))
SUBTITLE_MIN_DURATION_MS = max(300, int(os.getenv("SUBTITLE_MIN_DURATION_MS", "800")))
SUBTITLE_MERGE_SHORT_CHARS = max(1, int(os.getenv("SUBTITLE_MERGE_SHORT_CHARS", "8")))
SUBTITLE_COHERENCE_MERGE = os.getenv("SUBTITLE_COHERENCE_MERGE", "true").lower() in {"1", "true", "yes", "on"}
SUBTITLE_COHERENCE_MAX_CHARS = max(SUBTITLE_MAX_CHARS, int(os.getenv("SUBTITLE_COHERENCE_MAX_CHARS", "76")))
SUBTITLE_COHERENCE_MAX_DURATION_MS = max(SUBTITLE_MAX_DURATION_MS, int(os.getenv("SUBTITLE_COHERENCE_MAX_DURATION_MS", "7200")))
SUBTITLE_COHERENCE_MAX_GAP_MS = max(0, int(os.getenv("SUBTITLE_COHERENCE_MAX_GAP_MS", "650")))
SUBTITLE_ORPHAN_MAX_CHARS = max(1, int(os.getenv("SUBTITLE_ORPHAN_MAX_CHARS", "18")))
SUBTITLE_REPEAT_TOKEN_LIMIT = max(3, int(os.getenv("SUBTITLE_REPEAT_TOKEN_LIMIT", "8")))
SUBTITLE_DROP_REPEATED_HALLUCINATIONS = os.getenv("SUBTITLE_DROP_REPEATED_HALLUCINATIONS", "false").lower() in {"1", "true", "yes", "on"}
SUBTITLE_REPEAT_HANDLING = os.getenv("SUBTITLE_REPEAT_HANDLING", "compress").strip().lower()
if SUBTITLE_DROP_REPEATED_HALLUCINATIONS:
    SUBTITLE_REPEAT_HANDLING = "drop"
elif SUBTITLE_REPEAT_HANDLING not in {"keep", "compress", "drop"}:
    SUBTITLE_REPEAT_HANDLING = "compress"
SUBTITLE_REPEAT_COMPRESS_TEXT = os.getenv("SUBTITLE_REPEAT_COMPRESS_TEXT", "ha ha ha").strip() or "ha ha ha"
SUBTITLE_REPEAT_MIN_SPAN_MS = max(500, int(os.getenv("SUBTITLE_REPEAT_MIN_SPAN_MS", "2500")))
SUBTITLE_REPEAT_MIN_BLOCKS = max(2, int(os.getenv("SUBTITLE_REPEAT_MIN_BLOCKS", "4")))
TRANSLATE_PROVIDER = os.getenv("TRANSLATE_PROVIDER", "").strip()
TRANSLATE_API_BASE = os.getenv("TRANSLATE_API_BASE", "").strip()
TRANSLATE_API_KEY = os.getenv("TRANSLATE_API_KEY", "").strip()
TRANSLATE_MODEL = os.getenv("TRANSLATE_MODEL", DEFAULT_TRANSLATE_MODEL).strip()
TRANSLATE_PROMPT_CONCURRENCY = max(1, int(os.getenv("TRANSLATE_PROMPT_CONCURRENCY", "8")))
TRANSLATE_PROMPT_SEMAPHORE = threading.BoundedSemaphore(TRANSLATE_PROMPT_CONCURRENCY)
BILI_SESSDATA = os.getenv("BILI_SESSDATA", "").strip()
BILI_JCT = os.getenv("BILI_JCT", "").strip()
BILI_BUVID3 = os.getenv("BILI_BUVID3", "").strip()
BILI_DEDEUSERID = os.getenv("BILI_DEDEUSERID", "").strip()
BILI_AC_TIME_VALUE = os.getenv("BILI_AC_TIME_VALUE", "").strip()
BILI_UPLOAD_CONCURRENCY = max(1, int(os.getenv("BILI_UPLOAD_CONCURRENCY", "1")))
_BILI_UPLOAD_LINE_RAW = os.getenv("BILI_UPLOAD_LINE", "QN").strip() or "QN"
BILI_UPLOAD_LINE = "auto" if _BILI_UPLOAD_LINE_RAW.lower() == "auto" else _BILI_UPLOAD_LINE_RAW.upper()
BILI_UPLOAD_FALLBACK_LINES = [
    item.strip().upper() if item.strip().lower() != "auto" else "auto"
    for item in os.getenv("BILI_UPLOAD_FALLBACK_LINES", "QN,BDA2,WS,auto").split(",")
    if item.strip()
]
BILI_UPLOAD_TIMEOUT_SECONDS = max(300, int(os.getenv("BILI_UPLOAD_TIMEOUT_SECONDS", "7200")))
BILI_PROXY = os.getenv("BILI_PROXY", "").strip()
BILI_UPLOAD_SEMAPHORE = threading.BoundedSemaphore(BILI_UPLOAD_CONCURRENCY)

app = FastAPI(title=APP_NAME, version=VERSION)


def desktop_process() -> bool:
    return os.getenv("MEDIA_DESKTOP") == "1"


def api_token() -> str:
    return os.getenv("MEDIA_API_TOKEN", "").strip()


def bind_host_is_loopback(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def require_token_when_exposed(host: str) -> None:
    """Headless entry points call this before listening.

    The desktop window never calls it. It already binds 127.0.0.1 and checks
    its own session cookie. A headless process may listen beyond loopback only
    when MEDIA_API_TOKEN is set.
    """
    if desktop_process() or bind_host_is_loopback(host):
        return
    if not api_token():
        raise SystemExit(
            f"Refusing to bind {host} without MEDIA_API_TOKEN. "
            "Set the token, or bind 127.0.0.1."
        )


def presented_api_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.headers.get("x-media-token", "").strip()


@app.middleware("http")
async def headless_api_token(request: Request, call_next):
    expected = api_token()
    if desktop_process() or not expected:
        return await call_next(request)
    supplied = presented_api_token(request)
    if not supplied or not secrets.compare_digest(supplied.encode(), expected.encode()):
        return Response("Missing or invalid API token", status_code=401)
    return await call_next(request)


executor = ThreadPoolExecutor(max_workers=WORKER_CONCURRENCY)
batch_executor = ThreadPoolExecutor(max_workers=BATCH_WORKER_MAX_CONCURRENCY)
state_lock = threading.Lock()
batch_lock = threading.RLock()
stage_sync_lock = threading.Lock()
stage_sync_times: dict[str, float] = {}

STAGE_PROGRESS_RANGES: dict[str, tuple[int, int]] = {
    "download": (0, 25),
    "transcribe": (25, 60),
    "translate": (60, 78),
    "burn": (78, 92),
    "bilibili_upload": (92, 100),
}
STAGE_LABELS: dict[str, str] = {
    "download": "下载",
    "transcribe": "转写",
    "translate": "翻译",
    "burn": "烧录",
    "bilibili_upload": "上传",
}
BATCH_STAGE_SYNC_THROTTLE_SECONDS = 1.0

AspectRatio = Literal["source", "16:9", "9:16", "1:1"]
Resolution = Literal["best", "1080p", "1440p", "2160p"]
Fps = Literal["source", "30", "60"]
SubtitleFontSize = Literal["auto", "small", "medium", "large"]
SubtitlePosition = Literal["bottom", "middle", "top"]
SubtitleMargin = Literal["auto", "compact", "normal", "high"]
OutputNameMode = Literal["original", "sequence", "custom"]
SubtitleOutputMode = Literal["bilingual", "zh_only", "en_only"]
SubtitleFontSizeMode = Literal["auto", "manual"]
SubtitleBilingualOrder = Literal["en_top_zh_bottom", "zh_top_en_bottom"]
WhisperInferenceMode = Literal["standard", "batched", "auto_repair", "auto", "gpu_only"]
BurnEncoder = Literal["auto", "nvenc", "cpu"]
SourceKind = Literal["youtube", "bilibili", "local", "url"]
MediaType = Literal["audio", "video", "unknown", "note"]
WorkflowStage = Literal["download", "transcribe", "translate", "burn", "bilibili_upload"]
BatchItemStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
BilibiliCopyright = Literal[1, 2]
BilibiliSourceMode = Literal["original_url", "custom"]
BilibiliCoverMode = Literal[
    "source_cover",
    "auto_middle_frame",
    "auto_first_frame",
    "custom_path",
    "selected_frame",
    "uploaded_image",
    "youtube_thumbnail",
]
BilibiliUploadLine = Literal["auto", "QN", "BDA2", "WS"]
BilibiliCollectionType = Literal["none", "season", "series"]
BilibiliCoverScope = Literal["batch", "per_item"]
BilibiliCoverSource = Literal["frame", "uploaded_image", "youtube_thumbnail"]


class SubtitleStyle(BaseModel):
    font_family: str = Field(default=DEFAULT_FONT)
    font_size: int = Field(default=44, ge=18, le=96)
    font_size_mode: SubtitleFontSizeMode = Field(default="manual")
    font_weight: int = Field(default=700, ge=100, le=900)
    primary_color: str = Field(default="#ffffff")
    outline_color: str = Field(default="#000000")
    outline_width: int = Field(default=3, ge=0, le=12)
    shadow: int = Field(default=1, ge=0, le=12)
    position: SubtitlePosition = Field(default="bottom")
    y_offset_percent: int = Field(default=8, ge=0, le=30)
    max_width_percent: int = Field(default=86, ge=50, le=95)
    line_spacing: float = Field(default=1.15, ge=0.9, le=1.6)
    bilingual_order: SubtitleBilingualOrder = Field(default="en_top_zh_bottom")
    background_enabled: bool = Field(default=False)
    background_color: str = Field(default="#000000")
    background_opacity: int = Field(default=45, ge=0, le=90)
    background_padding: int = Field(default=12, ge=0, le=32)


class TranslationContextProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=20000)
    glossary: str = Field(default="", max_length=20000)


class TranslationContextProfile(TranslationContextProfileInput):
    profile_id: str
    created_at: str
    updated_at: str


class SourceInput(BaseModel):
    source_kind: SourceKind = Field(default="youtube")
    source_value: str = Field(default="")
    client_row_id: str = Field(default="", max_length=128)
    source_title: str = Field(default="", max_length=500)
    expected_duration: float | None = Field(default=None, ge=0, le=21600)
    stop_after: WorkflowStage | None = None
    allow_muxed_audio: bool = False
    session_id: str = Field(default="", exclude=True)
    allow_unknown_audio: bool = False
    continue_from: tuple[str, str] | None = None

    @model_validator(mode="after")
    def normalize(self) -> "SourceInput":
        kind = self.source_kind or "youtube"
        value = (self.source_value or "").strip()
        if not value:
            raise ValueError("source_value is required")
        object.__setattr__(self, "source_kind", kind)
        object.__setattr__(self, "source_value", value)
        object.__setattr__(self, "client_row_id", (self.client_row_id or "").strip())
        return self


class BilibiliUploadSettings(BaseModel):
    enabled: bool = Field(default=False)
    auto_metadata: bool = False
    tid: int | None = Field(default=130, ge=1)
    tags: list[str] = Field(default_factory=lambda: ["音乐综合", "音乐"])
    desc: str = Field(default="", max_length=2000)
    dynamic: str = Field(default="", max_length=233)
    copyright: BilibiliCopyright = Field(default=2)
    source_mode: BilibiliSourceMode = Field(default="original_url")
    source: str = Field(default="", max_length=512)
    no_reprint: bool = Field(default=True)
    title_template: str = Field(default="{output_name}", max_length=80)
    cover_mode: BilibiliCoverMode = Field(default="source_cover")
    cover_path: str = Field(default="", max_length=1024)
    cover_scope: BilibiliCoverScope = Field(default="batch")
    cover_source: BilibiliCoverSource = Field(default="frame")
    cover_time_percent: float = Field(default=50, ge=0, le=100)
    cover_asset_url: str = Field(default="", max_length=2048)
    per_item_covers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    line: BilibiliUploadLine = Field(default="QN")
    collection_type: BilibiliCollectionType = Field(default="none")
    collection_id: str = Field(default="", max_length=64)
    series_id: str = Field(default="", max_length=64)

    @field_validator("tags", mode="before")
    @classmethod
    def parse_tags(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in re.split(r"[,，\n]+", value) if item.strip()]
        return value

    @field_validator("line", mode="before")
    @classmethod
    def normalize_line(cls, value: Any) -> Any:
        text = str(value or "QN").strip().upper()
        return "auto" if text == "AUTO" else text

    @model_validator(mode="after")
    def normalize(self) -> "BilibiliUploadSettings":
        tags = [str(item).strip()[:20] for item in self.tags if str(item).strip()]
        if self.enabled and not tags and not DESKTOP:
            raise ValueError("bilibili tags are required when upload is enabled")
        object.__setattr__(self, "tags", tags[:10])
        title_template = self.title_template.strip()
        object.__setattr__(self, "title_template", title_template if DESKTOP else title_template or "{output_name}")
        collection_id = (self.collection_id or self.series_id or "").strip()
        collection_type = self.collection_type
        if self.series_id and self.collection_type == "none":
            collection_type = "series"
        if not collection_id:
            collection_type = "none"
        object.__setattr__(self, "collection_id", collection_id)
        object.__setattr__(self, "collection_type", collection_type)
        object.__setattr__(self, "series_id", collection_id if collection_type == "series" else "")
        return self


class VideoJobRequest(BaseModel):
    youtube_url: str = Field(min_length=1)
    rights_confirmed: bool = Field(default=False)
    target_lang: str = Field(default=DEFAULT_TARGET_LANG)
    whisper_model: str = Field(default=WHISPER_MODEL)
    whisper_inference_mode: WhisperInferenceMode = Field(default=WHISPER_INFERENCE_MODE)  # type: ignore[assignment]
    translate_model: str = Field(default=TRANSLATE_MODEL)
    translation_context_profile_id: str = Field(default="", max_length=128)
    translation_context_note: str = Field(default="", max_length=4000)
    translation_glossary: str = Field(default="", max_length=4000)
    need_bilingual_srt: bool = Field(default=True)
    need_burn_subtitle: bool = Field(default=True)
    title: str | None = None
    output_name_mode: OutputNameMode = Field(default="original")
    output_name_prefix: str = Field(default="")
    output_index: int = Field(default=1, ge=1)
    aspect_ratio: AspectRatio = Field(default="source")
    resolution: Resolution = Field(default="best")
    fps: Fps = Field(default="source")
    subtitle_font_size: SubtitleFontSize = Field(default="auto")
    subtitle_color: str = Field(default="#ffffff")
    subtitle_outline_color: str = Field(default="#000000")
    subtitle_position: SubtitlePosition = Field(default="bottom")
    subtitle_margin: SubtitleMargin = Field(default="auto")
    subtitle_output_mode: SubtitleOutputMode = Field(default="bilingual")
    subtitle_style: SubtitleStyle | None = None

    @field_validator(
        "output_name_mode",
        "aspect_ratio",
        "resolution",
        "fps",
        "subtitle_font_size",
        "subtitle_position",
        "subtitle_margin",
        "subtitle_output_mode",
        mode="before",
    )
    @classmethod
    def default_empty_options(cls, value: Any, info: Any) -> Any:
        if value is None or value == "":
            defaults = {
                "output_name_mode": "original",
                "aspect_ratio": "source",
                "resolution": "best",
                "fps": "source",
                "subtitle_font_size": "auto",
                "subtitle_position": "bottom",
                "subtitle_margin": "auto",
                "subtitle_output_mode": "bilingual",
            }
            return defaults[info.field_name]
        return value

    @field_validator("whisper_inference_mode", mode="before")
    @classmethod
    def default_empty_inference_mode(cls, value: Any) -> Any:
        return WHISPER_INFERENCE_MODE if value is None or value == "" else value

    @field_validator("subtitle_style", mode="before")
    @classmethod
    def parse_subtitle_style(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return None
            return parsed or None
        return value


class OperatorRunRequest(BaseModel):
    operator: Literal["youtube_bilingual_video"] = "youtube_bilingual_video"
    input: VideoJobRequest


class JobQueryRequest(BaseModel):
    job_id: str = Field(min_length=1)


class StageDownloadRequest(BaseModel):
    audio_only: bool = False
    managed: bool = False
    allow_muxed_audio: bool = False
    retain_cover: bool = False
    source_kind: SourceKind = Field(default="youtube")
    source_value: str = Field(default="")
    youtube_url: str = Field(default="")
    rights_confirmed: bool = Field(default=False)
    title: str | None = None
    resolution: Resolution = Field(default="best")
    fps: Fps = Field(default="source")
    operator_batch_id: str = Field(default="")
    operator_item_id: str = Field(default="")

    @model_validator(mode="after")
    def normalize_source(self) -> "StageDownloadRequest":
        kind = self.source_kind or "youtube"
        value = (self.source_value or "").strip()
        youtube_url = (self.youtube_url or "").strip()
        if not value:
            value = youtube_url
        if not value:
            raise ValueError("source_value is required")
        object.__setattr__(self, "source_kind", kind)
        object.__setattr__(self, "source_value", value)
        object.__setattr__(self, "youtube_url", youtube_url or value)
        return self

    @field_validator("resolution", "fps", mode="before")
    @classmethod
    def default_empty_options(cls, value: Any, info: Any) -> Any:
        if value is None or value == "":
            return {"resolution": "best", "fps": "source"}[info.field_name]
        return value


class StageTranscribeRequest(BaseModel):
    source_video_url: str = Field(min_length=1)
    language: str = Field(default="en")
    whisper_model: str = Field(default=WHISPER_MODEL)
    whisper_inference_mode: WhisperInferenceMode = Field(default=WHISPER_INFERENCE_MODE)  # type: ignore[assignment]
    title: str | None = None
    operator_batch_id: str = Field(default="")
    operator_item_id: str = Field(default="")

    @field_validator("whisper_inference_mode", mode="before")
    @classmethod
    def default_empty_inference_mode(cls, value: Any) -> Any:
        return WHISPER_INFERENCE_MODE if value is None or value == "" else value


class StageTranslateRequest(BaseModel):
    english_srt_url: str = Field(min_length=1)
    target_lang: str = Field(default=DEFAULT_TARGET_LANG)
    translate_model: str = Field(default=TRANSLATE_MODEL)
    subtitle_output_mode: SubtitleOutputMode = Field(default="bilingual")
    translation_context_profile_id: str = Field(default="", max_length=128)
    translation_context_note: str = Field(default="", max_length=4000)
    translation_glossary: str = Field(default="", max_length=4000)
    operator_batch_id: str = Field(default="")
    operator_item_id: str = Field(default="")


class StageBurnRequest(BaseModel):
    source_video_url: str = Field(min_length=1)
    bilingual_srt_url: str = Field(min_length=1)
    english_srt_url: str | None = None
    aspect_ratio: AspectRatio = Field(default="source")
    subtitle_font_size: SubtitleFontSize = Field(default="auto")
    subtitle_color: str = Field(default="#ffffff")
    subtitle_outline_color: str = Field(default="#000000")
    subtitle_position: SubtitlePosition = Field(default="bottom")
    subtitle_margin: SubtitleMargin = Field(default="auto")
    subtitle_output_mode: SubtitleOutputMode = Field(default="bilingual")
    subtitle_style: SubtitleStyle | None = None
    burn_encoder: BurnEncoder | None = None
    output_name: str | None = None
    operator_batch_id: str = Field(default="")
    operator_item_id: str = Field(default="")

    @field_validator(
        "aspect_ratio",
        "subtitle_font_size",
        "subtitle_position",
        "subtitle_margin",
        "subtitle_output_mode",
        mode="before",
    )
    @classmethod
    def default_empty_options(cls, value: Any, info: Any) -> Any:
        if value is None or value == "":
            defaults = {
                "aspect_ratio": "source",
                "subtitle_font_size": "auto",
                "subtitle_position": "bottom",
                "subtitle_margin": "auto",
                "subtitle_output_mode": "bilingual",
            }
            return defaults[info.field_name]
        return value

    @field_validator("subtitle_style", mode="before")
    @classmethod
    def parse_subtitle_style(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return None
            return parsed or None
        return value


class StageBilibiliUploadRequest(BaseModel):
    final_video_url: str = Field(min_length=1)
    source_video_url: str = ""
    english_srt_url: str = ""
    translate_model: str = ""
    original_source: str = Field(default="")
    output_name: str = Field(default="")
    original_title: str = Field(default="")
    original_description: str | None = None
    source_thumbnail: str | None = None
    bilibili_metadata: dict[str, Any] | None = None
    upload_settings: BilibiliUploadSettings = Field(default_factory=BilibiliUploadSettings)
    allow_automatic_retry: bool = True
    operator_batch_id: str = Field(default="")
    operator_item_id: str = Field(default="")


class BatchCreateRequest(BaseModel):
    notes_auto: bool = False
    notes_mode: Literal['summary', 'curated', 'comprehensive'] = 'curated'
    knowledge_only: bool = False
    source_language: str = Field(default="auto", pattern=r"^(auto|[a-z]{2,3})$")
    transcript_ids: dict[str, int] = Field(default_factory=dict)
    publish_confirmed: list[str] = Field(default_factory=list)
    sources: list[SourceInput] | None = None
    youtube_urls: list[str] | None = None
    item_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    rights_confirmed: bool = Field(default=False)
    batch_concurrency: int | None = Field(default=None, ge=1)
    target_lang: str = Field(default=DEFAULT_TARGET_LANG)
    whisper_model: str = Field(default=WHISPER_MODEL)
    whisper_inference_mode: WhisperInferenceMode = Field(default=WHISPER_INFERENCE_MODE)  # type: ignore[assignment]
    translate_model: str = Field(default=TRANSLATE_MODEL)
    translation_context_profile_id: str = Field(default="", max_length=128)
    translation_context_note: str = Field(default="", max_length=4000)
    translation_glossary: str = Field(default="", max_length=4000)
    output_name_mode: OutputNameMode = Field(default="sequence")
    output_name_prefix: str = Field(default="")
    aspect_ratio: AspectRatio = Field(default="source")
    resolution: Resolution = Field(default="best")
    fps: Fps = Field(default="source")
    subtitle_font_size: SubtitleFontSize = Field(default="auto")
    subtitle_color: str = Field(default="#ffffff")
    subtitle_outline_color: str = Field(default="#000000")
    subtitle_position: SubtitlePosition = Field(default="bottom")
    subtitle_margin: SubtitleMargin = Field(default="auto")
    subtitle_output_mode: SubtitleOutputMode = Field(default="bilingual")
    subtitle_style: SubtitleStyle | None = None
    burn_encoder: BurnEncoder | None = None
    bilibili_upload: BilibiliUploadSettings = Field(default_factory=BilibiliUploadSettings)

    @field_validator(
        "output_name_mode",
        "aspect_ratio",
        "resolution",
        "fps",
        "subtitle_font_size",
        "subtitle_position",
        "subtitle_margin",
        "subtitle_output_mode",
        mode="before",
    )
    @classmethod
    def default_empty_options(cls, value: Any, info: Any) -> Any:
        if value is None or value == "":
            defaults = {
                "output_name_mode": "sequence",
                "aspect_ratio": "source",
                "resolution": "best",
                "fps": "source",
                "subtitle_font_size": "auto",
                "subtitle_position": "bottom",
                "subtitle_margin": "auto",
                "subtitle_output_mode": "bilingual",
            }
            return defaults[info.field_name]
        return value

    @field_validator("whisper_inference_mode", mode="before")
    @classmethod
    def default_empty_inference_mode(cls, value: Any) -> Any:
        return WHISPER_INFERENCE_MODE if value is None or value == "" else value

    @field_validator("subtitle_style", mode="before")
    @classmethod
    def parse_subtitle_style(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return None
            return parsed or None
        return value

    @field_validator("bilibili_upload", mode="before")
    @classmethod
    def parse_bilibili_upload(cls, value: Any) -> Any:
        if value is None or value == "":
            return {}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return {}
            return parsed or {}
        return value

    @field_validator("item_overrides", mode="before")
    @classmethod
    def parse_item_overrides(cls, value: Any) -> Any:
        if value is None or value == "":
            return {}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return value if isinstance(value, dict) else {}

    @model_validator(mode="after")
    def normalize_sources(self) -> "BatchCreateRequest":
        sources = list(self.sources or [])
        if not sources and self.youtube_urls:
            sources = [SourceInput(source_kind="youtube", source_value=url) for url in self.youtube_urls]
        if not sources:
            raise ValueError("at least one source is required")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "youtube_urls", [source.source_value for source in sources if source.source_kind == "youtube"])
        return self


class PreviewFrameRequest(BaseModel):
    source_kind: SourceKind = Field(default="youtube")
    source_value: str = Field(default="")
    youtube_url: str = Field(default="")
    aspect_ratio: AspectRatio = Field(default="source")
    resolution: Resolution = Field(default="best")
    fps: Fps = Field(default="source")
    subtitle_output_mode: SubtitleOutputMode = Field(default="bilingual")
    subtitle_style: SubtitleStyle | None = None
    preview_time_percent: float = Field(default=50, ge=0, le=100)

    @field_validator("subtitle_style", mode="before")
    @classmethod
    def parse_subtitle_style(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return None
            return parsed or None
        return value

    @model_validator(mode="after")
    def normalize_source(self) -> "PreviewFrameRequest":
        kind = self.source_kind or "youtube"
        value = (self.source_value or "").strip()
        youtube_url = (self.youtube_url or "").strip()
        if not value:
            value = youtube_url
        if not value:
            raise ValueError("source_value is required")
        object.__setattr__(self, "source_kind", kind)
        object.__setattr__(self, "source_value", value)
        object.__setattr__(self, "youtube_url", youtube_url or value)
        return self


class BilibiliCoverPreviewRequest(BaseModel):
    source_kind: SourceKind = Field(default="youtube")
    source_value: str = Field(default="")
    youtube_url: str = Field(default="")
    preview_time_percent: float = Field(default=50, ge=0, le=100)
    cover_source_mode: Literal["frame", "youtube_thumbnail"] = Field(default="frame")

    @model_validator(mode="after")
    def normalize_source(self) -> "BilibiliCoverPreviewRequest":
        kind = self.source_kind or "youtube"
        value = (self.source_value or "").strip()
        youtube_url = (self.youtube_url or "").strip()
        if not value:
            value = youtube_url
        if not value:
            raise ValueError("source_value is required")
        object.__setattr__(self, "source_kind", kind)
        object.__setattr__(self, "source_value", value)
        object.__setattr__(self, "youtube_url", youtube_url or value)
        return self


class BatchItemState(BaseModel):
    item_id: str
    index: int
    client_row_id: str = ""
    youtube_url: str
    source_kind: SourceKind = "youtube"
    source_value: str = ""
    source_title: str = ""
    media_type: MediaType | None = None
    stop_after: WorkflowStage | None = None
    planned_stages: list[WorkflowStage] | None = None
    platform: str = ""
    duration: float | None = None
    status: BatchItemStatus = "queued"
    stage: str = "queued"
    progress: int = 0
    execution_id: str | None = None
    work_progress: float | None = None
    work_progress_known: bool | None = None
    waiting_for_shared: bool | None = None
    work_plan: dict[str, Any] | None = None
    message: str = "queued"
    output_name: str | None = None
    stage_jobs: dict[str, str] = Field(default_factory=dict)
    stage_details: dict[str, dict[str, Any]] = Field(default_factory=dict)
    active_stage_job_id: str | None = None
    local_progress: int = 0
    progress_detail: str = ""
    log_tail: list[str] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class BatchState(BaseModel):
    batch_id: str
    status: BatchItemStatus = "queued"
    total: int
    queued: int
    running: int = 0
    succeeded: int = 0
    failed: int = 0
    request: dict[str, Any] = Field(default_factory=dict)
    items: list[BatchItemState] = Field(default_factory=list)
    created_at: str
    updated_at: str


class JobState(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: str = "queued"
    progress: int = 0
    message: str = ""
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: str
    updated_at: str


def _load_stages() -> None:
    """Run each stage file in this module's namespace."""
    directory = Path(__file__).resolve().parent / "stages"
    for name in (
        "jobs",
        "download",
        "transcribe",
        "translate",
        "subtitles",
        "bilibili",
        "pipeline",
        "api",
    ):
        path = directory / f"{name}.py"
        code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
        exec(code, globals())


_load_stages()


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("MEDIA_BIND_HOST", "127.0.0.1")
    port = int(os.getenv("MEDIA_PORT", "8090"))
    require_token_when_exposed(host)
    uvicorn.run(app, host=host, port=port)
