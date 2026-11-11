
"""Fetch the pinned NVIDIA runtime on demand from NVIDIA's release archives."""
from hashlib import file_digest
from pathlib import Path
import shutil
import tempfile
import zipfile
import threading

import httpx

from app.desktop_config import GPU_LIBRARIES, gpu_ready, update

FILES = (
    ("cuda/redist/libcublas/windows-x86_64/libcublas-windows-x86_64-12.9.1.4-archive.zip",
     "d534d98b0b453a98914dbf3adf47d7e84b55037abf02f87466439e1dcef581ed", 549755186),
    ("cuda/redist/cuda_cudart/windows-x86_64/cuda_cudart-windows-x86_64-12.9.79-archive.zip",
     "179e9c43b0735ffe67207b3da556eb5a0c50f3047961882b7657d3b822d34ef8", 3521238),
    ("cudnn/redist/cudnn/windows-x86_64/cudnn-windows-x86_64-9.10.2.21_cuda12-archive.zip",
     "c1a4567d822ebda7373fa1f19255dff4942302de741f830160b6c7d1fb31af23", 683336095),
)
LOCK = threading.Lock()
PROGRESS = {"running": False, "message": ""}


def unpack(destination, archives):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        staging = Path(directory) / "runtime"
        staging.mkdir()
        for archive_path in archives:
            with zipfile.ZipFile(archive_path) as archive:
                for name in archive.namelist():
                    path = Path(name)
                    if path.parent.name.lower() == "bin" and path.suffix.lower() == ".dll":
                        with archive.open(name) as source, (staging / path.name).open("wb") as target:
                            shutil.copyfileobj(source, target)
        if not all((staging / name).is_file() for name in GPU_LIBRARIES):
            raise RuntimeError("NVIDIA 加速包缺少运行库")
        (staging / ".ready").touch()
        staging.rename(destination)


def download(client, url, destination, checksum, size, report):
    partial = destination.with_suffix(".part")
    for _ in range(4):
        current = destination if destination.exists() else partial
        offset = current.stat().st_size if current.exists() else 0
        if offset == size:
            with current.open("rb") as file:
                valid = file_digest(file, "sha256").hexdigest() == checksum
            if valid:
                if current == partial:
                    partial.replace(destination)
                return destination
        if offset >= size or current == destination:
            current.unlink(missing_ok=True)
            offset = 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                if response.status_code == 206:
                    if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                        raise ValueError("NVIDIA 下载返回了错误的文件范围")
                else:
                    offset = 0
                with partial.open("ab" if offset else "wb") as output:
                    for chunk in response.iter_bytes(1024 * 1024):
                        output.write(chunk)
                        offset += len(chunk)
                        report(min(99, offset * 100 // size))
        except httpx.TransportError:
            continue
    if partial.is_file() and partial.stat().st_size == size:
        with partial.open("rb") as file:
            if file_digest(file, "sha256").hexdigest() == checksum:
                partial.replace(destination)
                return destination
    raise RuntimeError("NVIDIA 运行库下载未完成或校验失败")


def download_progress(index, total, percent):
    return f"正在下载 NVIDIA 运行库 {index}/{total} · {percent}%"


def progress_reporter(index, total):
    def report(percent, index=index, total=total):
        PROGRESS["message"] = download_progress(index, total, percent)
    return report


def _install(destination):
    try:
        cache = destination.parent / ".media-operator-downloads"
        cache.mkdir(parents=True, exist_ok=True)
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            archives = []
            for index, (url, checksum, size) in enumerate(FILES, 1):
                report = progress_reporter(index, len(FILES))
                report(0)
                archives.append(download(client, "https://developer.download.nvidia.com/compute/" + url,
                                         cache / f"{index}.zip", checksum, size, report))
            PROGRESS["message"] = "正在解压 NVIDIA 运行库"
            unpack(destination, archives)
        update({"gpu_enabled": True, "gpu_install_dir": str(destination.parent)}, {})
        for archive in archives:
            try:
                archive.unlink()
            except OSError:
                pass
        PROGRESS["message"] = "已启用 NVIDIA 加速"
    except Exception:
        PROGRESS["message"] = "NVIDIA 运行库安装失败，可继续使用 CPU 或稍后重试"
    finally:
        with LOCK:
            PROGRESS["running"] = False


def install(directory):
    with LOCK:
        if PROGRESS["running"]:
            raise RuntimeError("NVIDIA 运行库正在安装")
        if not directory.is_absolute():
            raise ValueError("请选择 NVIDIA 运行库的绝对安装目录")
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory.resolve() / "cuda12-cudnn9"
        if gpu_ready(destination):
            update({"gpu_enabled": True, "gpu_install_dir": str(destination.parent)}, {})
            PROGRESS.update(message="已启用 NVIDIA 加速")
            return
        if destination.exists():
            raise ValueError("该目录已有同名文件夹，请选择其他安装目录")
        PROGRESS.update(running=True, message="正在准备 NVIDIA 运行库")
        threading.Thread(target=_install, args=(destination,), daemon=True).start()
