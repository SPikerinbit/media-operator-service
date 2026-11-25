"""Process-wide lane-fair, VRAM-aware admission for GPU workers and hardware encoding."""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
import os
import subprocess
import threading
import time
from typing import Any, Callable


WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
RELEASE_COOLDOWN_SECONDS = max(0.0, float(os.getenv("MEDIA_GPU_RELEASE_COOLDOWN", "0.2")))

MODEL_VRAM_MB: dict[str, int] = {
    "tiny": 600,
    "base": 900,
    "small": 1400,
    "medium": 2800,
    "large-v2": 4800,
    "large-v3": 4800,
    "large-v3-turbo": 3400,
}

LANE_LABELS = {
    "notes": "笔记线",
    "publish": "投稿线",
    "other": "任务",
}

OPERATION_LABELS = {
    "transcribe": "语音转录",
    "burn": "字幕压制",
    "gpu": "显卡计算",
}


@dataclass
class _Ticket:
    lane: str
    operation: str
    label: str
    enqueued_at: float
    started_at: float = 0.0


_condition = threading.Condition()
_waiting: deque[_Ticket] = deque()
_active: _Ticket | None = None
_last_lane: str | None = None
_cooldown_until: float = 0.0

_vram_lock = threading.Lock()
_vram_cache: tuple[float, dict[str, int] | None] = (0.0, None)


def _normalize_lane(lane: str | None) -> str:
    value = str(lane or "other").strip().lower()
    return value if value in {"notes", "publish"} else "other"


def _holder_payload(ticket: _Ticket | None) -> dict[str, Any] | None:
    if ticket is None:
        return None
    return {
        "lane": ticket.lane,
        "operation": ticket.operation,
        "label": ticket.label,
        "elapsed_seconds": round(max(0.0, time.perf_counter() - ticket.started_at), 1) if ticket.started_at else 0.0,
    }


def describe_holder(holder: dict[str, Any] | None) -> str:
    if not holder:
        return "显卡任务"
    lane_text = LANE_LABELS.get(str(holder.get("lane") or "other"), "任务")
    op_text = OPERATION_LABELS.get(str(holder.get("operation") or "gpu"), "显卡计算")
    return f"{lane_text} · {op_text}"


def _next_candidate() -> _Ticket | None:
    if not _waiting:
        return None
    lanes = {ticket.lane for ticket in _waiting}
    if len(lanes) > 1 and _last_lane in lanes:
        for ticket in _waiting:
            if ticket.lane != _last_lane:
                return ticket
    return _waiting[0]


def _queue_position(ticket: _Ticket) -> int:
    position = 0
    for item in _waiting:
        if item is _active:
            continue
        position += 1
        if item is ticket:
            return position
    return max(1, position)


def query_vram_mb(*, force: bool = False) -> dict[str, int] | None:
    """Query primary NVIDIA GPU total/free VRAM in MiB via nvidia-smi."""
    global _vram_cache
    now = time.perf_counter()
    with _vram_lock:
        if not force and now - _vram_cache[0] < 2.0:
            return dict(_vram_cache[1]) if _vram_cache[1] is not None else None
    result: dict[str, int] | None = None
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            creationflags=WINDOW_FLAGS,
        )
        if completed.returncode == 0:
            for line in completed.stdout.splitlines():
                parts = [part.strip() for part in line.split(",")]
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    total_mb = int(parts[0])
                    free_mb = int(parts[1])
                    if total_mb > 0:
                        result = {
                            "total_mb": total_mb,
                            "free_mb": free_mb,
                            "used_mb": max(0, total_mb - free_mb),
                        }
                        break
    except (OSError, subprocess.TimeoutExpired, ValueError):
        result = None
    with _vram_lock:
        _vram_cache = (time.perf_counter(), result)
    return dict(result) if result is not None else None


def plan_whisper_gpu(
    model_name: str,
    default_batch_size: int = 8,
    *,
    vram: dict[str, int] | None = None,
    probe_vram: bool = True,
) -> dict[str, Any]:
    """Select an initial Whisper CUDA mode and batch size based on available VRAM."""
    name = (model_name or "small").strip().lower()
    base_mb = MODEL_VRAM_MB.get(name, 2000)
    preferred_batch = max(int(default_batch_size or 1), 8) if name in {"tiny", "base", "small"} else max(int(default_batch_size or 1), 1)
    reading = vram if vram is not None else (query_vram_mb(force=True) if probe_vram else None)
    if not reading or not reading.get("free_mb"):
        return {
            "mode": "batched",
            "batch_size": preferred_batch,
            "vram": reading,
            "base_mb": base_mb,
            "headroom_mb": None,
            "reason": "vram_unavailable",
        }
    free_mb = int(reading["free_mb"])
    headroom = free_mb - base_mb
    if headroom >= 3200:
        mode, batch_size, reason = "batched", min(preferred_batch, 16), "abundant_vram"
    elif headroom >= 1800:
        mode, batch_size, reason = "batched", min(preferred_batch, 4), "moderate_vram"
    elif headroom >= 900:
        mode, batch_size, reason = "batched", min(preferred_batch, 2), "tight_vram"
    elif headroom >= 350:
        mode, batch_size, reason = "batched", 1, "low_vram"
    else:
        mode, batch_size, reason = "standard", 1, "minimal_vram"
    return {
        "mode": mode,
        "batch_size": max(1, batch_size),
        "vram": reading,
        "base_mb": base_mb,
        "headroom_mb": headroom,
        "reason": reason,
    }


def snapshot(*, include_vram: bool = True) -> dict[str, Any]:
    with _condition:
        waiting_by_lane = {"notes": 0, "publish": 0, "other": 0}
        waiting_count = 0
        for ticket in _waiting:
            if ticket is _active:
                continue
            waiting_count += 1
            waiting_by_lane[ticket.lane] = waiting_by_lane.get(ticket.lane, 0) + 1
        holder = _holder_payload(_active)
    return {
        "busy": holder is not None,
        "holder": holder,
        "holder_text": describe_holder(holder) if holder else "",
        "waiting_count": waiting_count,
        "waiting_by_lane": waiting_by_lane,
        "vram": query_vram_mb() if include_vram else None,
    }


@contextmanager
def slot(
    enabled: bool = True,
    cancelled: Callable[[], bool] | None = None,
    *,
    lane: str = "other",
    operation: str = "gpu",
    label: str = "",
    on_wait: Callable[[int, dict[str, Any] | None], None] | None = None,
    cooldown: float | None = None,
):
    """Acquire exclusive GPU access with lane-fair round-robin scheduling."""
    global _active, _last_lane, _cooldown_until
    if not enabled:
        yield
        return
    effective_cooldown = (
        max(0.0, float(cooldown))
        if cooldown is not None
        else (RELEASE_COOLDOWN_SECONDS if operation in {"transcribe", "burn"} else 0.0)
    )
    ticket = _Ticket(
        lane=_normalize_lane(lane),
        operation=str(operation or "gpu"),
        label=str(label or ""),
        enqueued_at=time.perf_counter(),
    )
    last_notified: tuple[int, str, str] | None = None
    with _condition:
        _waiting.append(ticket)
        try:
            while True:
                if cancelled and cancelled():
                    raise RuntimeError("转录已取消，可重试恢复")
                now = time.perf_counter()
                cooldown_left = _cooldown_until - now
                if _active is None and cooldown_left <= 0 and _next_candidate() is ticket:
                    _active = ticket
                    _last_lane = ticket.lane
                    ticket.started_at = now
                    break
                notify_payload = None
                if on_wait is not None:
                    position = _queue_position(ticket)
                    holder = _holder_payload(_active)
                    signature = (
                        position,
                        str((holder or {}).get("lane") or ""),
                        str((holder or {}).get("operation") or ""),
                    )
                    if signature != last_notified:
                        last_notified = signature
                        notify_payload = (position, holder)
                if notify_payload is not None:
                    _condition.release()
                    try:
                        on_wait(*notify_payload)
                    finally:
                        _condition.acquire()
                    # Re-check state immediately after releasing the lock.
                    continue
                wait_time = 0.25
                if _active is None and cooldown_left > 0:
                    wait_time = min(0.25, max(0.01, cooldown_left))
                _condition.wait(wait_time)
            if cancelled and cancelled():
                raise RuntimeError("转录已取消，可重试恢复")
        except BaseException:
            if _active is ticket:
                _active = None
            try:
                _waiting.remove(ticket)
            except ValueError:
                pass
            _condition.notify_all()
            raise
    try:
        yield
    finally:
        with _condition:
            if _active is ticket:
                _active = None
            try:
                _waiting.remove(ticket)
            except ValueError:
                pass
            if effective_cooldown > 0:
                _cooldown_until = max(_cooldown_until, time.perf_counter() + effective_cooldown)
            _condition.notify_all()
