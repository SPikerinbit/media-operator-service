"""Windows native helpers: monitor bounds clamping, taskbar progress, and background notifications."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import queue
import threading
import time
import uuid

TBPF_NOPROGRESS = 0x0
TBPF_INDETERMINATE = 0x1
TBPF_NORMAL = 0x2
TBPF_ERROR = 0x4
TBPF_PAUSED = 0x8

_TASKBAR_STATES = {
    "none": TBPF_NOPROGRESS,
    "indeterminate": TBPF_INDETERMINATE,
    "normal": TBPF_NORMAL,
    "error": TBPF_ERROR,
    "paused": TBPF_PAUSED,
}

_CLSID_TASKBAR_LIST = "{56FDF344-FD6D-11D0-958A-006097C9A090}"
_IID_ITASKBAR_LIST3 = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"


def clamp_window_bounds(saved, monitors):
    """Clamp persisted logical window bounds into visible monitor work areas.

    ``monitors`` is a sequence of ``(left, top, right, bottom)`` logical work-area rects.
    Returns ``None`` when ``saved`` is missing or invalid so callers fall back to defaults.
    """
    if not isinstance(saved, dict):
        return None
    try:
        width = int(saved.get("width", 0))
        height = int(saved.get("height", 0))
        x = int(saved.get("x", 0))
        y = int(saved.get("y", 0))
    except (TypeError, ValueError):
        return None
    if width < 600 or height < 400:
        return None
    maximized = bool(saved.get("maximized", False))

    valid_monitors = [
        (int(left), int(top), int(right), int(bottom))
        for left, top, right, bottom in (monitors or ())
        if right - left >= 320 and bottom - top >= 240
    ]
    if not valid_monitors:
        return {
            "x": x,
            "y": y,
            "width": min(width, 2560),
            "height": min(height, 1600),
            "maximized": maximized,
        }

    # Find the monitor with the largest visible overlap with the saved rectangle.
    best_monitor = None
    best_area = 0
    for rect in valid_monitors:
        left, top, right, bottom = rect
        overlap_w = min(x + width, right) - max(x, left)
        overlap_h = min(y + height, bottom) - max(y, top)
        if overlap_w >= 160 and overlap_h >= 80:
            area = overlap_w * overlap_h
            if area > best_area:
                best_area = area
                best_monitor = rect

    if best_monitor is None:
        # Saved position is off-screen (e.g., an unplugged monitor); place cleanly on primary monitor.
        left, top, right, bottom = valid_monitors[0]
        avail_w = right - left
        avail_h = bottom - top
        clamped_w = max(min(950, avail_w), min(width, max(320, avail_w - 28)))
        clamped_h = max(min(680, avail_h), min(height, max(240, avail_h - 28)))
        return {
            "x": left + max(0, (avail_w - clamped_w) // 2),
            "y": top + max(0, (avail_h - clamped_h) // 2),
            "width": clamped_w,
            "height": clamped_h,
            "maximized": maximized,
        }

    left, top, right, bottom = best_monitor
    avail_w = right - left
    avail_h = bottom - top
    clamped_w = max(min(950, avail_w), min(width, avail_w))
    clamped_h = max(min(680, avail_h), min(height, avail_h))
    clamped_x = max(left - clamped_w + 160, min(x, right - 160))
    clamped_y = max(top, min(y, bottom - 60))
    return {
        "x": clamped_x,
        "y": clamped_y,
        "width": clamped_w,
        "height": clamped_h,
        "maximized": maximized,
    }


def monitor_work_rects():
    """Return logical work-area rectangles for all active monitors on Windows."""
    if os.name != "nt":
        return []
    try:
        user = ctypes.windll.user32

        class MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("monitor", wintypes.RECT),
                ("work", wintypes.RECT),
                ("flags", wintypes.DWORD),
            ]

        rects = []
        primary = []
        enum_proc_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
        )

        def callback(hmonitor, _hdc, _lprect, _lparam):
            info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
            if user.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                dpi_x, dpi_y = wintypes.UINT(96), wintypes.UINT(96)
                try:
                    get_dpi = ctypes.windll.shcore.GetDpiForMonitor
                    get_dpi.argtypes = [
                        wintypes.HANDLE,
                        ctypes.c_int,
                        ctypes.POINTER(wintypes.UINT),
                        ctypes.POINTER(wintypes.UINT),
                    ]
                    get_dpi(hmonitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
                except OSError:
                    pass
                sx = 96.0 / max(96, dpi_x.value)
                sy = 96.0 / max(96, dpi_y.value)
                rect = (
                    round(info.work.left * sx),
                    round(info.work.top * sy),
                    round(info.work.right * sx),
                    round(info.work.bottom * sy),
                )
                if info.flags & 1:
                    primary.append(rect)
                else:
                    rects.append(rect)
            return True

        user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        user.EnumDisplayMonitors(None, None, enum_proc_type(callback), 0)
        return primary + rects
    except Exception:
        return []


def window_hwnd(window):
    native = getattr(window, "native", None)
    if native is None:
        return None
    try:
        return int(native.Handle.ToInt64())
    except Exception:
        return None


def is_window_maximized(hwnd):
    if os.name != "nt" or not hwnd:
        return False
    try:
        return bool(ctypes.windll.user32.IsZoomed(ctypes.c_void_p(hwnd)))
    except Exception:
        return False


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_str(cls, text: str) -> "_GUID":
        raw = uuid.UUID(text)
        data4 = (ctypes.c_ubyte * 8)(*raw.bytes[8:])
        return cls(raw.time_low, raw.time_mid, raw.time_hi_version, data4)


class TaskbarProgress:
    """Thread-safe Windows ITaskbarList3 taskbar progress bridge."""

    def __init__(self):
        self._queue: queue.Queue[tuple[int, str, int] | None] = queue.Queue(maxsize=32)
        self._started = False
        self._lock = threading.Lock()

    def _ensure_worker(self):
        if os.name != "nt":
            return False
        with self._lock:
            if not self._started:
                self._started = True
                threading.Thread(target=self._run, name="taskbar-progress", daemon=True).start()
            return True

    def update(self, hwnd: int | None, state: str, percent: int = 0) -> None:
        if not hwnd or not self._ensure_worker():
            return
        safe_state = state if state in _TASKBAR_STATES else "none"
        safe_pct = max(0, min(100, int(percent or 0)))
        try:
            self._queue.put_nowait((int(hwnd), safe_state, safe_pct))
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait((int(hwnd), safe_state, safe_pct))
            except Exception:
                pass

    def _run(self):
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        taskbar_ptr = ctypes.c_void_p()
        try:
            clsid = _GUID.from_str(_CLSID_TASKBAR_LIST)
            iid = _GUID.from_str(_IID_ITASKBAR_LIST3)
            hr = ole32.CoCreateInstance(
                ctypes.byref(clsid),
                None,
                0x17,  # CLSCTX_ALL
                ctypes.byref(iid),
                ctypes.byref(taskbar_ptr),
            )
            if hr != 0 or not taskbar_ptr.value:
                return
            vtable = ctypes.cast(
                ctypes.cast(taskbar_ptr, ctypes.POINTER(ctypes.c_void_p))[0],
                ctypes.POINTER(ctypes.c_void_p),
            )
            hr_init = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[3])
            set_value = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, wintypes.HWND, ctypes.c_uint64, ctypes.c_uint64
            )(vtable[9])
            set_state = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, wintypes.HWND, ctypes.c_uint32
            )(vtable[10])
            if hr_init(taskbar_ptr) != 0:
                return
            while True:
                item = self._queue.get()
                if item is None:
                    break
                hwnd, state, percent = item
                try:
                    flag = _TASKBAR_STATES.get(state, TBPF_NOPROGRESS)
                    set_state(taskbar_ptr, wintypes.HWND(hwnd), flag)
                    if state in {"normal", "error", "paused"}:
                        set_value(taskbar_ptr, wintypes.HWND(hwnd), percent, 100)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            try:
                if taskbar_ptr.value:
                    vtable = ctypes.cast(
                        ctypes.cast(taskbar_ptr, ctypes.POINTER(ctypes.c_void_p))[0],
                        ctypes.POINTER(ctypes.c_void_p),
                    )
                    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
                    release(taskbar_ptr)
            except Exception:
                pass
            try:
                ole32.CoUninitialize()
            except Exception:
                pass


class _FLASHWINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("hwnd", wintypes.HWND),
        ("dwFlags", wintypes.DWORD),
        ("uCount", wintypes.UINT),
        ("dwTimeout", wintypes.DWORD),
    ]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
    ]


_NOTIFY_LOCK = threading.Lock()
_NOTIFY_SEQ = 0


def notify_if_unfocused(hwnd: int | None, title: str, body: str) -> bool:
    """Flash the taskbar and display a Windows notification when the app is not foreground."""
    if os.name != "nt" or not hwnd:
        return False
    clean_title = str(title or "Media Operator").strip()[:63]
    clean_body = str(body or "").strip()[:255]
    if not clean_body:
        return False
    try:
        user = ctypes.windll.user32
        foreground = user.GetForegroundWindow()
        if foreground and int(foreground) == int(hwnd):
            return False
        flash = _FLASHWINFO(
            cbSize=ctypes.sizeof(_FLASHWINFO),
            hwnd=wintypes.HWND(hwnd),
            dwFlags=0x00000002 | 0x0000000C,  # FLASHW_TRAY | FLASHW_TIMERNOFG
            uCount=3,
            dwTimeout=0,
        )
        user.FlashWindowEx(ctypes.byref(flash))
    except Exception:
        return False

    def _balloon():
        global _NOTIFY_SEQ
        with _NOTIFY_LOCK:
            _NOTIFY_SEQ += 1
            uid = 9400 + (_NOTIFY_SEQ % 400)
        try:
            shell = ctypes.windll.shell32
            user = ctypes.windll.user32
            hicon = user.SendMessageW(wintypes.HWND(hwnd), 0x007F, 0, 0)  # WM_GETICON ICON_SMALL
            if not hicon:
                hicon = user.LoadIconW(None, ctypes.c_void_p(32512))  # IDI_APPLICATION
            data = _NOTIFYICONDATAW()
            data.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
            data.hWnd = wintypes.HWND(hwnd)
            data.uID = uid
            data.uFlags = 0x00000002 | 0x00000004 | 0x00000010  # NIF_ICON | NIF_TIP | NIF_INFO
            data.hIcon = hicon
            data.szTip = "Media Operator"
            data.szInfoTitle = clean_title
            data.szInfo = clean_body
            data.dwInfoFlags = 0x00000001 | 0x00000020  # NIIF_INFO | NIIF_RESPECT_QUIET_TIME
            shell.Shell_NotifyIconW(0x00000000, ctypes.byref(data))  # NIM_ADD
            time.sleep(6.0)
            shell.Shell_NotifyIconW(0x00000002, ctypes.byref(data))  # NIM_DELETE
        except Exception:
            pass

    threading.Thread(target=_balloon, name="desktop-notify", daemon=True).start()
    return True
