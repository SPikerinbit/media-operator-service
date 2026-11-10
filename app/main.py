from __future__ import annotations

import hashlib
import json
import os
import re
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
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

APP_NAME = "media-operator-service"
DESKTOP = os.getenv("MEDIA_DESKTOP") == "1"
WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if DESKTOP and os.name == "nt" else 0
DEFAULT_TARGET_LANG = "zh-CN"
DEFAULT_YT_DLP_FORMAT = "bestvideo+bestaudio/best"
DEFAULT_WHISPER_MODEL = "small"
DEFAULT_TRANSLATE_MODEL = "deepseek-chat"
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

app = FastAPI(title=APP_NAME, version="1.1.0")
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
SourceKind = Literal["youtube", "bilibili", "local"]
BatchItemStatus = Literal["queued", "running", "succeeded", "failed"]
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
    source_thumbnail: str | None = None
    bilibili_metadata: dict[str, Any] | None = None
    upload_settings: BilibiliUploadSettings = Field(default_factory=BilibiliUploadSettings)
    allow_automatic_retry: bool = True
    operator_batch_id: str = Field(default="")
    operator_item_id: str = Field(default="")


class BatchCreateRequest(BaseModel):
    knowledge_only: bool = False
    source_language: str = Field(default="auto", pattern=r"^(auto|[a-z]{2,3})$")
    transcript_ids: dict[str, int] = Field(default_factory=dict)
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
    status: BatchItemStatus = "queued"
    stage: str = "queued"
    progress: int = 0
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    BATCHES_DIR.mkdir(parents=True, exist_ok=True)
    TRANSLATION_CONTEXTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default



def job_dir(job_id: str) -> Path:
    if DESKTOP and not re.fullmatch(r"[a-zA-Z0-9_-]+", job_id):
        raise FileNotFoundError(job_id)
    return JOBS_DIR / job_id


def batch_dir(batch_id: str) -> Path:
    if DESKTOP and not re.fullmatch(r"batch_[0-9a-f]{12}", batch_id):
        raise FileNotFoundError(batch_id)
    return BATCHES_DIR / batch_id


def batch_state_path(batch_id: str) -> Path:
    return batch_dir(batch_id) / "state.json"


def state_path(job_id: str) -> Path:
    return job_dir(job_id) / "state.json"


def request_path(job_id: str) -> Path:
    return job_dir(job_id) / "request.json"


def artifact_path(job_id: str, name: str) -> Path:
    return job_dir(job_id) / name


def public_file_url(job_id: str, name: str) -> str:
    return f"{'' if DESKTOP else PUBLIC_BASE_URL}/files/{job_id}/{name}"


def public_job_url(job_id: str) -> str:
    return f"{PUBLIC_BASE_URL}/jobs/{job_id}"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    last_error: Exception | None = None
    for attempt in range(8):
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError as error:
            last_error = error
            time.sleep(min(0.25, 0.03 * (attempt + 1)))
        except OSError as error:
            last_error = error
            time.sleep(min(0.25, 0.03 * (attempt + 1)))
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except Exception:
        pass
    if last_error is not None:
        raise last_error


def read_json(path: Path) -> Any:
    last_error: Exception | None = None
    for _ in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            last_error = error
            time.sleep(0.05)
    if last_error is not None:
        raise last_error
    return json.loads(path.read_text(encoding="utf-8"))


def clean_translation_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:limit]


def normalize_saved_translation_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def load_translation_context_profiles() -> list[dict[str, Any]]:
    ensure_dirs()
    if not TRANSLATION_CONTEXTS_PATH.exists():
        return []
    data = read_json(TRANSLATION_CONTEXTS_PATH)
    if isinstance(data, dict):
        data = data.get("profiles", [])
    if not isinstance(data, list):
        return []
    profiles: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            profile = TranslationContextProfile.model_validate(item)
        except Exception:
            continue
        profiles.append(profile.model_dump())
    return profiles


def save_translation_context_profiles(profiles: list[dict[str, Any]]) -> None:
    write_json(TRANSLATION_CONTEXTS_PATH, {"profiles": profiles})


def is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_youtube_url(value: str) -> bool:
    return video_url_kind(value) == "youtube"


def video_url_kind(value: str) -> str | None:
    try:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.port is not None:
            return None
        host = parsed.hostname or ""
    except ValueError:
        return None
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}:
        return "youtube"
    if host in {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"}:
        return "bilibili"
    return None


def is_local_source_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    return parsed.path.startswith("/files/")


def source_display_title(kind: str, source: str, title: str = "") -> str:
    if kind in {"local", "subtitle"}:
        return Path(source).name
    return " ".join(title.split())[:500] if title and not is_http_url(title.strip()) else ""


def normalize_local_source_path(value: str) -> Path:
    raw = value.strip()
    if not raw:
        raise ValueError("source_value is required")
    if raw.startswith("/files/"):
        _, path = resolve_local_artifact_from_url(raw)
        return path
    parsed = urlparse(raw)
    if parsed.scheme == "file":
        raw = parsed.path or ""
        if re.match(r"^/[A-Za-z]:/", raw):
            raw = raw[1:]
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("local source must be an absolute path or /files/ resource url")
    if not path.exists():
        raise ValueError(f"local source not found: {path}")
    if not path.is_file():
        raise ValueError(f"local source is not a file: {path}")
    return path


def import_local_source(job_id: str, source_value: str) -> Path:
    source_path = normalize_local_source_path(source_value)
    suffix = source_path.suffix or ".mp4"
    target_path = artifact_path(job_id, f"source{suffix}")
    if target_path.exists():
        return target_path
    shutil.copy2(source_path, target_path)
    return target_path


def parse_url_list(text_or_urls: str | list[str]) -> list[str]:
    if isinstance(text_or_urls, str):
        raw_parts = re.split(r"[\s,]+", text_or_urls)
    else:
        raw_parts = []
        for item in text_or_urls:
            raw_parts.extend(re.split(r"[\s,]+", str(item)))
    urls: list[str] = []
    seen: set[str] = set()
    for raw in raw_parts:
        url = raw.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def build_output_name(mode: OutputNameMode, prefix: str, index: int, fallback: str) -> str:
    clean_prefix = prefix.strip()
    if mode == "sequence":
        return f"{clean_prefix or 'video'}{index}"
    if mode == "custom" and clean_prefix:
        return clean_prefix if index == 1 else f"{clean_prefix}{index}"
    return fallback.strip() or "source"


def safe_download_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .")
    return cleaned[:120] or "final"


def bilibili_configured() -> bool:
    return bool(BILI_SESSDATA and BILI_JCT and BILI_BUVID3)


def require_bilibili_config() -> None:
    if not bilibili_configured():
        raise RuntimeError("Bilibili credential is not configured: set BILI_SESSDATA, BILI_JCT and BILI_BUVID3")


def bilibili_cookie_header() -> str:
    values = {
        "SESSDATA": BILI_SESSDATA,
        "bili_jct": BILI_JCT,
        "buvid3": BILI_BUVID3,
        "DedeUserID": BILI_DEDEUSERID,
        "ac_time_value": BILI_AC_TIME_VALUE,
    }
    return "; ".join(f"{key}={value}" for key, value in values.items() if value)


def render_bilibili_title(template: str, *, output_name: str, index: int, original_title: str, source: str) -> str:
    values = {
        "output_name": output_name or f"video{index}",
        "index": str(index),
        "original_title": original_title or output_name or f"video{index}",
        "source": source,
    }
    text = template or "{output_name}"
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return safe_download_filename(text)[:80] or values["output_name"][:80]


def extract_bilibili_submission_ids(value: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, raw in item.items():
                lower = str(key).lower()
                if lower in {"bvid", "bv_id", "bv"} and raw:
                    found["bvid"] = str(raw)
                if lower in {"aid", "avid", "archive_id"} and raw:
                    try:
                        found["aid"] = int(raw)
                    except Exception:
                        found["aid"] = raw
                visit(raw)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def load_state(job_id: str) -> JobState:
    path = state_path(job_id)
    if not path.exists():
        raise FileNotFoundError(job_id)
    return JobState.model_validate(read_json(path))


def save_state(state: JobState) -> JobState:
    with state_lock:
        payload = state.model_dump()
        write_json(state_path(state.job_id), payload)
        return state


def load_batch(batch_id: str) -> BatchState:
    path = batch_state_path(batch_id)
    if not path.exists():
        raise FileNotFoundError(batch_id)
    return BatchState.model_validate(read_json(path))


def save_batch(batch: BatchState) -> BatchState:
    with batch_lock:
        payload = batch.model_dump()
        write_json(batch_state_path(batch.batch_id), payload)
        return batch


def recompute_batch_counts(data: dict[str, Any]) -> None:
    items = data.get("items") or []
    data["queued"] = sum(1 for item in items if item.get("status") == "queued")
    data["running"] = sum(1 for item in items if item.get("status") == "running")
    data["succeeded"] = sum(1 for item in items if item.get("status") == "succeeded")
    data["failed"] = sum(1 for item in items if item.get("status") == "failed")
    if data["running"]:
        data["status"] = "running"
    elif data["queued"]:
        data["status"] = "queued"
    elif data["failed"]:
        data["status"] = "failed"
    else:
        data["status"] = "succeeded"


def update_batch_item(
    batch_id: str,
    item_id: str,
    *,
    status: BatchItemStatus | None = None,
    stage: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    output_name: str | None = None,
    source_title: str | None = None,
    stage_jobs: dict[str, str] | None = None,
    stage_details: dict[str, dict[str, Any]] | None = None,
    active_stage_job_id: str | None = None,
    local_progress: int | None = None,
    progress_detail: str | None = None,
    log_tail: list[str] | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    clear_error: bool = False,
) -> BatchState:
    with batch_lock:
        batch = load_batch(batch_id)
        data = batch.model_dump()
        found = False
        for item in data["items"]:
            if item["item_id"] != item_id:
                continue
            found = True
            if status is not None:
                item["status"] = status
            if stage is not None:
                item["stage"] = stage
            if progress is not None:
                item["progress"] = progress
            if message is not None:
                item["message"] = message
            if output_name is not None:
                item["output_name"] = output_name
            if source_title is not None:
                item["source_title"] = source_title
            if stage_jobs is not None:
                item["stage_jobs"] = stage_jobs
            if stage_details is not None:
                item["stage_details"] = stage_details
            if active_stage_job_id is not None:
                item["active_stage_job_id"] = active_stage_job_id
            if local_progress is not None:
                item["local_progress"] = local_progress
            if progress_detail is not None:
                item["progress_detail"] = progress_detail
            if log_tail is not None:
                item["log_tail"] = log_tail
            if result is not None:
                item["result"] = result
            if clear_error:
                item["error"] = None
            elif error is not None:
                item["error"] = error
            item["updated_at"] = now_iso()
            break
        if not found:
            raise FileNotFoundError(item_id)
        data["updated_at"] = now_iso()
        recompute_batch_counts(data)
        updated = BatchState.model_validate(data)
        save_batch(updated)
        return updated


def clamp_percent(value: int | float | None) -> int:
    try:
        return max(0, min(100, int(float(value or 0))))
    except Exception:
        return 0


def stage_overall_progress(stage: str, local_progress: int | float | None) -> int:
    start, end = STAGE_PROGRESS_RANGES.get(stage, (0, 100))
    local = clamp_percent(local_progress)
    return max(0, min(100, int(round(start + (end - start) * local / 100))))


def stage_progress_log_path(job_id: str) -> Path:
    return job_dir(job_id) / "progress.log.txt"


def append_stage_log(job_id: str, stage: str, progress: int, message: str, raw: str | None = None) -> None:
    path = stage_progress_log_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    detail = " ".join(str(message or "").split())
    raw_text = " ".join(str(raw or "").split())
    if raw_text and raw_text != detail:
        detail = f"{detail} | {raw_text}" if detail else raw_text
    line = f"{now_iso()}\t{stage}\t{clamp_percent(progress)}\t{detail}\n"
    with path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(line)


def read_stage_log_tail(job_id: str, limit: int = 5) -> list[str]:
    path = stage_progress_log_path(job_id)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    return lines[-limit:]


def exception_diagnostics(error: BaseException) -> dict[str, Any]:
    message = str(error).strip()
    repr_text = repr(error)
    return {
        "type": error.__class__.__name__,
        "message": message or repr_text or error.__class__.__name__,
        "repr": repr_text,
        "args": [str(item) for item in getattr(error, "args", ())],
        "cause": repr(error.__cause__) if getattr(error, "__cause__", None) else "",
        "context": repr(error.__context__) if getattr(error, "__context__", None) else "",
    }


def safe_json_payload(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return str(value)
    if isinstance(value, BaseException):
        return exception_diagnostics(value)
    if isinstance(value, dict):
        return {str(key): safe_json_payload(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [safe_json_payload(item, depth + 1) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def bilibili_event_message(data: Any, fallback: str = "uploading video") -> str:
    if not isinstance(data, dict):
        return fallback
    name = str(data.get("name") or data.get("event") or data.get("msg") or data.get("message") or fallback)
    event_data = data.get("data")
    err: Any = None
    if isinstance(event_data, list) and event_data:
        first = event_data[0]
        if isinstance(first, dict):
            err = first.get("err")
    elif isinstance(event_data, dict):
        err = event_data.get("err")
    if err:
        if isinstance(err, dict):
            err_text = str(err.get("message") or err.get("repr") or err.get("type") or err)
        else:
            err_text = str(err)
        if err_text:
            return f"{name}: {err_text}"
    return name


def bilibili_upload_line_candidates(preferred: str) -> list[str]:
    valid = {"auto", "QN", "BDA2", "WS"}
    candidates: list[str] = []
    for raw in [preferred, *BILI_UPLOAD_FALLBACK_LINES]:
        candidate = (raw or "").strip()
        candidate = "auto" if candidate.lower() == "auto" else candidate.upper()
        if candidate in valid and candidate not in candidates:
            candidates.append(candidate)
    return candidates or ["auto"]


def sync_stage_to_batch(
    job_id: str,
    stage: str,
    *,
    status: Literal["queued", "running", "succeeded", "failed"],
    progress: int,
    message: str,
    error: dict[str, Any] | None = None,
    force: bool = False,
) -> None:
    try:
        state = load_state(job_id)
    except Exception:
        return
    request_payload = state.request or {}
    batch_id = str(request_payload.get("operator_batch_id") or "").strip()
    item_id = str(request_payload.get("operator_item_id") or "").strip()
    if not batch_id or not item_id:
        return

    sync_key = f"{batch_id}:{item_id}:{stage}"
    now_monotonic = time.monotonic()
    if not force:
        with stage_sync_lock:
            last = stage_sync_times.get(sync_key, 0.0)
            if now_monotonic - last < BATCH_STAGE_SYNC_THROTTLE_SECONDS:
                return
            stage_sync_times[sync_key] = now_monotonic
    else:
        with stage_sync_lock:
            stage_sync_times[sync_key] = now_monotonic

    try:
        batch = load_batch(batch_id)
    except Exception:
        return
    current = next((entry for entry in batch.items if entry.item_id == item_id), None)
    if current is None:
        return

    local_progress = clamp_percent(progress)
    stage_jobs = dict(current.stage_jobs or {})
    stage_jobs[stage] = job_id
    stage_details = dict(current.stage_details or {})
    stage_details[stage] = {
        "job_id": job_id,
        "label": STAGE_LABELS.get(stage, stage),
        "status": status,
        "progress": local_progress,
        "message": message,
        "updated_at": now_iso(),
    }
    log_tail = read_stage_log_tail(job_id)
    is_terminal_upload_success = not DESKTOP and stage == "bilibili_upload" and status == "succeeded"
    batch_status: BatchItemStatus = "failed" if status == "failed" else ("succeeded" if is_terminal_upload_success else "running")
    batch_stage = "done" if is_terminal_upload_success else stage
    batch_progress = 100 if is_terminal_upload_success else stage_overall_progress(stage, local_progress)
    batch_message = "completed" if is_terminal_upload_success else message
    batch_result = state.result if is_terminal_upload_success else None
    update_batch_item(
        batch_id,
        item_id,
        status=batch_status,
        stage=batch_stage,
        progress=batch_progress,
        message=batch_message,
        stage_jobs=stage_jobs,
        stage_details=stage_details,
        active_stage_job_id=job_id,
        local_progress=local_progress,
        progress_detail=f"{STAGE_LABELS.get(stage, stage)} {local_progress}% · {message}",
        log_tail=log_tail,
        result=batch_result,
        error=error,
        clear_error=status in {"queued", "running", "succeeded"},
    )


def report_stage_progress(
    job_id: str,
    stage: str,
    progress: int,
    message: str,
    *,
    status: Literal["queued", "running", "succeeded", "failed"] | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    raw: str | None = None,
    force: bool = False,
) -> JobState:
    state = update_state(
        job_id,
        status=status,
        stage=stage,
        progress=clamp_percent(progress),
        message=message,
        result=result,
        error=error,
    )
    append_stage_log(job_id, stage, clamp_percent(progress), message, raw)
    sync_stage_to_batch(
        job_id,
        stage,
        status=state.status,
        progress=state.progress,
        message=message,
        error=error,
        force=force or status in {"queued", "succeeded", "failed"},
    )
    return state


def create_job(request: VideoJobRequest) -> JobState:
    ensure_dirs()
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = now_iso()
    folder = job_dir(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    payload = request.model_dump()
    payload["rights_confirmed"] = bool(request.rights_confirmed)
    payload["need_bilingual_srt"] = bool(request.need_bilingual_srt)
    payload["need_burn_subtitle"] = bool(request.need_burn_subtitle)
    state = JobState(
        job_id=job_id,
        status="queued",
        stage="queued",
        progress=0,
        message="queued",
        request=payload,
        created_at=now,
        updated_at=now,
    )
    write_json(request_path(job_id), payload)
    save_state(state)
    report_stage_progress(job_id, stage, 0, "queued", status="queued", force=True)
    return state


def create_stage_job(stage: str, request_payload: dict[str, Any]) -> JobState:
    ensure_dirs()
    job_id = f"stage_{stage}_{uuid.uuid4().hex[:12]}"
    now = now_iso()
    folder = job_dir(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    payload = dict(request_payload)
    payload["stage"] = stage
    state = JobState(
        job_id=job_id,
        status="queued",
        stage=stage,
        progress=0,
        message="queued",
        request=payload,
        created_at=now,
        updated_at=now,
    )
    write_json(request_path(job_id), payload)
    save_state(state)
    return state


def create_batch(request: BatchCreateRequest) -> BatchState:
    ensure_dirs()
    sources = list(request.sources or [])
    if not sources and request.youtube_urls:
        sources = [SourceInput(source_kind="youtube", source_value=url) for url in parse_url_list(request.youtube_urls)]
    if not sources:
        raise ValueError("at least one source is required")
    if not request.rights_confirmed:
        raise PermissionError("rights_confirmed must be true")

    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    now = now_iso()
    folder = batch_dir(batch_id)
    folder.mkdir(parents=True, exist_ok=True)
    request_payload = request.model_dump()
    request_payload["sources"] = [source.model_dump() for source in sources]
    request_payload["youtube_urls"] = [source.source_value for source in sources if source.source_kind == "youtube"]
    request_payload["batch_concurrency"] = min(
        int(request.batch_concurrency or BATCH_WORKER_CONCURRENCY),
        BATCH_WORKER_MAX_CONCURRENCY,
    )
    items = [
        BatchItemState(
            item_id=f"item_{uuid.uuid4().hex[:12]}",
            index=index,
            client_row_id=source.client_row_id,
            youtube_url=source.source_value,
            source_kind=source.source_kind,
            source_value=source.source_value,
            source_title=source_display_title(source.source_kind, source.source_value, source.source_title),
            output_name=build_output_name(
                request.output_name_mode,
                request.output_name_prefix,
                index,
                f"source{index}",
            ),
            created_at=now,
            updated_at=now,
        )
        for index, source in enumerate(sources, start=1)
    ]
    batch = BatchState(
        batch_id=batch_id,
        status="queued",
        total=len(items),
        queued=len(items),
        request=request_payload,
        items=items,
        created_at=now,
        updated_at=now,
    )
    save_batch(batch)
    return batch


def update_state(
    job_id: str,
    *,
    status: Literal["queued", "running", "succeeded", "failed"] | None = None,
    stage: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> JobState:
    state = load_state(job_id)
    data = state.model_dump()
    if status is not None:
        data["status"] = status
    if stage is not None:
        data["stage"] = stage
    if progress is not None:
        data["progress"] = progress
    if message is not None:
        data["message"] = message
    if result is not None:
        data["result"] = result
    if error is not None:
        data["error"] = error
    data["updated_at"] = now_iso()
    updated = JobState.model_validate(data)
    save_state(updated)
    return updated


def wait_for_state_change(job_id: str, *, hold_seconds: int = 0) -> JobState:
    state = load_state(job_id)
    if hold_seconds <= 0 or state.status in {"succeeded", "failed"}:
        return state

    deadline = time.monotonic() + hold_seconds

    while time.monotonic() < deadline:
        current = load_state(job_id)
        if current.status in {"succeeded", "failed"}:
            return current

        sleep_for = min(0.25, max(0.05, deadline - time.monotonic()))
        time.sleep(sleep_for)

    return load_state(job_id)


def safe_job_artifact(job_id: str, name: str) -> Path:
    path = artifact_path(job_id, name).resolve()
    base = job_dir(job_id).resolve()
    if base not in path.parents and path != base:
        raise ValueError("invalid artifact path")
    return path


def resolve_local_artifact_from_url(url: str) -> tuple[str, Path]:
    parsed = urlparse(url)
    if not parsed.path.startswith("/files/"):
        raise ValueError("url must be a /files/{job_id}/{filename} resource")
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 3:
        raise ValueError("invalid files url")
    _, job_id, filename = parts
    path = safe_job_artifact(job_id, filename)
    if not path.exists():
        raise ValueError("artifact not found")
    return job_id, path


def run_command(cmd: list[str], *, cwd: Path | None = None, log_dir: Path | None = None, log_name: str = "command") -> None:
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / f"{log_name}.out.log"
        stderr_path = log_dir / f"{log_name}.err.log"
        with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_file, stderr_path.open(
            "w", encoding="utf-8", errors="replace"
        ) as stderr_file:
            completed = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                check=False,
                creationflags=WINDOW_FLAGS,
            )
        if completed.returncode != 0:
            stderr = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
            stdout = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
            message = stderr or stdout or f"command failed with exit code {completed.returncode}"
            raise RuntimeError(message)
        return

    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
        creationflags=WINDOW_FLAGS,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or f"command failed with exit code {completed.returncode}"
        raise RuntimeError(stderr)


def run_command_streaming(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    log_dir: Path | None = None,
    log_name: str = "command",
    on_stdout_line: Callable[[str], None] | None = None,
    on_stderr_line: Callable[[str], None] | None = None,
    env: dict[str, str] | None = None,
) -> None:
    log_dir = log_dir or tempfile.mkdtemp(prefix="media-command-")
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{log_name}.out.log"
    stderr_path = log_dir / f"{log_name}.err.log"
    stdout_tail: list[str] = []
    stderr_tail: list[str] = []

    process = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
        encoding="utf-8" if DESKTOP else None,
        errors="replace",
        creationflags=WINDOW_FLAGS,
        env=env,
    )

    def reader(pipe: Any, path: Path, tail: list[str], callback: Callable[[str], None] | None) -> None:
        with path.open("w", encoding="utf-8", errors="replace") as handle:
            try:
                for line in iter(pipe.readline, ""):
                    text = line.rstrip("\r\n")
                    handle.write(text + "\n")
                    handle.flush()
                    tail.append(text)
                    del tail[:-20]
                    if callback:
                        callback(text)
            finally:
                pipe.close()

    stdout_thread = threading.Thread(target=reader, args=(process.stdout, stdout_path, stdout_tail, on_stdout_line), daemon=True)
    stderr_thread = threading.Thread(target=reader, args=(process.stderr, stderr_path, stderr_tail, on_stderr_line), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    return_code = process.wait()
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    if return_code != 0:
        message = "\n".join(stderr_tail or stdout_tail).strip() or f"command failed with exit code {return_code}"
        raise RuntimeError(message)


_ffmpeg_encoders_cache: set[str] | None = None
_ffmpeg_hwaccels_cache: set[str] | None = None


def ffmpeg_encoders() -> set[str]:
    global _ffmpeg_encoders_cache
    if _ffmpeg_encoders_cache is not None:
        return _ffmpeg_encoders_cache
    try:
        completed = subprocess.run(
            [FFMPEG_BIN, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=WINDOW_FLAGS,
        )
        text = f"{completed.stdout}\n{completed.stderr}"
    except Exception:
        text = ""
    _ffmpeg_encoders_cache = set(re.findall(r"\b[\w]+(?:_[\w]+)+\b", text))
    return _ffmpeg_encoders_cache


def ffmpeg_hwaccels() -> set[str]:
    global _ffmpeg_hwaccels_cache
    if _ffmpeg_hwaccels_cache is not None:
        return _ffmpeg_hwaccels_cache
    try:
        completed = subprocess.run(
            [FFMPEG_BIN, "-hide_banner", "-hwaccels"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=WINDOW_FLAGS,
        )
        text = f"{completed.stdout}\n{completed.stderr}"
    except Exception:
        text = ""
    names: set[str] = set()
    for line in text.splitlines():
        value = line.strip().lower()
        if value and re.fullmatch(r"[a-z0-9_]+", value):
            names.add(value)
    _ffmpeg_hwaccels_cache = names
    return _ffmpeg_hwaccels_cache


@lru_cache(maxsize=4)
def nvenc_runtime_error(binary: str) -> str:
    try:
        completed = subprocess.run(
            [binary, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=s=320x240:d=0.1",
             "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, errors="replace", timeout=12, creationflags=WINDOW_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)
    return "" if completed.returncode == 0 else completed.stderr.strip() or "NVENC 编码检测失败"


def ffmpeg_nvenc_available() -> bool:
    if DESKTOP:
        return not nvenc_runtime_error(FFMPEG_BURN_BIN)
    return "h264_nvenc" in ffmpeg_encoders()


def ffmpeg_cuda_hwaccel_available() -> bool:
    return "cuda" in ffmpeg_hwaccels()


def selected_burn_encoder(mode: str | None = None) -> str:
    return "nvenc" if (mode or FFMPEG_BURN_ENCODER) != "cpu" and ffmpeg_nvenc_available() else "cpu"


def ffmpeg_video_encoder_args(encoder: str) -> list[str]:
    if encoder == "nvenc":
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            FFMPEG_NVENC_PRESET,
            "-tune",
            FFMPEG_NVENC_TUNE,
            "-rc",
            "vbr",
            "-cq",
            str(FFMPEG_NVENC_CQ),
            "-b:v",
            "0",
            "-pix_fmt",
            "yuv420p",
        ]
    return ["-c:v", "libx264", "-pix_fmt", "yuv420p"]


def build_yt_dlp_format_selector(resolution: Resolution = "best", fps: Fps = "source") -> str:
    video_filters: list[str] = []
    if resolution != "best":
        height = {"1080p": 1080, "1440p": 1440, "2160p": 2160}[resolution]
        video_filters.append(f"height<={height}")
    if fps != "source":
        video_filters.append(f"fps<={fps}")
    if not video_filters:
        return DEFAULT_YT_DLP_FORMAT
    filter_text = "][".join(video_filters)
    mp4_filter_text = f"{filter_text}][ext=mp4][vcodec^=avc1"
    m4a_audio = "bestaudio[ext=m4a]/bestaudio"
    return (
        f"bestvideo[{mp4_filter_text}]+{m4a_audio}/"
        f"best[ext=mp4][{filter_text}]/"
        f"bestvideo[{filter_text}]+bestaudio/"
        f"best[{filter_text}]/best"
    )


def to_windows_path(path: Path) -> str:
    raw = str(path)
    if os.name == "nt":
        return raw
    completed = subprocess.run(
        ["wslpath", "-w", raw],
        capture_output=True,
        text=True,
        check=False,
        creationflags=WINDOW_FLAGS,
    )
    if completed.returncode == 0:
        converted = completed.stdout.strip()
        if converted:
            return converted
    if raw.startswith("/mnt/") and len(raw) > 6 and raw[6] == "/":
        drive_letter = raw[5].upper()
        remainder = raw[7:].replace("/", "\\")
        return f"{drive_letter}:\\{remainder}"
    return raw


def yt_dlp_ffmpeg_location() -> str:
    configured = str(FFMPEG_BIN or "").strip()
    if not configured or configured.lower() == "ffmpeg":
        return ""
    path = Path(configured)
    if path.name.lower().startswith("ffmpeg"):
        return str(path.parent)
    return str(path)


def online_media_proxy(url: str) -> str | None:
    if YT_DLP_PROXY or not DESKTOP:
        return YT_DLP_PROXY or None
    target = urlparse(url)
    if os.name == "nt":
        windows_proxies = urllib_request.getproxies_registry()
        if windows_proxies:
            if urllib_request.proxy_bypass_registry(target.hostname or ""):
                return None
            return windows_proxies.get(target.scheme) or windows_proxies.get("all")
    if urllib_request.proxy_bypass(target.hostname or ""):
        return None
    proxies = urllib_request.getproxies()
    return proxies.get(target.scheme) or proxies.get("all")


def yt_dlp_network_flags(url: str) -> list[str]:
    proxy = online_media_proxy(url)
    if not DESKTOP:
        return ["--proxy", proxy] if proxy else []
    return ["--ignore-config", "--encoding", "utf-8", "--proxy", proxy or "",
            "--js-runtimes", f"deno:{Path(YT_DLP_BIN).with_name('deno.exe')}"]


def online_media_error(url: str, diagnostics: str) -> str:
    site = "B 站" if video_url_kind(url) == "bilibili" else "YouTube"
    reason = diagnostics.lower()
    if any(term in reason for term in ("10061", "connection refused", "actively refused", "proxyerror")):
        return f"无法连接到{site}。请检查 Windows 系统代理或网络连接后重试。"
    if any(term in reason for term in ("timed out", "timeout", "getaddrinfo", "failed to establish", "network is unreachable")):
        return f"连接{site}超时或网络不可达，请检查网络后重试。"
    if "sign in" in reason or "login required" in reason:
        return f"{site}要求登录或验证，此链接暂时无法读取。"
    if "unavailable" in reason or "private video" in reason:
        return f"{site}上的视频暂不可用，请确认链接仍可访问。"
    return f"读取{site}素材失败，请核对链接后重试。详细信息已记录。"


def download_youtube(
    job_id: str,
    youtube_url: str,
    format_selector: str = DEFAULT_YT_DLP_FORMAT,
    progress_callback: Callable[[int, str, str | None], None] | None = None,
    *,
    audio_only: bool = False,
) -> Path:
    source_dir = job_dir(job_id)
    source_dir.mkdir(parents=True, exist_ok=True)
    if YT_DLP_BIN.lower().endswith(".exe"):
        output_template = to_windows_path(source_dir / "source.%(ext)s")
    else:
        output_template = str(source_dir / "source.%(ext)s")
    cmd = [
        YT_DLP_BIN,
        "--no-playlist",
        "--socket-timeout",
        str(YT_DLP_SOCKET_TIMEOUT),
        "--retries",
        str(YT_DLP_RETRIES),
        "--fragment-retries",
        str(YT_DLP_FRAGMENT_RETRIES),
        "--newline",
        "--merge-output-format",
        "mp4",
        "-f",
        format_selector,
        "-o",
        output_template,
        youtube_url,
    ]
    cmd[1:1] = yt_dlp_network_flags(youtube_url)
    if DESKTOP:
        metadata_file = source_dir / "source-metadata.jsonl"
        metadata_file.unlink(missing_ok=True)
        cmd[1:1] = [
            "--no-simulate", "--print-to-file", "after_move:%(.{title,thumbnail})j",
            to_windows_path(metadata_file) if YT_DLP_BIN.lower().endswith(".exe") else str(metadata_file),
        ]
    ffmpeg_location = yt_dlp_ffmpeg_location()
    if ffmpeg_location:
        cmd[1:1] = ["--ffmpeg-location", ffmpeg_location]
    def handle_yt_dlp_line(line: str) -> None:
        if not progress_callback:
            return
        percent_match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
        if percent_match:
            percent = float(percent_match.group(1))
            progress_callback(min(95, max(5, int(5 + percent * 0.9))), line.strip(), line)
            return
        if "[Merger]" in line:
            progress_callback(97, "merging video and audio", line)
        elif "[ExtractAudio]" in line or "[Fixup" in line:
            progress_callback(98, line.strip(), line)

    run_command_streaming(
        cmd,
        cwd=ROOT_DIR,
        log_dir=source_dir,
        log_name="yt-dlp",
        on_stdout_line=handle_yt_dlp_line,
        on_stderr_line=handle_yt_dlp_line,
    )

    candidates = sorted(
        [
            p
            for p in source_dir.iterdir()
            if p.is_file() and p.name.startswith("source.")
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if audio_only:
        candidates = [p for p in candidates if p.suffix.lower() in {".m4a", ".webm", ".mp3", ".opus", ".aac", ".ogg", ".wav"}]
        if candidates:
            return candidates[0]
    if not candidates:
        raise RuntimeError("yt-dlp finished but no source file was found")

    def probe_stream_types(path: Path) -> set[str]:
        completed = subprocess.run(
            [
                FFPROBE_BIN,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            creationflags=WINDOW_FLAGS,
        )
        if completed.returncode != 0:
            return set()
        return {line.strip() for line in completed.stdout.splitlines() if line.strip()}

    preferred = source_dir / "source.mp4"
    if preferred.exists():
        stream_types = probe_stream_types(preferred)
        if "video" in stream_types and "audio" in stream_types:
            return preferred

    video_candidates: list[Path] = []
    audio_candidates: list[Path] = []
    for candidate in candidates:
        stream_types = probe_stream_types(candidate)
        if "video" in stream_types:
            video_candidates.append(candidate)
        if stream_types == {"audio"}:
            audio_candidates.append(candidate)

    if video_candidates:
        chosen_video = video_candidates[0]
        chosen_video_types = probe_stream_types(chosen_video)
        if "audio" in chosen_video_types:
            return chosen_video
        if audio_candidates:
            merged_path = source_dir / "source.mp4"
            run_command(
                [
                    FFMPEG_BIN,
                    "-y",
                    "-i",
                    str(chosen_video),
                    "-i",
                    str(audio_candidates[0]),
                    "-c",
                    "copy",
                    str(merged_path),
                ]
            )
            merged_types = probe_stream_types(merged_path)
            if "video" in merged_types:
                return merged_path
        return chosen_video

    return candidates[0]


def ensure_placeholder_video(job_id: str, youtube_url: str) -> Path:
    placeholder = artifact_path(job_id, "source.txt")
    placeholder.write_text(
        f"placeholder source for {youtube_url}\ncreated_at={now_iso()}\n",
        encoding="utf-8",
    )
    return placeholder


def format_srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def placeholder_srt(job_id: str, title: str, source_hint: str) -> Path:
    content = "\n".join(
        [
            "1",
            "00:00:00,000 --> 00:00:04,000",
            f"Placeholder transcript for {source_hint}",
            "",
        ]
    )
    path = artifact_path(job_id, "english.srt")
    path.write_text(content, encoding="utf-8")
    return path


def write_transcription_artifacts(
    job_id: str,
    *,
    segments: list[dict[str, Any]],
    words: list[dict[str, Any]],
    language: str,
    model_name: str,
) -> tuple[Path, Path]:
    raw_segments_path = artifact_path(job_id, "raw_segments.json")
    aligned_words_path = artifact_path(job_id, "aligned_words.json")
    diagnostics_path = artifact_path(job_id, "timing_diagnostics.json")
    raw_segments_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    aligned_words_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    subtitles = subtitles_from_aligned_words(words) if words else subtitles_from_segments(segments)
    if DESKTOP and language in {"zh", "yue", "ja"}:
        cjk = r"぀-ヿ㐀-鿿"
        for subtitle in subtitles:
            subtitle.content = re.sub(rf"(?<=[{cjk}]) +(?=[{cjk}])", "", subtitle.content)
    segmentation_stats = getattr(subtitles_from_aligned_words, "last_stats", {}) if words else {}
    srt_path = artifact_path(job_id, "english.srt")
    srt_path.write_text(srt.compose(subtitles), encoding="utf-8")
    diagnostics = build_timing_diagnostics(
        subtitles,
        words=words,
        language=language,
        model_name=model_name,
    )
    diagnostics["segmentation"] = segmentation_stats
    diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    return srt_path, diagnostics_path


def normalize_word_text(value: Any) -> str:
    return str(value or "").strip()


def word_start(word: dict[str, Any]) -> float:
    return max(0.0, float(word.get("start") or 0.0))


def word_end(word: dict[str, Any]) -> float:
    start = word_start(word)
    raw_end = word.get("end")
    if raw_end is None:
        return start
    return max(start, float(raw_end))


def subtitles_from_segments(segments: list[dict[str, Any]]) -> list[srt.Subtitle]:
    subtitles: list[srt.Subtitle] = []
    for index, segment in enumerate(segments, start=1):
        start = max(0.0, float(segment.get("start") or 0.0))
        end = max(start + 0.25, float(segment.get("end") or start + 0.25))
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        subtitles.append(
            srt.Subtitle(
                index=len(subtitles) + 1,
                start=timedelta(seconds=start),
                end=timedelta(seconds=end),
                content=text,
            )
        )
    return normalize_subtitle_timing(subtitles)


def subtitles_from_aligned_words(words: list[dict[str, Any]]) -> list[srt.Subtitle]:
    clean_words = [word for word in words if normalize_word_text(word.get("word"))]
    subtitles: list[srt.Subtitle] = []
    current: list[dict[str, Any]] = []
    subtitles_from_aligned_words.last_stats = {}

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = " ".join(normalize_word_text(item.get("word")) for item in current).strip()
        if not text:
            current = []
            return
        start = word_start(current[0])
        end = word_end(current[-1]) + SUBTITLE_TAIL_PADDING_MS / 1000
        end = max(start + SUBTITLE_MIN_DURATION_MS / 1000, end)
        subtitles.append(
            srt.Subtitle(
                index=len(subtitles) + 1,
                start=timedelta(seconds=start),
                end=timedelta(seconds=end),
                content=text,
            )
        )
        current = []

    for word in clean_words:
        if not current:
            current.append(word)
            continue
        previous = current[-1]
        gap_ms = max(0.0, (word_start(word) - word_end(previous)) * 1000)
        candidate_text = " ".join(normalize_word_text(item.get("word")) for item in [*current, word]).strip()
        candidate_duration_ms = max(1.0, (word_end(word) - word_start(current[0])) * 1000)
        too_long = candidate_duration_ms > SUBTITLE_MAX_DURATION_MS
        too_wide = len(candidate_text) > SUBTITLE_MAX_CHARS
        too_sparse = gap_ms > SUBTITLE_MAX_GAP_MS
        ends_sentence = normalize_word_text(previous.get("word")).endswith((".", "?", "!", "。", "？", "！"))
        if too_long or too_wide or too_sparse or (ends_sentence and candidate_duration_ms > 1200):
            flush()
        current.append(word)
    flush()
    before_coherence_count = len(subtitles)
    coherence_result = merge_coherent_subtitles(subtitles)
    normalized = normalize_subtitle_timing(coherence_result["subtitles"])
    second_pass_result = merge_coherent_subtitles(normalized)
    if second_pass_result["coherence_merged_count"]:
        normalized = normalize_subtitle_timing(second_pass_result["subtitles"])
    subtitles_from_aligned_words.last_stats = {
        "segmentation_before_count": before_coherence_count,
        "segmentation_after_count": len(normalized),
        "coherence_merged_count": coherence_result["coherence_merged_count"] + second_pass_result["coherence_merged_count"],
        "orphan_merged_count": coherence_result["orphan_merged_count"] + second_pass_result["orphan_merged_count"],
        "coherence_second_pass_merged_count": second_pass_result["coherence_merged_count"],
        "merge_settings": {
            "enabled": SUBTITLE_COHERENCE_MERGE,
            "max_chars": SUBTITLE_COHERENCE_MAX_CHARS,
            "max_duration_ms": SUBTITLE_COHERENCE_MAX_DURATION_MS,
            "max_gap_ms": SUBTITLE_COHERENCE_MAX_GAP_MS,
            "orphan_max_chars": SUBTITLE_ORPHAN_MAX_CHARS,
        },
    }
    return normalized


def subtitle_has_sentence_end(subtitle: srt.Subtitle) -> bool:
    return subtitle.content.strip().endswith((".", "?", "!", "。", "？", "！"))


def subtitle_looks_like_orphan(subtitle: srt.Subtitle) -> bool:
    text = subtitle.content.strip()
    if len(text) <= SUBTITLE_ORPHAN_MAX_CHARS:
        return True
    tokens = re.findall(r"[A-Za-z']+", text)
    return len(tokens) <= 3 and len(text) <= SUBTITLE_ORPHAN_MAX_CHARS + 8


def can_merge_subtitle_pair(left: srt.Subtitle, right: srt.Subtitle) -> tuple[bool, bool]:
    if not SUBTITLE_COHERENCE_MERGE:
        return False, False
    left_text = left.content.strip()
    right_text = right.content.strip()
    if not left_text or not right_text:
        return False, False
    if is_pure_vocal_filler(left_text) or is_pure_vocal_filler(right_text):
        return False, False
    gap_ms = (right.start - left.end).total_seconds() * 1000
    if gap_ms < -20 or gap_ms > SUBTITLE_COHERENCE_MAX_GAP_MS:
        return False, False
    combined = f"{left_text} {right_text}".strip()
    duration = max(0.001, (right.end - left.start).total_seconds())
    if len(combined) > SUBTITLE_COHERENCE_MAX_CHARS:
        return False, False
    if duration * 1000 > SUBTITLE_COHERENCE_MAX_DURATION_MS:
        return False, False
    if len(combined) / duration > SUBTITLE_MAX_CPS:
        return False, False
    orphan = subtitle_looks_like_orphan(right)
    continuation = not subtitle_has_sentence_end(left)
    return orphan or continuation, orphan


def merge_coherent_subtitles(subtitles: list[srt.Subtitle]) -> dict[str, Any]:
    if not SUBTITLE_COHERENCE_MERGE or len(subtitles) < 2:
        return {
            "subtitles": subtitles,
            "coherence_merged_count": 0,
            "orphan_merged_count": 0,
        }
    merged: list[srt.Subtitle] = []
    coherence_merged_count = 0
    orphan_merged_count = 0
    for subtitle in subtitles:
        if not merged:
            merged.append(subtitle)
            continue
        previous = merged[-1]
        should_merge, orphan = can_merge_subtitle_pair(previous, subtitle)
        if should_merge:
            merged[-1] = srt.Subtitle(
                index=previous.index,
                start=previous.start,
                end=subtitle.end,
                content=f"{previous.content.strip()} {subtitle.content.strip()}".strip(),
            )
            coherence_merged_count += 1
            if orphan:
                orphan_merged_count += 1
            continue
        merged.append(subtitle)
    for index, subtitle in enumerate(merged, start=1):
        subtitle.index = index
    return {
        "subtitles": merged,
        "coherence_merged_count": coherence_merged_count,
        "orphan_merged_count": orphan_merged_count,
    }


def normalize_subtitle_timing(subtitles: list[srt.Subtitle]) -> list[srt.Subtitle]:
    source_subtitles = sorted(subtitles, key=lambda item: (item.start, item.end))
    source_subtitles = handle_repeated_subtitle_runs(source_subtitles)
    ordered = merge_short_subtitles(source_subtitles)
    normalized: list[srt.Subtitle] = []
    for subtitle in ordered:
        start_seconds = max(0.0, subtitle.start.total_seconds())
        min_read_seconds = min(SUBTITLE_MAX_DURATION_MS / 1000, max(SUBTITLE_MIN_DURATION_MS / 1000, len(subtitle.content) / SUBTITLE_MAX_CPS))
        end_seconds = max(start_seconds + min_read_seconds, subtitle.end.total_seconds())
        if normalized:
            previous_end = normalized[-1].end.total_seconds()
            if start_seconds < previous_end + 0.02:
                start_seconds = previous_end + 0.02
            if end_seconds <= start_seconds:
                end_seconds = start_seconds + SUBTITLE_MIN_DURATION_MS / 1000
        normalized.append(
            srt.Subtitle(
                index=len(normalized) + 1,
                start=timedelta(seconds=start_seconds),
                end=timedelta(seconds=end_seconds),
                content=subtitle.content,
            )
        )
    for index, subtitle in enumerate(normalized, start=1):
        subtitle.index = index
    return normalized


def handle_repeated_subtitle_runs(subtitles: list[srt.Subtitle]) -> list[srt.Subtitle]:
    if SUBTITLE_REPEAT_HANDLING == "keep":
        return subtitles

    handled: list[srt.Subtitle] = []
    index = 0
    while index < len(subtitles):
        current = subtitles[index]
        if not is_repeated_subtitle_candidate(current):
            handled.append(current)
            index += 1
            continue

        run_start = index
        index += 1
        while index < len(subtitles) and is_repeated_subtitle_candidate(subtitles[index]):
            index += 1
        repeated_run = subtitles[run_start:index]
        span_ms = (repeated_run[-1].end - repeated_run[0].start).total_seconds() * 1000
        should_handle_run = (
            len(repeated_run) >= SUBTITLE_REPEAT_MIN_BLOCKS
            and span_ms >= SUBTITLE_REPEAT_MIN_SPAN_MS
        ) or any(is_long_vocal_filler(subtitle) for subtitle in repeated_run)
        if not should_handle_run:
            handled.extend(repeated_run)
            continue
        if SUBTITLE_REPEAT_HANDLING == "drop":
            continue
        end = min(
            repeated_run[-1].end,
            repeated_run[0].start + timedelta(milliseconds=SUBTITLE_MAX_DURATION_MS),
        )
        handled.append(
            srt.Subtitle(
                index=len(handled) + 1,
                start=repeated_run[0].start,
                end=end,
                content=SUBTITLE_REPEAT_COMPRESS_TEXT,
            )
        )

    for output_index, subtitle in enumerate(handled, start=1):
        subtitle.index = output_index
    return handled


def is_repeated_subtitle_candidate(subtitle: srt.Subtitle) -> bool:
    return is_repeated_hallucination(subtitle.content) or is_long_vocal_filler(subtitle)


def is_long_vocal_filler(subtitle: srt.Subtitle) -> bool:
    duration_ms = (subtitle.end - subtitle.start).total_seconds() * 1000
    return duration_ms >= SUBTITLE_REPEAT_MIN_SPAN_MS and is_pure_vocal_filler(subtitle.content)


def is_pure_vocal_filler(text: str) -> bool:
    tokens = re.findall(r"[A-Za-z']+", text.lower())
    if not tokens:
        return False
    filler_tokens = {"ha", "haha", "cha", "chacha", "ja", "jaja"}
    return all(token.strip("'") in filler_tokens for token in tokens)


def is_repeated_hallucination(text: str) -> bool:
    tokens = re.findall(r"[A-Za-z']+", text.lower())
    if len(tokens) < SUBTITLE_REPEAT_TOKEN_LIMIT:
        return False
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    repeated = max(counts.values(), default=0)
    return repeated >= SUBTITLE_REPEAT_TOKEN_LIMIT and repeated / max(1, len(tokens)) >= 0.75


def merge_short_subtitles(subtitles: list[srt.Subtitle]) -> list[srt.Subtitle]:
    merged: list[srt.Subtitle] = []
    index = 0
    while index < len(subtitles):
        current = subtitles[index]
        text = current.content.strip()
        if (
            not is_pure_vocal_filler(text)
            and len(text) <= SUBTITLE_MERGE_SHORT_CHARS
            and index + 1 < len(subtitles)
            and not is_pure_vocal_filler(subtitles[index + 1].content)
            and (subtitles[index + 1].start - current.end).total_seconds() * 1000 <= SUBTITLE_MAX_GAP_MS
        ):
            next_item = subtitles[index + 1]
            combined = f"{text} {next_item.content.strip()}".strip()
            if len(combined) <= SUBTITLE_MAX_CHARS:
                merged.append(
                    srt.Subtitle(
                        index=len(merged) + 1,
                        start=current.start,
                        end=next_item.end,
                        content=combined,
                    )
                )
                index += 2
                continue
        if merged and len(text) <= SUBTITLE_MERGE_SHORT_CHARS and not is_pure_vocal_filler(text):
            previous = merged[-1]
            gap_ms = (current.start - previous.end).total_seconds() * 1000
            combined = f"{previous.content.strip()} {text}".strip()
            if (
                gap_ms <= SUBTITLE_MAX_GAP_MS
                and len(combined) <= SUBTITLE_MAX_CHARS
                and not is_pure_vocal_filler(previous.content)
            ):
                merged[-1] = srt.Subtitle(
                    index=previous.index,
                    start=previous.start,
                    end=current.end,
                    content=combined,
                )
                index += 1
                continue
        merged.append(
            srt.Subtitle(
                index=len(merged) + 1,
                start=current.start,
                end=current.end,
                content=current.content,
            )
        )
        index += 1
    return merged


def subtitle_gap_diagnostics(subtitles: list[srt.Subtitle], threshold_seconds: float | None = None) -> list[dict[str, Any]]:
    threshold = WHISPER_GAP_THRESHOLD_SECONDS if threshold_seconds is None else threshold_seconds
    gaps: list[dict[str, Any]] = []
    ordered = sorted(subtitles, key=lambda item: item.start)
    for left, right in zip(ordered, ordered[1:]):
        gap = (right.start - left.end).total_seconds()
        if gap <= threshold:
            continue
        gaps.append(
            {
                "after_index": left.index,
                "before_index": right.index,
                "start": left.end.total_seconds(),
                "end": right.start.total_seconds(),
                "duration": gap,
                "left_text": left.content,
                "right_text": right.content,
                "suspicious": True,
            }
        )
    return gaps


def build_timing_diagnostics(
    subtitles: list[srt.Subtitle],
    *,
    words: list[dict[str, Any]],
    language: str,
    model_name: str,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for subtitle in subtitles:
        duration = max(0.001, (subtitle.end - subtitle.start).total_seconds())
        chars = len(subtitle.content)
        cps = chars / duration
        items.append(
            {
                "index": subtitle.index,
                "start": subtitle.start.total_seconds(),
                "end": subtitle.end.total_seconds(),
                "duration": duration,
                "chars": chars,
                "cps": cps,
                "too_fast": cps > SUBTITLE_MAX_CPS,
                "too_long": duration * 1000 > SUBTITLE_MAX_DURATION_MS,
                "repeated_like": is_repeated_hallucination(subtitle.content),
                "text": subtitle.content,
            }
        )
    gaps = subtitle_gap_diagnostics(subtitles)
    return {
        "language": language,
        "model": model_name,
        "word_timestamps": bool(words),
        "word_count": len(words),
        "subtitle_count": len(subtitles),
        "gap_threshold_seconds": WHISPER_GAP_THRESHOLD_SECONDS,
        "suspicious_gap_count": len(gaps),
        "max_gap_seconds": max((gap["duration"] for gap in gaps), default=0.0),
        "settings": {
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
        "gaps": gaps,
        "items": items,
    }


def decode_audio_for_whisper(source_path: Path) -> tuple[np.ndarray, int]:
    temp_wav: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            temp_wav = Path(temp_file.name)
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-i",
            str(source_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-vn",
            "-f",
            "wav",
            str(temp_wav),
        ]
        run_command(cmd)
        with wave.open(str(temp_wav), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frames = wav_file.readframes(wav_file.getnframes())
        if channels != 1:
            raise RuntimeError(f"unexpected channel count in extracted audio: {channels}")
        if sample_width == 2:
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        elif sample_width == 4:
            audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            raise RuntimeError(f"unsupported sample width in extracted audio: {sample_width}")
        return audio, sample_rate
    finally:
        if temp_wav is not None:
            try:
                temp_wav.unlink(missing_ok=True)
            except Exception:
                pass


def detect_cuda_runtime() -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "available": False,
        "device_count": 0,
        "supported_compute_types": [],
        "error": None,
    }
    try:
        import ctranslate2  # type: ignore
    except Exception as exc:
        diagnostics["error"] = str(exc)
        return diagnostics

    try:
        diagnostics["device_count"] = int(ctranslate2.get_cuda_device_count())
        if diagnostics["device_count"] > 0:
            diagnostics["available"] = True
            diagnostics["supported_compute_types"] = list(ctranslate2.get_supported_compute_types("cuda"))
    except Exception as exc:
        diagnostics["error"] = str(exc)
    return diagnostics


def resolve_whisper_runtime(model_name: str) -> dict[str, Any]:
    backend = WHISPER_BACKEND or "auto"
    if backend not in {"auto", "cli", "faster-whisper"}:
        raise ValueError(f"unsupported WHISPER_BACKEND: {backend}")

    cuda_info = detect_cuda_runtime()
    requested_device = WHISPER_DEVICE or "auto"
    if requested_device == "cuda" and not cuda_info.get("available"):
        raise RuntimeError("WHISPER_DEVICE=cuda requested but CUDA runtime is not available")
    device = requested_device
    if device == "auto":
        device = "cuda" if cuda_info.get("available") else "cpu"
    compute_type = WHISPER_COMPUTE_TYPE or ("float16" if device == "cuda" else "int8")

    return {
        "backend": backend,
        "model_name": model_name,
        "device": device,
        "device_index": WHISPER_DEVICE_INDEX,
        "compute_type": compute_type,
        "cpu_threads": WHISPER_CPU_THREADS,
        "num_workers": WHISPER_NUM_WORKERS,
        "cuda": cuda_info,
    }


def resolve_whisper_model_ref(model_name: str) -> str:
    requested = model_name.strip() or DEFAULT_WHISPER_MODEL
    local_candidates = [
        DATA_DIR / "models" / f"faster-whisper-{requested}",
        DATA_DIR / "models" / requested,
    ]
    for candidate in local_candidates:
        if (candidate / "model.bin").exists():
            return str(candidate)
    return requested


def whisper_model_status(model_name: str) -> dict[str, Any]:
    requested = model_name.strip() or DEFAULT_WHISPER_MODEL
    if DESKTOP:
        from app.desktop_models import status
        return status(DATA_DIR, requested)
    local_candidates = [
        DATA_DIR / "models" / f"faster-whisper-{requested}",
        DATA_DIR / "models" / requested,
    ]
    local_path = next((candidate for candidate in local_candidates if (candidate / "model.bin").is_file()), None)
    return {
        "name": requested,
        "available": local_path is not None,
        "path": str(local_path) if local_path else None,
        "preferred_path": str(local_candidates[0]),
    }


def transcribe_video(
    job_id: str,
    source_path: Path,
    *,
    language: str = "en",
    model_name: str | None = None,
    inference_mode: str | None = None,
    progress_callback: Callable[[int, str, str | None], None] | None = None,
) -> Path:
    whisper_cli = WHISPER_BIN or shutil.which("whisper") or ""
    requested_model = (model_name or WHISPER_MODEL).strip() or DEFAULT_WHISPER_MODEL
    mode = (inference_mode or WHISPER_INFERENCE_MODE).strip() or WHISPER_INFERENCE_MODE
    if DESKTOP and not whisper_model_status(requested_model)["available"]:
        raise RuntimeError(f"本地 Whisper {requested_model} 未准备好，请在「设置 → 本地资源与环境」下载模型后重试。")
    runtime = {"backend": "faster-whisper"} if DESKTOP else resolve_whisper_runtime(requested_model)

    if runtime["backend"] == "cli":
        if not whisper_cli:
            raise RuntimeError("WHISPER_BACKEND=cli but whisper CLI is not installed")
        output_dir = job_dir(job_id) / "transcript"
        output_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            whisper_cli,
            str(source_path),
            "--model",
            requested_model,
            "--language",
            language,
            "--output_format",
            "srt",
            "--output_dir",
            str(output_dir),
        ]
        run_command(cmd, log_dir=job_dir(job_id), log_name="whisper-cli")
        produced = list(output_dir.glob("*.srt"))
        if not produced:
            raise RuntimeError("whisper finished but no .srt file was produced")
        return produced[0]

    try:
        job_dir(job_id).mkdir(parents=True, exist_ok=True)
        worker_exe = Path(sys.executable).with_name("MediaWhisper.exe")
        worker = [str(worker_exe)] if DESKTOP and getattr(sys, "frozen", False) else [
            WHISPER_WORKER_PYTHON or sys.executable, "-m", "app.whisper_worker"
        ]
        cmd = [
            *worker,
            "--job-id",
            job_id,
            "--source",
            str(source_path),
            "--language",
            language,
            "--model",
            requested_model,
            "--inference-mode",
            mode,
        ]
        def handle_whisper_line(line: str) -> None:
            if not progress_callback:
                return
            if not line.startswith("WHISPER_PROGRESS\t"):
                return
            parts = line.split("\t", 2)
            if len(parts) < 3:
                return
            progress_callback(clamp_percent(parts[1]), parts[2].strip(), line)

        if DESKTOP:
            from app.desktop_config import worker_environment
            env = worker_environment()
            if mode == "gpu_only" and env["WHISPER_DEVICE"] != "cuda":
                raise RuntimeError("严格 GPU 模式需要可用且已启用的 NVIDIA 转录环境。请到设置检测。")
        else:
            env = None
        try:
            run_command_streaming(
                cmd, cwd=ROOT_DIR, log_dir=job_dir(job_id), log_name="whisper",
                on_stdout_line=handle_whisper_line, on_stderr_line=handle_whisper_line, env=env,
            )
        except RuntimeError:
            if mode == "gpu_only" or not env or env.get("WHISPER_DEVICE") != "cuda":
                raise
            if progress_callback:
                progress_callback(5, "GPU 转录失败，改用 CPU 重试", None)
            env["WHISPER_DEVICE"] = "cpu"
            env["WHISPER_COMPUTE_TYPE"] = ""
            env.pop("MEDIA_GPU_DLL_DIR", None)
            run_command_streaming(
                cmd, cwd=ROOT_DIR, log_dir=job_dir(job_id), log_name="whisper-cpu",
                on_stdout_line=handle_whisper_line, on_stderr_line=handle_whisper_line, env=env,
            )
        path = artifact_path(job_id, "english.srt")
        if not path.exists():
            raise RuntimeError("faster-whisper worker finished but no english.srt was produced")
        return path
    except Exception as exc:
        if DESKTOP:
            if mode == "gpu_only":
                raise RuntimeError("严格 GPU 转录失败，任务已停止。请检查 NVIDIA 环境和显存，详情见本地 Whisper 日志。") from exc
            raise RuntimeError("Whisper 转录失败。请在设置中检查本地模型和运行环境，详情见本地 Whisper 日志。") from exc
        if runtime["backend"] == "auto" and whisper_cli:
            output_dir = job_dir(job_id) / "transcript"
            output_dir.mkdir(parents=True, exist_ok=True)
            cmd = [
                whisper_cli,
                str(source_path),
                "--model",
                requested_model,
                "--language",
                language,
                "--output_format",
                "srt",
                "--output_dir",
                str(output_dir),
            ]
            run_command(cmd, log_dir=job_dir(job_id), log_name="whisper-cli")
            produced = list(output_dir.glob("*.srt"))
            if not produced:
                raise RuntimeError("whisper finished but no .srt file was produced")
            return produced[0]
        if ALLOW_PLACEHOLDER_ARTIFACTS:
            return placeholder_srt(job_id, source_path.stem, source_path.name)
        raise RuntimeError(
            f"no usable whisper backend available for model={requested_model}: {exc}"
        ) from exc


def split_srt_blocks(text: str) -> list[srt.Subtitle]:
    return list(srt.parse(text))


def build_translation_system_prompt(target_lang: str, context_note: str = "", glossary: str = "") -> str:
    parts = [
        f"Translate subtitles into concise {target_lang} output.",
        "Preserve meaning, keep one output line per input line, and do not add commentary.",
        "Use any supplied domain context or glossary only when it is relevant to the sentence.",
        "Do not force glossary entries if they conflict with the sentence meaning, and never translate or output the context itself.",
    ]
    note = clean_translation_text(context_note)
    terms = clean_translation_text(glossary)
    if note:
        parts.append(f"Domain context for reference only:\n{note}")
    if terms:
        parts.append(f"Glossary for reference only:\n{terms}")
    return "\n\n".join(parts)


def build_translation_json_system_prompt(target_lang: str, context_note: str = "", glossary: str = "") -> str:
    parts = [
        "You are a subtitle translation engine.",
        "Return json only.",
        f"Translate subtitles into concise {target_lang} output.",
        "The response must be a valid json object with this exact shape:",
        '{"items":[{"index":1,"translation":"..."},{"index":2,"translation":"..."}]}',
        "Keep one json item per input line, preserve the index, and do not add explanations, markdown, or code fences.",
        "If a source line is empty, return an empty translation string for that item.",
    ]
    note = clean_translation_text(context_note)
    terms = clean_translation_text(glossary)
    if note:
        parts.append(f"Domain context for reference only:\n{note}")
    if terms:
        parts.append(f"Glossary for reference only:\n{terms}")
    return "\n\n".join(parts)


def build_translation_json_user_prompt(texts: list[str], target_lang: str) -> str:
    example_input = "1. Which is the longest river in the world?\n2. The Nile River."
    example_output = json.dumps(
        {
            "items": [
                {"index": 1, "translation": "Which river is the longest in the world?"},
                {"index": 2, "translation": "The Nile River."},
            ]
        },
        ensure_ascii=False,
        indent=2,
    )
    input_lines = "\n".join(f"{idx + 1}. {line}" for idx, line in enumerate(texts))
    return (
        f"Translate the following subtitle lines into {target_lang} and return json only.\n\n"
        f"EXAMPLE INPUT:\n{example_input}\n\n"
        f"EXAMPLE JSON OUTPUT:\n{example_output}\n\n"
        f"INPUT:\n{input_lines}"
    )


def _extract_json_object_text(content: str) -> str:
    text = (content or "").strip()
    if not text:
        raise ValueError("empty translation content")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    raise ValueError("translation content does not contain a json object")


def _normalize_translation_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _estimate_translation_max_tokens(texts: list[str]) -> int:
    char_count = sum(len(text) for text in texts)
    line_count = max(1, len(texts))
    estimate = int(char_count * 2.2) + line_count * 48 + 256
    return max(256, min(8192, estimate))


def _validate_translation_items(data: Any, texts: list[str]) -> list[str]:
    if not isinstance(data, dict):
        raise ValueError("translation payload is not a json object")
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("translation json missing items array")

    translated: dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("translation items must be json objects")
        index = item.get("index")
        if isinstance(index, str) and index.isdigit():
            index = int(index)
        if not isinstance(index, int):
            raise ValueError("translation item missing numeric index")
        if index < 1 or index > len(texts):
            raise ValueError(f"translation item index out of range: {index}")
        translation = _normalize_translation_text(item.get("translation"))
        if index in translated:
            raise ValueError(f"duplicate translation item index: {index}")
        translated[index] = translation

    if len(translated) != len(texts):
        raise ValueError(
            f"translation json returned {len(translated)} items for {len(texts)} inputs"
        )

    ordered: list[str] = []
    for idx, source_text in enumerate(texts, start=1):
        translation = translated.get(idx, "")
        if not translation:
            translation = source_text
        ordered.append(translation)
    return ordered


def _translate_lines_via_provider(
    texts: list[str],
    target_lang: str,
    *,
    model_name: str | None = None,
    context_note: str = "",
    glossary: str = "",
) -> list[str]:
    requested_model = (model_name or TRANSLATE_MODEL).strip()
    if not (TRANSLATE_PROVIDER and TRANSLATE_API_BASE and requested_model and TRANSLATE_API_KEY):
        raise RuntimeError(
            "translation provider is not configured "
            f"(provider={TRANSLATE_PROVIDER!r}, api_base={TRANSLATE_API_BASE!r}, "
            f"model={requested_model!r}, key_set={bool(TRANSLATE_API_KEY)})"
        )

    prompt = build_translation_json_user_prompt(texts, target_lang)
    payload = {
        "model": requested_model,
        "messages": [
            {
                "role": "system",
                "content": build_translation_json_system_prompt(target_lang, context_note, glossary),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": _estimate_translation_max_tokens(texts),
        "response_format": {"type": "json_object"},
    }
    with TRANSLATE_PROMPT_SEMAPHORE:
        with httpx.Client(timeout=120) as client:
            response = client.post(
                f"{TRANSLATE_API_BASE.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {TRANSLATE_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = str(message.get("content") or "").strip()
    json_text = _extract_json_object_text(content)
    parsed = json.loads(json_text)
    return _validate_translation_items(parsed, texts)


def _translate_lines_recursive(
    texts: list[str],
    target_lang: str,
    *,
    model_name: str | None = None,
    context_note: str = "",
    glossary: str = "",
) -> list[str]:
    if not texts:
        return []
    try:
        return _translate_lines_via_provider(
            texts,
            target_lang,
            model_name=model_name,
            context_note=context_note,
            glossary=glossary,
        )
    except Exception as error:
        if DESKTOP and isinstance(error, (httpx.TransportError, httpx.HTTPStatusError)):
            raise
        if len(texts) > 1:
            midpoint = max(1, len(texts) // 2)
            left = _translate_lines_recursive(
                texts[:midpoint],
                target_lang,
                model_name=model_name,
                context_note=context_note,
                glossary=glossary,
            )
            right = _translate_lines_recursive(
                texts[midpoint:],
                target_lang,
                model_name=model_name,
                context_note=context_note,
                glossary=glossary,
            )
            return left + right
        if DESKTOP:
            raise RuntimeError("DeepSeek 没有返回有效译文，请检查模型配置后重试") from error
        if ALLOW_PLACEHOLDER_ARTIFACTS:
            source = texts[0] if texts else ""
            return [f"（{target_lang}）{source}" if source else ""]
        return [texts[0]]


def translate_lines(
    texts: list[str],
    target_lang: str,
    *,
    model_name: str | None = None,
    context_note: str = "",
    glossary: str = "",
) -> list[str]:
    if not texts:
        return []

    return _translate_lines_recursive(
        texts,
        target_lang,
        model_name=model_name,
        context_note=context_note,
        glossary=glossary,
    )


def translate_srt(
    job_id: str,
    english_srt_path: Path,
    *,
    target_lang: str = DEFAULT_TARGET_LANG,
    model_name: str | None = None,
    context_note: str = "",
    glossary: str = "",
    progress_callback: Callable[[int, str, str | None], None] | None = None,
) -> Path:
    if progress_callback:
        progress_callback(8, "reading source subtitles", None)
    source_text = english_srt_path.read_text(encoding="utf-8")
    subtitles = split_srt_blocks(source_text)
    texts = [item.content for item in subtitles]
    chunk_size = 40
    chunks = [
        (index, texts[offset : offset + chunk_size])
        for index, offset in enumerate(range(0, len(texts), chunk_size))
    ]
    translated_chunks: list[list[str] | None] = [None] * len(chunks)
    completed_chunks = 0
    max_workers = min(TRANSLATE_PROMPT_CONCURRENCY, max(1, len(chunks)))

    def translate_chunk(chunk_texts: list[str]) -> list[str]:
        return _translate_lines_recursive(
            chunk_texts,
            target_lang,
            model_name=model_name,
            context_note=context_note,
            glossary=glossary,
        )

    if chunks:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(translate_chunk, chunk_texts): (chunk_index, chunk_texts)
                for chunk_index, chunk_texts in chunks
            }
            for future in as_completed(future_map):
                chunk_index, chunk_texts = future_map[future]
                translated_chunks[chunk_index] = future.result()
                completed_chunks += 1
                if progress_callback:
                    start_line = chunk_index * chunk_size + 1
                    end_line = start_line + len(chunk_texts) - 1
                    progress = 12 + int(76 * completed_chunks / max(1, len(chunks)))
                    progress_callback(
                        progress,
                        f"translating subtitles {start_line}-{end_line} of {len(texts)}",
                        None,
                    )
    translated_texts = [line for chunk in translated_chunks if chunk for line in chunk]
    if progress_callback:
        progress_callback(90, "merging translated subtitles", None)
    bilingual: list[srt.Subtitle] = []
    for index, subtitle in enumerate(subtitles, start=1):
        translation = translated_texts[index - 1] if index - 1 < len(translated_texts) else ""
        content = subtitle.content.strip()
        if translation and translation != content:
            content = f"{content}\n{translation}"
        bilingual.append(
            srt.Subtitle(
                index=index,
                start=subtitle.start,
                end=subtitle.end,
                content=content,
            )
        )
    path = artifact_path(job_id, "bilingual.srt")
    path.write_text(srt.compose(bilingual), encoding="utf-8")
    if progress_callback:
        progress_callback(100, "translation file ready", None)
    return path


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
        result = {
            "result_url": public_file_url(job_id, bilingual_path.name),
            "bilingual_srt_url": public_file_url(job_id, bilingual_path.name),
            "artifact_name": bilingual_path.name,
            "translate_model": request.translate_model,
            "subtitle_output_mode": request.subtitle_output_mode,
        }
        report_stage_progress(job_id, "translate", 100, "translation completed", status="succeeded", result=result, force=True)
    except Exception as error:
        fail_job(job_id, "translate", error)


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
            data = json.loads(stream.readline(65536))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def bilibili_source_metadata(source_value: str, source_video_url: str) -> dict[str, Any]:
    if not video_url_kind(source_value):
        return {}
    if source_video_url:
        try:
            _, path = resolve_local_artifact_from_url(source_video_url)
            data = read_source_download_metadata(path)
            if data.get("thumbnail"):
                return data
        except (OSError, ValueError):
            pass
    try:
        data = load_youtube_preview_metadata(source_value)
        return {"title": data.get("title"), "thumbnail": data.get("thumbnail") or best_thumbnail_url(data)}
    except (OSError, RuntimeError, ValueError):
        return {}


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
        if is_http_url(source_thumbnail):
            try:
                image = download_thumbnail_for_preview(job_id, source_thumbnail)
                cover_path = normalize_bilibili_cover_image(job_id, image)
                return cover_path, {
                    "cover_selection": cover_selection, "cover_mode": mode, "cover_source": "source_thumbnail",
                    "cover_asset_url": public_file_url(job_id, cover_path.name),
                }
            except (OSError, RuntimeError, httpx.HTTPError):
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
                request.upload_settings.auto_metadata and is_http_url(request.original_title)
                and request.bilibili_metadata is None
            ):
                source = bilibili_source_metadata(request.original_source, request.source_video_url)
                request.source_thumbnail = str(source.get("thumbnail") or "")
                request.original_title = str(source.get("title") or request.original_title)
            request.upload_settings, request.bilibili_metadata = desktop_bilibili.prepare_metadata(request)
            state = load_state(job_id)
            state.request.update({
                "original_title": request.original_title, "upload_settings": request.upload_settings.model_dump(),
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
        ext = str(item.get("ext") or "").lower()
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8090)
