
"""The Windows window owns a private, loopback-only Media Operator session."""
import ctypes
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time

from fastapi import Request
from fastapi.responses import RedirectResponse, Response
import uvicorn

from app import desktop_config as config


def prepare():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    desktop_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else root
    tools = Path(os.getenv("MEDIA_DESKTOP_TOOLS", desktop_dir / "tools"))
    data = Path(os.getenv("MEDIA_DESKTOP_DATA", config.data_dir()))
    os.environ.update({
        "MEDIA_DESKTOP": "1",
        "MEDIA_ROOT_DIR": str(root),
        "MEDIA_DATA_DIR": str(data),
        "HF_HOME": str(data / "models" / "huggingface"),
        "FFMPEG_BIN": str(tools / "ffmpeg.exe"),
        "FFPROBE_BIN": str(tools / "ffprobe.exe"),
        "YT_DLP_BIN": str(tools / "yt-dlp.exe"),
        "WHISPER_MODEL": "small",
        "WHISPER_INFERENCE_MODE": "standard",
        "WHISPER_BACKEND": "faster-whisper",
        "SUBTITLE_FONTS_DIR": str(Path(os.environ["WINDIR"]) / "Fonts"),
        "ALLOW_PLACEHOLDER_ARTIFACTS": "false",
        "TRANSLATE_PROVIDER": "deepseek",
        "TRANSLATE_API_BASE": "https://api.deepseek.com",
        "TRANSLATE_MODEL": config.settings().get("ai_model", "deepseek-flash"),
    })


def application(origin, token):
    from app import desktop_jobs, desktop_routes, knowledge
    from app import main as media

    media.ensure_dirs()
    knowledge.initialize()
    desktop_routes.sync_credentials()
    desktop_jobs.recover_interrupted()
    app = media.app
    app.include_router(desktop_routes.router)

    @app.middleware("http")
    async def private_session(request: Request, call_next):
        if request.headers.get("host") != origin.removeprefix("http://"):
            return Response(status_code=403)
        if request.url.path == "/desktop/connect" and request.method == "GET":
            supplied = request.query_params.get("token", "")
            if not secrets.compare_digest(supplied.encode(), token.encode()):
                return Response(status_code=403)
            response = RedirectResponse("/media-ui", status_code=303)
            response.set_cookie("media_session", token, httponly=True, samesite="strict")
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
            return response
        if not secrets.compare_digest(request.cookies.get("media_session", "").encode(), token.encode()):
            return Response(status_code=403)
        if request.method not in {"GET", "HEAD"} and request.headers.get("origin") != origin:
            return Response(status_code=403)
        response = await call_next(request)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; "
            "media-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        )
        return response

    return app


class NativeFiles:
    def __init__(self, webview):
        self._webview = webview
        self._window = None

    def choose_media(self, multiple=False):
        return self._window.create_file_dialog(
            self._webview.FileDialog.OPEN, allow_multiple=multiple,
            file_types=("媒体与字幕 (*.mp4;*.mkv;*.mov;*.webm;*.avi;*.mp3;*.m4a;*.wav;*.flac;*.ogg;*.opus;*.aac;*.srt;*.vtt)",
                        "所有文件 (*.*)"),
        ) or []

    def choose_folder(self):
        paths = self._window.create_file_dialog(self._webview.FileDialog.FOLDER) or []
        return paths[0] if paths else ""

    def save_as(self, filename):
        paths = self._window.create_file_dialog(self._webview.FileDialog.SAVE, save_filename=Path(filename).name) or []
        return paths[0] if paths else ""


def run_window():
    import webview

    prepare()
    token = secrets.token_urlsafe(32)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config(
            application(origin, token), host="127.0.0.1", port=port, access_log=False,
            log_config=None, timeout_graceful_shutdown=3,
        ))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("应用服务启动失败")

        bridge = NativeFiles(webview)
        window = webview.create_window(
            "Media Operator", f"{origin}/desktop/connect?token={token}", js_api=bridge,
            width=1440, height=940, min_size=(950, 680),
        )
        bridge._window = window
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        def allow_close():
            from app import desktop_gpu, desktop_jobs, desktop_routes, obsidian

            busy = any(batch.queued or batch.running for batch in desktop_jobs.stored_batches())
            if busy or desktop_routes.GENERATING or desktop_gpu.PROGRESS["running"] or obsidian.LOCK.locked():
                ctypes.windll.user32.MessageBoxW(None, "还有任务正在运行。请等待任务完成后再关闭。", "Media Operator", 0x40)
                return False
            return True

        window.events.closing += allow_close
        webview.start(gui="edgechromium")
        server.should_exit = True
        thread.join(timeout=4)


def main():
    # The same mutex is checked by the installer before an upgrade.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None, False, "MediaOperatorDesktopWindow")
    if ctypes.get_last_error() == 183:
        ctypes.windll.user32.MessageBoxW(None, "Media Operator 已在运行。", "Media Operator", 0x40)
        return
    config.HOME.mkdir(parents=True, exist_ok=True)
    try:
        with (config.HOME / "desktop.log").open("a", encoding="utf-8") as log:
            if sys.stdout is None:
                sys.stdout = log
            if sys.stderr is None:
                sys.stderr = log
            try:
                run_window()
            except Exception:
                logging.exception("Desktop startup failed")
                ctypes.windll.user32.MessageBoxW(None, "应用启动失败。请检查 WebView2 或查看本机启动日志。", "Media Operator", 0x10)
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(mutex)
