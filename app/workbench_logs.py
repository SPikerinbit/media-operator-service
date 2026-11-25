"""Curated, human-readable stage log organizer for the Publish and Notes record views."""
from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any, Callable

from app import knowledge
from app import main as media

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_PROGRESS_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T[0-9:.+-]+(?:Z|[+-]\d{2}:\d{2})?)\t([a-z0-9_]+)\t(\d+)\t(.*)$"
)
_TRANSCRIBE_START_RE = re.compile(r"^starting transcription with\s+([^\s(]+)\s*(?:\(([^)]+)\))?", re.I)
_TRANSCRIBED_RE = re.compile(r"transcribed\s+([0-9.]+)s\s*/\s*([0-9.]+)s", re.I)
_GAPS_RE = re.compile(r"detected\s+(\d+)\s+suspicious gaps,\s*max gap\s+([0-9.]+)s", re.I)
_TRANSLATE_START_RE = re.compile(r"^starting translation with\s+(.+)$", re.I)
_TRANSLATING_RE = re.compile(r"^translating subtitles\s+(\d+)-(\d+)\s+of\s+(\d+)", re.I)
_RENDERED_RE = re.compile(r"^rendered\s+([0-9.]+)s\s*/\s*([0-9.]+)s", re.I)
_BILI_LINE_START_RE = re.compile(r"^starting bilibili uploader via\s+(.+)$", re.I)
_BILI_LINE_FAIL_RE = re.compile(r"^upload line\s+(\S+)\s+failed:\s*(.+)$", re.I)
_DOWNLOAD_PCT_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")

STAGE_ORDER = {
    "publish": ("download", "transcribe", "translate", "burn", "bilibili_upload"),
    "notes": ("download", "transcribe", "translate", "extract"),
}
STAGE_LABELS = {
    "download": "获取素材",
    "transcribe": "Whisper 转录",
    "translate": "生成译文",
    "burn": "烧录字幕",
    "bilibili_upload": "提交 B 站",
    "extract": "提取观点",
    "identify": "来源识别",
}
INFERENCE_LABELS = {
    "gpu_only": "严格 GPU",
    "auto": "自动",
    "batched": "批处理",
    "standard": "标准",
    "auto_repair": "自动修复",
}
NOTES_MODE_LABELS = {
    "summary": "摘要",
    "curated": "精华观点",
    "comprehensive": "大多数观点",
}
LANG_CLASS_LABELS = {
    "zh_native": "中文原文",
    "mixed": "中英混合",
    "foreign": "外语原文",
}
STRATEGY_LABELS = {
    "none": "中文原文，无需翻译",
    "direct_cross_lingual": "直接跨语提炼中文摘要",
    "cited_only": "跨语精选并仅译引用原句",
    "foreign_spans_only": "仅译外语片段并缓存复用",
    "full_cached": "分块译文与观点同步处理并缓存",
}
BILI_NOISE_EVENTS = {
    "PREUPLOAD",
    "PRE_CHUNK",
    "AFTER_CHUNK",
    "PRE_UPLOAD_CHUNK",
    "AFTER_UPLOAD_CHUNK",
    "PRE_PAGE",
    "AFTER_PAGE",
    "PRE_PAGE_SUBMIT",
    "AFTER_PAGE_SUBMIT",
    "PRE_UPLOAD",
    "AFTER_UPLOAD",
    "PRE_COVER",
    "PRE_SUBMIT",
    "PRE_CHUNK_FAILED",
}
_UPPER_EVENT_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", str(text or ""))


def _parse_iso(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _local_clock(iso_text: str) -> str:
    dt = _parse_iso(iso_text)
    if dt is None:
        return ""
    try:
        return dt.astimezone().strftime("%H:%M:%S")
    except OSError:
        return dt.strftime("%H:%M:%S")


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return ""
    whole = int(round(seconds))
    if whole < 1:
        return "<1 秒"
    if whole < 60:
        return f"{whole} 秒"
    minutes, rem = divmod(whole, 60)
    if minutes < 60:
        return f"{minutes} 分 {rem} 秒" if rem else f"{minutes} 分"
    hours, rem_min = divmod(minutes, 60)
    return f"{hours} 小时 {rem_min} 分" if rem_min else f"{hours} 小时"


def _clean_error_cause(payload: dict[str, Any]) -> str:
    cause = str(payload.get("cause") or "").strip()
    if not cause:
        return ""
    lower = cause.lower()
    if "empty translation content" in lower:
        if "finish_reason='length'" in lower or 'finish_reason="length"' in lower:
            return "诊断：模型输出达到长度上限，未返回正文内容"
        return "诊断：模型返回了空译文内容"
    if "timeout" in lower:
        return "诊断：请求超时"
    if "401" in lower or "403" in lower:
        return "诊断：接口鉴权失败，请检查密钥"
    if "429" in lower:
        return "诊断：接口触发限流，请稍后重试"
    return ""


def _parse_structured_rows(raw_lines: list[str], scrub: Callable[[str], str]) -> tuple[list[dict[str, Any]], list[str]]:
    structured: list[dict[str, Any]] = []
    plain: list[str] = []
    for raw_line in raw_lines:
        cleaned = scrub(strip_ansi(raw_line)).strip()
        if not cleaned:
            continue
        match = _PROGRESS_LINE_RE.match(cleaned)
        if not match:
            plain.append(cleaned)
            continue
        ts, stage_name, pct_text, detail = match.groups()
        msg, raw_part = (detail.split(" | ", 1) if " | " in detail else (detail, ""))
        structured.append({
            "time": ts,
            "stage": stage_name,
            "progress": int(pct_text),
            "message": msg.strip(),
            "raw": raw_part.strip(),
        })
    return structured, plain


def _emit(events: list[dict[str, Any]], time_iso: str, text: str, level: str = "info") -> None:
    clean = " ".join(str(text or "").split())
    if not clean:
        return
    if events and events[-1]["text"] == clean and events[-1]["level"] == level:
        return
    events.append({
        "time": time_iso,
        "clock": _local_clock(time_iso),
        "level": level,
        "text": clean,
    })


def _extract_failure_from_row(row: dict[str, Any]) -> tuple[str, str] | None:
    raw_part = row.get("raw") or ""
    if not raw_part.startswith("{"):
        return None
    try:
        payload = json.loads(raw_part)
    except ValueError:
        return None
    if isinstance(payload, dict) and payload.get("stage") and payload.get("type") and payload.get("message"):
        return str(payload.get("message") or row["message"]), _clean_error_cause(payload)
    return None


def _organize_download(rows: list[dict[str, Any]], stage_status: str) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    folded = 0
    download_ticks = 0
    latest_dl_pct = 0
    latest_dl_time = ""
    latest_dl_label = "正在下载素材"
    note_images = 0
    last_image_time = ""
    direct_attempts = 0
    last_direct_time = ""

    def flush_download_ticks(include_finished_note: bool = False) -> None:
        nonlocal download_ticks, folded
        if not download_ticks:
            return
        if stage_status == "running":
            _emit(events, latest_dl_time, f"{latest_dl_label}（当前 {latest_dl_pct}%）", "info")
            folded += max(0, download_ticks - 1)
        elif include_finished_note:
            _emit(events, latest_dl_time, f"{latest_dl_label}（{latest_dl_pct}%）", "info")
            folded += max(0, download_ticks - 1)
        else:
            folded += download_ticks
        download_ticks = 0

    def flush_note_images() -> None:
        nonlocal note_images, folded
        if not note_images:
            return
        _emit(events, last_image_time, f"已保存 {note_images} 张笔记图片", "info")
        folded += max(0, note_images - 1)
        note_images = 0

    for row in rows:
        ts, pct, msg = row["time"], row["progress"], row["message"]
        failure = _extract_failure_from_row(row)
        if failure:
            flush_note_images()
            if direct_attempts > 1:
                _emit(events, last_direct_time, f"已尝试从登录页面下载（共 {direct_attempts} 次）", "info")
                folded += max(0, direct_attempts - 1)
                direct_attempts = 0
            flush_download_ticks(include_finished_note=False)
            err_msg, cause_hint = failure
            _emit(events, ts, f"获取素材失败：{err_msg}", "error")
            if cause_hint:
                _emit(events, ts, cause_hint, "warn")
            continue

        lower = msg.lower()
        if msg in {"正在导入素材", "starting download"}:
            _emit(events, ts, "开始获取素材", "info")
        elif lower == "importing local source":
            _emit(events, ts, "开始导入本地素材", "info")
        elif msg == "正在保存图文笔记":
            _emit(events, ts, "开始保存图文笔记", "info")
        elif msg == "正在保存笔记图片":
            note_images += 1
            last_image_time = ts
        elif msg == "正在从登录页面下载":
            if pct <= 20:
                direct_attempts += 1
            last_direct_time = ts
            download_ticks += 1
            latest_dl_pct = pct
            latest_dl_time = ts
            latest_dl_label = "正在从登录页面下载"
        elif msg in {"正在下载素材", "正在下载节目音频"} or _DOWNLOAD_PCT_RE.search(msg):
            download_ticks += 1
            latest_dl_pct = pct
            latest_dl_time = ts
            latest_dl_label = "正在下载节目音频" if msg == "正在下载节目音频" else "正在下载素材"
        elif "merging video and audio" in lower:
            flush_download_ticks(include_finished_note=False)
            _emit(events, ts, "正在合并音视频流", "info")
        elif msg in {"素材已导入", "download completed", "local source imported", "图文笔记已保存"}:
            flush_note_images()
            flush_download_ticks(include_finished_note=False)
            label = {
                "download completed": "素材下载完成",
                "local source imported": "本地素材已导入",
                "图文笔记已保存": "图文笔记已保存",
            }.get(msg, "素材已导入")
            # Avoid duplicate "图文笔记已保存" immediately followed by "素材已导入"
            if msg == "素材已导入" and events and events[-1]["text"] == "图文笔记已保存":
                folded += 1
            else:
                _emit(events, ts, label, "success")
        else:
            flush_note_images()
            flush_download_ticks(include_finished_note=False)
            _emit(events, ts, msg, "info")

    flush_note_images()
    if direct_attempts > 1 and stage_status != "running":
        _emit(events, last_direct_time, f"从登录页面下载（尝试 {direct_attempts} 次）", "info")
        folded += max(0, direct_attempts - 1)
    flush_download_ticks(include_finished_note=(stage_status == "running"))
    return events, folded


def _clean_whisper_message(msg: str, pct: int) -> str:
    if "\ufffd" in msg:
        if pct <= 10:
            return "NVIDIA GPU · 读取预解码音频" if "NVIDIA GPU" in msg else "读取预解码音频"
        model_match = re.search(r"Whisper\s+([^\s·]+)", msg)
        device = "NVIDIA GPU" if "NVIDIA GPU" in msg else ("CPU" if "CPU" in msg else "")
        if model_match:
            return f"加载 Whisper {model_match.group(1)}" + (f"（{device}）" if device else "")
        return ""
    return msg


def _organize_transcribe(rows: list[dict[str, Any]], stage_status: str) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    folded = 0
    tick_count = 0
    last_pos = 0.0
    total_dur = 0.0
    last_tick_pct = 0
    last_tick_time = ""
    heartbeat_count = 0
    last_heartbeat = ("", "")
    wait_count = 0
    last_wait = ("", "")
    had_model_load = False

    def flush_waits() -> None:
        nonlocal wait_count, folded
        if wait_count:
            _emit(events, last_wait[0], last_wait[1], "info")
            folded += max(0, wait_count - 1)
            wait_count = 0

    def flush_ticks(done: bool) -> None:
        nonlocal tick_count, folded
        if not tick_count:
            return
        if done:
            dur_str = format_duration(total_dur)
            _emit(events, last_tick_time, f"语音识别完成（音频时长 {dur_str}）" if dur_str else "语音识别完成", "info")
        else:
            _emit(events, last_tick_time, f"正在识别语音（{last_pos:.1f}s / {total_dur:.1f}s · {last_tick_pct}%）", "info")
        folded += max(0, tick_count - 1)
        tick_count = 0

    for row in rows:
        ts, pct = row["time"], row["progress"]
        msg = _clean_whisper_message(row["message"], pct)
        failure = _extract_failure_from_row(row)
        if failure:
            flush_waits()
            flush_ticks(done=False)
            err_msg, _ = failure
            _emit(events, ts, f"转录失败：{err_msg}", "error")
            continue
        if not msg:
            folded += 1
            continue

        start_match = _TRANSCRIBE_START_RE.match(msg)
        if start_match:
            model_name = start_match.group(1)
            mode_raw = (start_match.group(2) or "").strip()
            mode_label = INFERENCE_LABELS.get(mode_raw, mode_raw)
            suffix = f" · {mode_label}" if mode_label else ""
            _emit(events, ts, f"开始转录（模型 {model_name}{suffix}）", "info")
            continue

        if "等待显卡队列" in msg:
            wait_count += 1
            last_wait = (ts, msg)
            continue

        if "最近阶段活动" in msg:
            heartbeat_count += 1
            last_heartbeat = (ts, msg)
            continue

        tick_match = _TRANSCRIBED_RE.search(msg)
        if tick_match:
            flush_waits()
            tick_count += 1
            last_pos = float(tick_match.group(1))
            total_dur = float(tick_match.group(2))
            last_tick_pct = pct
            last_tick_time = ts
            continue

        lower = msg.lower()
        if "提取音频" in msg:
            _emit(events, ts, msg, "info")
        elif "读取预解码音频" in msg or "decoding audio for whisper" in lower or "audio decoded" in lower:
            folded += 1
        elif "加载 whisper" in lower:
            flush_waits()
            had_model_load = True
            _emit(events, ts, msg.replace(" · ", "（") + ("）" if " · " in msg and "）" not in msg else ""), "info")
        elif "starting batched transcription" in lower:
            flush_waits()
            device = "NVIDIA GPU" if "NVIDIA GPU" in msg else ("CPU" if "CPU" in msg else "")
            if not had_model_load and device:
                _emit(events, ts, f"使用 {device} 开始批处理语音识别", "info")
            else:
                _emit(events, ts, "开始批处理语音识别", "info")
        elif "starting standard transcription" in lower:
            flush_waits()
            _emit(events, ts, "开始标准模式语音识别", "info")
        elif "suspicious gaps" in lower:
            flush_ticks(done=True)
            gap_match = _GAPS_RE.search(msg)
            if gap_match:
                _emit(events, ts, f"检测到 {gap_match.group(1)} 处较长静音间隔（最长 {gap_match.group(2)}s）", "info")
            else:
                folded += 1
        elif "writing subtitle artifacts" in lower or "transcription artifacts ready" in lower:
            flush_ticks(done=True)
            folded += 1
        elif lower == "transcription completed":
            flush_waits()
            flush_ticks(done=True)
            _emit(events, ts, "转录完成，原文字幕已生成", "success")
        elif "已复用原文字幕" in msg:
            _emit(events, ts, "已复用原文字幕", "success")
        elif any(k in msg for k in ("改用", "失败", "重试", "降级", "取消", "显存")):
            flush_waits()
            flush_ticks(done=False)
            _emit(events, ts, msg, "warn")
        else:
            flush_waits()
            _emit(events, ts, msg, "info")

    flush_waits()
    if tick_count:
        flush_ticks(done=(stage_status == "succeeded"))
    if heartbeat_count:
        if stage_status == "running":
            _emit(events, last_heartbeat[0], last_heartbeat[1], "info")
            folded += max(0, heartbeat_count - 1)
        else:
            folded += heartbeat_count
    return events, folded


def _organize_translate(rows: list[dict[str, Any]], stage_status: str) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    folded = 0
    chunks_done = 0
    total_lines = 0
    last_chunk_pct = 0
    last_chunk_time = ""

    def flush_chunks(done: bool) -> None:
        nonlocal chunks_done, folded
        if not chunks_done:
            return
        if done:
            _emit(events, last_chunk_time, f"已完成 {total_lines} 条字幕翻译（共 {chunks_done} 批）", "info")
        else:
            _emit(events, last_chunk_time, f"正在翻译字幕（已完成 {chunks_done} 批，共 {total_lines} 条 · {last_chunk_pct}%）", "info")
        folded += max(0, chunks_done - 1)
        chunks_done = 0

    for row in rows:
        ts, pct, msg = row["time"], row["progress"], row["message"]
        failure = _extract_failure_from_row(row)
        if failure:
            flush_chunks(done=False)
            err_msg, cause_hint = failure
            _emit(events, ts, f"翻译失败：{err_msg}", "error")
            if cause_hint:
                _emit(events, ts, cause_hint, "warn")
            continue

        start_match = _TRANSLATE_START_RE.match(msg)
        if start_match:
            _emit(events, ts, f"开始翻译字幕（模型 {start_match.group(1).strip()}）", "info")
            continue

        chunk_match = _TRANSLATING_RE.match(msg)
        if chunk_match:
            chunks_done += 1
            total_lines = max(total_lines, int(chunk_match.group(3)))
            last_chunk_pct = pct
            last_chunk_time = ts
            continue

        lower = msg.lower()
        if lower in {"reading source subtitles", "merging translated subtitles", "translation file ready"}:
            folded += 1
        elif lower == "translation skipped for english-only output":
            _emit(events, ts, "原文字幕模式，已跳过翻译", "info")
        elif lower == "translation completed":
            flush_chunks(done=True)
            _emit(events, ts, "译文生成完成", "success")
        else:
            _emit(events, ts, msg, "info")

    if chunks_done:
        flush_chunks(done=(stage_status == "succeeded"))
    return events, folded


def _organize_burn(rows: list[dict[str, Any]], stage_status: str) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    folded = 0
    render_ticks = 0
    last_pos = 0.0
    total_dur = 0.0
    last_pct = 0
    last_time = ""
    wait_count = 0
    last_wait = ("", "")

    def flush_waits() -> None:
        nonlocal wait_count, folded
        if wait_count:
            _emit(events, last_wait[0], last_wait[1], "info")
            folded += max(0, wait_count - 1)
            wait_count = 0

    def flush_renders(done: bool) -> None:
        nonlocal render_ticks, folded
        if not render_ticks:
            return
        if done:
            dur_str = format_duration(total_dur)
            _emit(events, last_time, f"视频压制完成（时长 {dur_str}）" if dur_str else "视频压制完成", "info")
        else:
            _emit(events, last_time, f"正在压制视频（{last_pos:.1f}s / {total_dur:.1f}s · {last_pct}%）", "info")
        folded += max(0, render_ticks - 1)
        render_ticks = 0

    for row in rows:
        ts, pct, msg = row["time"], row["progress"], row["message"]
        failure = _extract_failure_from_row(row)
        if failure:
            flush_waits()
            flush_renders(done=False)
            err_msg, _ = failure
            _emit(events, ts, f"烧录失败：{err_msg}", "error")
            continue

        if "等待显卡队列" in msg:
            wait_count += 1
            last_wait = (ts, msg)
            continue

        render_match = _RENDERED_RE.match(msg)
        if render_match:
            flush_waits()
            render_ticks += 1
            last_pos = float(render_match.group(1))
            total_dur = float(render_match.group(2))
            last_pct = pct
            last_time = ts
            continue

        lower = msg.lower()
        if lower == "starting subtitle burn":
            _emit(events, ts, "开始准备字幕样式与画幅", "info")
        elif lower in {"probing video and building subtitle style", "finalizing output video"}:
            folded += 1
        elif msg == "NVIDIA NVENC 编码":
            _emit(events, ts, "编码方式：NVIDIA NVENC 硬件编码", "info")
        elif msg == "CPU 编码":
            _emit(events, ts, "编码方式：CPU 软件编码", "info")
        elif lower == "subtitle burn completed":
            flush_waits()
            flush_renders(done=True)
            _emit(events, ts, "字幕烧录完成，成片已生成", "success")
        elif any(k in msg for k in ("失败", "改用")):
            flush_waits()
            flush_renders(done=False)
            _emit(events, ts, msg, "warn")
        else:
            _emit(events, ts, msg, "info")

    flush_waits()
    if render_ticks:
        flush_renders(done=(stage_status == "succeeded"))
    return events, folded


def _organize_bilibili(rows: list[dict[str, Any]], stage_status: str, result: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    folded = 0
    chunk_events = 0
    last_chunk_pct = 20
    last_chunk_time = ""
    cover_uploaded_time = ""
    submitted_bvid = str(result.get("bvid") or "").strip()
    completed_emitted = False

    def flush_chunks(done: bool) -> None:
        nonlocal chunk_events, folded
        if not chunk_events:
            return
        if done:
            _emit(events, last_chunk_time, "视频分片上传完成", "info")
        else:
            _emit(events, last_chunk_time, f"正在上传视频分片（{last_chunk_pct}%）", "info")
        folded += max(0, chunk_events - 1)
        chunk_events = 0

    for row in rows:
        ts, pct, msg, raw_part = row["time"], row["progress"], row["message"], row["raw"]
        failure = _extract_failure_from_row(row)
        if failure:
            flush_chunks(done=False)
            err_msg, _ = failure
            _emit(events, ts, f"投稿失败：{err_msg}", "error")
            continue

        lower = msg.lower()
        if msg == "准备来源封面和投稿信息":
            _emit(events, ts, msg, "info")
            continue
        if lower == "waiting for upload slot":
            if stage_status == "running" and row is rows[-1]:
                _emit(events, ts, "等待上传通道", "info")
            else:
                folded += 1
            continue
        if lower == "extracting upload cover":
            _emit(events, ts, "已准备投稿封面", "info")
            continue
        if lower.startswith("using ") and lower.endswith(" cover"):
            folded += 1
            continue

        line_start = _BILI_LINE_START_RE.match(msg)
        if line_start:
            _emit(events, ts, f"开始上传视频（线路 {line_start.group(1).strip()}）", "info")
            continue

        line_fail = _BILI_LINE_FAIL_RE.match(msg)
        if line_fail:
            flush_chunks(done=False)
            _emit(events, ts, f"线路 {line_fail.group(1)} 上传失败，切换重试：{line_fail.group(2).strip()[:120]}", "warn")
            continue

        if "season binding failed" in lower:
            _emit(events, ts, "合集绑定失败，已改用普通投稿重试", "warn")
            continue

        if lower == "bilibili upload skipped":
            _emit(events, ts, "已跳过 B 站投稿（仅保留本地成片）", "info")
            continue

        if lower == "bilibili upload completed":
            flush_chunks(done=True)
            if cover_uploaded_time:
                _emit(events, cover_uploaded_time, "投稿封面上传完成", "info")
                cover_uploaded_time = ""
            if not completed_emitted:
                suffix = f"（{submitted_bvid}）" if submitted_bvid else ""
                _emit(events, ts, f"投稿完成{suffix}", "success")
                completed_emitted = True
            else:
                folded += 1
            continue

        # Parse bilibili_api __ALL__ events
        event_name = msg.split(":", 1)[0].strip().upper()
        if raw_part.startswith("{"):
            try:
                parsed_raw = json.loads(raw_part)
                ev = parsed_raw.get("event") if isinstance(parsed_raw, dict) else None
                if isinstance(ev, dict):
                    event_name = str(ev.get("name") or event_name).upper()
                    ids = media.extract_bilibili_submission_ids(ev)
                    if ids.get("bvid"):
                        submitted_bvid = str(ids["bvid"])
            except ValueError:
                pass

        if event_name in BILI_NOISE_EVENTS or (_UPPER_EVENT_RE.match(event_name) and event_name not in {"AFTER_COVER", "AFTER_SUBMIT", "COMPLETE", "FAILED"}):
            chunk_events += 1
            last_chunk_pct = max(last_chunk_pct, pct)
            last_chunk_time = ts
            continue
        if event_name == "AFTER_COVER":
            cover_uploaded_time = ts
            folded += 1
            continue
        if event_name in {"AFTER_SUBMIT", "COMPLETE"}:
            folded += 1
            continue
        if event_name == "FAILED":
            flush_chunks(done=False)
            _emit(events, ts, msg, "warn")
            continue
        if lower.startswith("adding archive to "):
            _emit(events, ts, "正在将稿件加入合集/系列", "info")
            continue

        _emit(events, ts, msg, "info")

    if chunk_events:
        flush_chunks(done=(stage_status == "succeeded"))
    if cover_uploaded_time:
        _emit(events, cover_uploaded_time, "投稿封面上传完成", "info")
    return events, folded


def _organize_stage_rows(stage: str, rows: list[dict[str, Any]], stage_status: str, result: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    if stage == "download":
        return _organize_download(rows, stage_status)
    if stage == "transcribe":
        return _organize_transcribe(rows, stage_status)
    if stage == "translate":
        return _organize_translate(rows, stage_status)
    if stage == "burn":
        return _organize_burn(rows, stage_status)
    if stage == "bilibili_upload":
        return _organize_bilibili(rows, stage_status, result)
    events: list[dict[str, Any]] = []
    for row in rows:
        failure = _extract_failure_from_row(row)
        if failure:
            _emit(events, row["time"], failure[0], "error")
        else:
            _emit(events, row["time"], row["message"], "info")
    return events, 0


def _note_run_for(transcript_id: Any, preferred_mode: str = "") -> dict[str, Any] | None:
    if not transcript_id:
        return None
    try:
        tid = int(transcript_id)
    except (TypeError, ValueError):
        return None
    try:
        with knowledge.database() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='note_run'").fetchone()
            if not exists:
                return None
            row = None
            if preferred_mode:
                row = db.execute(
                    "SELECT * FROM note_run WHERE transcript_id=? AND mode=? ORDER BY updated DESC, rowid DESC LIMIT 1",
                    (tid, preferred_mode),
                ).fetchone()
            if row is None:
                row = db.execute(
                    "SELECT * FROM note_run WHERE transcript_id=? ORDER BY updated DESC, rowid DESC LIMIT 1",
                    (tid,),
                ).fetchone()
            if not row:
                return None
            counts = db.execute(
                "SELECT count(*), sum(status='done') FROM note_node WHERE run=? AND cue IS NOT NULL AND status!='split'",
                (row["id"],),
            ).fetchone()
            return {**dict(row), "total_blocks": counts[0] or 0, "completed_blocks": counts[1] or 0}
    except Exception:
        return None


def _extract_ytdlp_failure_line(folder: Any, scrub: Callable[[str], str]) -> str:
    if folder is None:
        return ""
    for name in ("yt-dlp.err.log", "yt-dlp.out.log"):
        path = folder / name
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for raw_line in reversed(lines):
            text = scrub(strip_ansi(raw_line)).strip()
            if text.startswith("ERROR:"):
                return text[:180]
    return ""


def raw_log_lines(entry: dict[str, Any], scrub: Callable[[str], str]) -> list[str]:
    lines: list[str] = []
    task = entry.get("task") or {}
    for job_id in (task.get("stage_jobs") or {}).values():
        path = media.stage_progress_log_path(job_id)
        if path.is_file():
            lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
        folder = media.job_dir(job_id) if re.fullmatch(r"[a-zA-Z0-9_-]+", str(job_id)) else None
        if folder is not None:
            for name in ("yt-dlp.err.log", "yt-dlp.out.log"):
                extra = folder / name
                if extra.is_file():
                    lines.extend(extra.read_text(encoding="utf-8", errors="replace").splitlines())
    return [scrub(strip_ansi(line)) for line in lines if str(line).strip()]


def _stage_status_of(stage: str, detail: dict[str, Any], entry: dict[str, Any], task: dict[str, Any], has_error: bool) -> str:
    if detail.get("reused"):
        return "reused"
    if detail.get("skipped"):
        return "skipped"
    raw = str(detail.get("status") or "").strip()
    if raw in {"succeeded", "running", "failed", "queued"}:
        return raw
    if has_error:
        return "failed"
    if task.get("status") == "failed" and task.get("stage") == stage:
        return "failed"
    if task.get("status") == "running" and task.get("stage") == stage:
        return "running"
    if task.get("status") == "succeeded":
        return "succeeded"
    return "pending"


def _compute_duration(rows: list[dict[str, Any]]) -> float | None:
    times = [_parse_iso(r["time"]) for r in rows]
    valid = [t for t in times if t is not None]
    if len(valid) < 2:
        return None
    delta = (valid[-1] - valid[0]).total_seconds()
    return max(0.0, delta)


def _stage_order_for(lane: str, stage_jobs: dict[str, Any], stage_details: dict[str, Any], planned: list[str]) -> list[str]:
    ordered: list[str] = []
    for name in STAGE_ORDER.get(lane, ()):
        if name in stage_jobs or name in stage_details or name in planned:
            ordered.append(name)
    for name in [*stage_jobs.keys(), *stage_details.keys()]:
        if name not in ordered:
            ordered.append(name)
    return ordered


def _pre_batch_stage(entry: dict[str, Any], scrub: Callable[[str], str]) -> dict[str, Any]:
    lane = entry.get("lane") or "publish"
    status = entry.get("status") or "ready"
    platform = entry.get("platform") or "来源"
    created = str(entry.get("created_at") or "")
    msg = scrub(str(entry.get("message") or "")).strip()
    if status == "ready":
        text = (
            f"已接收来自 {platform} 的来信，等待选择摘录档位后开始整理"
            if lane == "notes"
            else f"已识别 {platform} 视频，等待确认设置后开始处理"
        )
        level, st = "info", "pending"
    elif status == "identifying":
        text, level, st = "正在识别素材来源信息", "info", "running"
    elif status == "duplicate":
        text, level, st = msg or "已在队列中，未重复创建", "info", "skipped"
    elif status == "rejected":
        text, level, st = msg or "来源无法处理，已退回", "error", "failed"
    elif status == "blocked":
        text, level, st = msg or "处理暂未继续，请检查提示后重试", "warn", "failed"
    elif status == "cancelled":
        text, level, st = msg or "任务已取消", "warn", "skipped"
    elif status == "succeeded":
        text, level, st = msg or ("笔记已完成" if lane == "notes" else "处理已完成"), "success", "succeeded"
    else:
        text, level, st = msg or "等待处理", "info", "pending"
    return {
        "stage": "identify",
        "label": STAGE_LABELS["identify"],
        "status": st,
        "progress": 100 if st in {"succeeded", "skipped"} else 0,
        "duration_seconds": None,
        "duration_label": "",
        "collapsed_count": 0,
        "events": [{"time": created, "clock": _local_clock(created), "level": level, "text": text}],
    }


def build_entry_log(
    entry: dict[str, Any],
    *,
    offset: int = 0,
    limit: int = 80,
    raw: bool = False,
    scrub: Callable[[str], str],
) -> dict[str, Any]:
    offset = max(0, offset)
    limit = min(200, max(1, limit))

    raw_lines = raw_log_lines(entry, scrub)
    if raw:
        return {
            "offset": offset,
            "limit": limit,
            "total": len(raw_lines),
            "lines": raw_lines[offset:offset + limit],
            "raw": True,
        }

    lane = entry.get("lane") or "publish"
    task = entry.get("task") or {}
    result = entry.get("result") or task.get("result") or {}
    stage_jobs = dict(task.get("stage_jobs") or {})
    stage_details = dict(task.get("stage_details") or {})
    planned = list(task.get("planned_stages") or [])
    reuse_map = {
        r.get("stage"): r.get("origin_lane")
        for r in (entry.get("reuse") or result.get("reuse") or [])
        if isinstance(r, dict) and r.get("stage")
    }

    # Check if this entry only has plain unstructured log lines (preserves exact legacy pagination contract).
    plain_only = True
    raw_by_stage: dict[str, tuple[list[dict[str, Any]], list[str], int]] = {}
    for stage_name, job_id in stage_jobs.items():
        path = media.stage_progress_log_path(job_id)
        file_lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
        structured_rows, plain_rows = _parse_structured_rows(file_lines, scrub)
        extra_count = 0
        folder = media.job_dir(job_id) if re.fullmatch(r"[a-zA-Z0-9_-]+", str(job_id)) else None
        if folder is not None:
            for extra_name in ("yt-dlp.err.log", "yt-dlp.out.log"):
                extra_path = folder / extra_name
                if extra_path.is_file():
                    extra_count += sum(
                        1 for ln in extra_path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()
                    )
        if structured_rows:
            plain_only = False
        raw_by_stage[stage_name] = (structured_rows, plain_rows, extra_count)

    if plain_only and raw_by_stage and not stage_details and any(plain for _, plain, _ in raw_by_stage.values()):
        plain_all: list[str] = []
        stages_out: list[dict[str, Any]] = []
        for stage_name, (_, plain_rows, extra_count) in raw_by_stage.items():
            if not plain_rows:
                continue
            plain_all.extend(plain_rows)
            stages_out.append({
                "stage": stage_name,
                "label": STAGE_LABELS.get(stage_name, stage_name),
                "status": _stage_status_of(stage_name, {}, entry, task, False),
                "progress": 0,
                "duration_seconds": None,
                "duration_label": "",
                "collapsed_count": extra_count,
                "events": [{"time": "", "clock": "", "level": "info", "text": line} for line in plain_rows],
            })
        return {
            "offset": offset,
            "limit": limit,
            "total": len(plain_all),
            "lines": plain_all[offset:offset + limit],
            "raw_total": len(raw_lines),
            "folded_count": max(0, len(raw_lines) - len(plain_all)),
            "stages": stages_out,
            "overview": {
                "lane": lane,
                "status": entry.get("status") or "",
                "total_duration_label": "",
                "folded_count": max(0, len(raw_lines) - len(plain_all)),
                "raw_total": len(raw_lines),
            },
        }

    stages_out = []
    curated_lines: list[str] = []
    total_duration = 0.0
    has_any_duration = False

    stage_names = _stage_order_for(lane, stage_jobs, stage_details, planned)
    note_run = _note_run_for(result.get("transcript_id"), str(entry.get("execution_mode") or entry.get("notes_mode") or "")) if lane == "notes" else None
    if lane == "notes" and "extract" not in stage_names:
        if note_run is not None or result.get("note_notice") or entry.get("stage") == "extract" or entry.get("status") == "succeeded":
            stage_names.append("extract")

    for stage_name in stage_names:
        detail = dict(stage_details.get(stage_name) or {})
        structured_rows, plain_rows, extra_count = raw_by_stage.get(stage_name, ([], [], 0))
        has_err_row = any(_extract_failure_from_row(r) is not None for r in structured_rows)
        st_status = _stage_status_of(stage_name, detail, entry, task, has_err_row)
        events: list[dict[str, Any]] = []
        folded = extra_count

        if structured_rows:
            events, stage_folded = _organize_stage_rows(stage_name, structured_rows, st_status, result)
            folded += stage_folded
        elif plain_rows:
            for line in plain_rows:
                _emit(events, "", line, "info")

        if stage_name == "download" and st_status == "failed" and not any(e["level"] == "error" for e in events):
            job_id = stage_jobs.get("download")
            folder = media.job_dir(job_id) if job_id and re.fullmatch(r"[a-zA-Z0-9_-]+", str(job_id)) else None
            err_line = scrub(str(detail.get("message") or (task.get("error") or {}).get("message") or ""))
            if not err_line:
                err_line = _extract_ytdlp_failure_line(folder, scrub)
            if err_line:
                _emit(events, str(detail.get("updated_at") or ""), f"获取素材失败：{err_line}", "error")

        # Synthesize reused / skipped / notes-extract stages that have no progress.log.txt
        if not events:
            updated_at = str(detail.get("updated_at") or "")
            detail_msg = scrub(str(detail.get("message") or "")).strip()
            if st_status == "reused":
                origin = reuse_map.get(stage_name) or detail.get("origin_lane")
                origin_label = {"publish": "投稿", "notes": "笔记"}.get(str(origin or ""), "")
                base_msg = detail_msg or (
                    "已复用" + {"download": "源媒体", "transcribe": "原文字幕", "translate": "译文", "burn": "成片", "extract": "观点摘录"}.get(stage_name, "结果")
                )
                if origin_label and origin_label not in base_msg:
                    base_msg = f"{base_msg}（来自{origin_label}记录）"
                _emit(events, updated_at, base_msg, "success")
            elif st_status == "skipped":
                _emit(events, updated_at, detail_msg or "本阶段已跳过", "info")
            elif stage_name == "extract":
                mode_key = str((note_run or {}).get("mode") or entry.get("execution_mode") or entry.get("notes_mode") or "")
                mode_label = NOTES_MODE_LABELS.get(mode_key, mode_key)
                model_name = str((note_run or {}).get("model") or "").strip()
                if mode_label:
                    _emit(events, "", f"整理档位：{mode_label}" + (f" · 模型 {model_name}" if model_name else ""), "info")
                if note_run:
                    lang_label = LANG_CLASS_LABELS.get(str(note_run.get("detected_language") or ""), "")
                    strat_label = STRATEGY_LABELS.get(str(note_run.get("translation_strategy") or ""), "")
                    if lang_label or strat_label:
                        parts = [p for p in (f"文档语言：{lang_label}" if lang_label else "", f"策略：{strat_label}" if strat_label else "") if p]
                        _emit(events, "", " · ".join(parts), "info")
                    total_blocks = int(note_run.get("total_blocks") or 0)
                    done_blocks = int(note_run.get("completed_blocks") or 0)
                    total_tokens = int(note_run.get("input_tokens") or 0) + int(note_run.get("output_tokens") or 0)
                    saved_tokens = int(note_run.get("saved_tokens") or 0)
                    if total_blocks > 0 or total_tokens > 0:
                        metrics = []
                        if total_blocks > 0:
                            metrics.append(f"正文分块 {done_blocks}/{total_blocks}")
                        if total_tokens > 0:
                            metrics.append(f"用量 {total_tokens:,} token")
                        if saved_tokens > 0:
                            metrics.append("已复用省额")
                        _emit(events, "", " · ".join(metrics), "info")
                notice_text = scrub(str(result.get("note_notice") or detail_msg or "")).strip()
                run_err = scrub(str((note_run or {}).get("error") or "")).strip()
                if st_status == "failed" or (entry.get("status") in {"failed", "blocked"} and entry.get("stage") == "extract"):
                    st_status = "failed"
                    err_text = run_err or scrub(str(entry.get("message") or "")) or "观点提取未完成"
                    _emit(events, updated_at, f"提取失败：{err_text}", "error")
                elif notice_text:
                    _emit(events, updated_at, notice_text, "success" if st_status == "succeeded" else "info")
                elif st_status == "running":
                    _emit(events, updated_at, "正在提取观点", "info")
                elif st_status == "succeeded":
                    _emit(events, updated_at, "观点整理完成", "success")
            elif detail_msg:
                lvl = "error" if st_status == "failed" else ("success" if st_status == "succeeded" else "info")
                _emit(events, updated_at, detail_msg, lvl)
            elif st_status == "failed":
                err_msg = scrub(str((task.get("error") or {}).get("message") or entry.get("message") or "阶段处理失败"))
                _emit(events, updated_at, err_msg, "error")

        # Skip completely empty pending stages that haven't started yet unless nothing else exists
        if not events:
            continue

        duration = _compute_duration(structured_rows)
        if duration is not None:
            total_duration += duration
            has_any_duration = True

        stage_label = STAGE_LABELS.get(stage_name, stage_name)
        stage_entry = {
            "stage": stage_name,
            "label": stage_label,
            "status": st_status,
            "progress": int(detail.get("progress") or (100 if st_status in {"succeeded", "reused", "skipped"} else 0)),
            "duration_seconds": round(duration, 1) if duration is not None else None,
            "duration_label": format_duration(duration) if duration is not None else "",
            "collapsed_count": folded,
            "events": events,
        }
        stages_out.append(stage_entry)
        for ev in events:
            prefix = f"[{stage_label}]"
            if ev["clock"]:
                prefix = f"{ev['clock']} {prefix}"
            curated_lines.append(f"{prefix} {ev['text']}")

    if not stages_out:
        pre = _pre_batch_stage(entry, scrub)
        stages_out.append(pre)
        for ev in pre["events"]:
            prefix = f"[{pre['label']}]"
            if ev["clock"]:
                prefix = f"{ev['clock']} {prefix}"
            curated_lines.append(f"{prefix} {ev['text']}")

    total_folded = sum(int(s.get("collapsed_count") or 0) for s in stages_out)
    return {
        "offset": offset,
        "limit": limit,
        "total": len(curated_lines),
        "lines": curated_lines[offset:offset + limit],
        "raw_total": len(raw_lines),
        "folded_count": total_folded,
        "stages": stages_out,
        "overview": {
            "lane": lane,
            "status": entry.get("status") or "",
            "total_duration_label": format_duration(total_duration) if has_any_duration else "",
            "folded_count": total_folded,
            "raw_total": len(raw_lines),
        },
    }
