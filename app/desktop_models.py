"""Prepare complete, pinned Whisper models outside the transcription worker."""
import logging
from hashlib import file_digest
from pathlib import Path
import shutil
import threading

import httpx

MODELS = {
    "base": ("ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66", 145217532,
             "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9", 2309),
    "small": ("536b0662742c02347bc0e980a01041f333bce120", 483546902,
              "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671", 2370),
    "medium": ("08e178d48790749d25932bbc082711ddcfdfbc4f", 1527906378,
               "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae", 2257),
    "large-v3": ("edaa852ec7e145841d8ffdb056a99866b5f0a478", 3087284237,
                 "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1", 2394),
    "large-v3-turbo": ("0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf", 1617884929,
                       "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da", 2263),
}
TURBO_REPO = "dropbox-dash/faster-whisper-large-v3-turbo"
LOCK = threading.Lock()
PROGRESS: dict[str, dict] = {}


def metadata(name):
    if name in {"large-v3", "large-v3-turbo"}:
        return {"config.json": MODELS[name][3],
                "tokenizer.json": 2710337 if name == "large-v3-turbo" else 2480617,
                "preprocessor_config.json": 340, "vocabulary.json": 1068114}
    return {"config.json": MODELS[name][3], "tokenizer.json": 2203239, "vocabulary.txt": 459861}


def model_repo(name):
    return TURBO_REPO if name == "large-v3-turbo" else f"Systran/faster-whisper-{name}"


def matches(path, size):
    try:
        return path.is_file() and path.stat().st_size == size
    except OSError:
        return False


def status(data, name):
    if name not in MODELS:
        raise ValueError("不支持的 Whisper 模型")
    root = data / "models"
    preferred = root / f"faster-whisper-{name}"
    revision, size, _, _ = MODELS[name]
    hub = root / "huggingface" / "hub"
    repositories = [model_repo(name)]
    if name == "large-v3-turbo":
        repositories.append("mobiuslabsgmbh/faster-whisper-large-v3-turbo")
    candidates = [preferred, root / (preferred.name + "-verified"), root / name]
    candidates.extend(hub / ("models--" + repo.replace("/", "--")) / "snapshots" / revision for repo in repositories)
    required = {"model.bin": size, **metadata(name)}
    local = next((path for path in candidates if all(matches(path / file, length)
                                                    for file, length in required.items())), None)
    with LOCK:
        progress = dict(PROGRESS.get(name, {}))
    return {"name": name, "available": local is not None, "path": str(local) if local else None,
            "preferred_path": str(preferred), "size": size, "download": progress}


def download_weights(client, url, destination, size, checksum, progress):
    partial = destination.with_suffix(".part")
    if destination.is_file() and matches(destination, size):
        with destination.open("rb") as file:
            if file_digest(file, "sha256").hexdigest() == checksum:
                return
    offset = partial.stat().st_size if partial.is_file() else 0
    while offset < size:
        end = min(size, offset + 64 * 1024 * 1024) - 1
        headers = {"Range": f"bytes={offset}-{end}", "Accept-Encoding": "identity"}
        for attempt in range(3):
            try:
                with client.stream("GET", url, params={"download": "true", "offset": offset}, headers=headers) as response:
                    response.raise_for_status()
                    expected = f"bytes {offset}-{end}/{size}"
                    if response.status_code != 206 or response.headers.get("Content-Range") != expected:
                        raise RuntimeError("Invalid Whisper model download range")
                    with partial.open("ab") as output:
                        for chunk in response.iter_raw(chunk_size=1024 * 1024):
                            output.write(chunk)
                            progress(min(99, output.tell() * 100 // size))
                break
            except httpx.TransportError:
                if attempt == 2:
                    raise
                resume = partial.stat().st_size if partial.is_file() else offset
                if resume > offset:
                    break
        advanced = partial.stat().st_size
        if advanced <= offset or advanced > end + 1:
            raise RuntimeError("Unexpected Whisper download size")
        offset = advanced
    with partial.open("rb") as file:
        valid = offset == size and file_digest(file, "sha256").hexdigest() == checksum
    if not valid:
        partial.unlink()
        raise RuntimeError("Whisper model SHA-256 mismatch")
    partial.replace(destination)


def _prepare(data, name, proxy, target):
    revision, size, checksum, _ = MODELS[name]
    directory = target.parent / f".download-{name}"
    base = f"https://huggingface.co/{model_repo(name)}/resolve/{revision}/"

    def progress(percent):
        with LOCK:
            PROGRESS[name].update(percent=percent, message=f"正在准备模型 · {percent}%")

    try:
        directory.mkdir(parents=True, exist_ok=True)
        with httpx.Client(proxy=proxy, trust_env=False, follow_redirects=True, timeout=60) as client:
            for file, length in metadata(name).items():
                path = directory / file
                if not matches(path, length):
                    response = client.get(base + file)
                    response.raise_for_status()
                    if len(response.content) != length:
                        raise ValueError("Whisper metadata size mismatch")
                    temporary = path.with_suffix(path.suffix + ".part")
                    temporary.write_bytes(response.content)
                    temporary.replace(path)
            download_weights(client, base + "model.bin", directory / "model.bin", size, checksum, progress)
        directory.rename(target)
        with LOCK:
            PROGRESS[name] = {"running": False, "percent": 100, "message": "本地模型已准备好"}
    except Exception as error:
        logging.getLogger(__name__).warning("Whisper %s preparation failed (%s)", name, type(error).__name__)
        with LOCK:
            PROGRESS[name].update(running=False, message="模型下载或校验失败。请检查网络和资料目录后重试。")


def prepare(data, name, proxy):
    current = status(data, name)
    if current["available"]:
        return
    target = Path(current["preferred_path"])
    if target.exists():
        target = target.with_name(target.name + "-verified")
    if target.exists():
        raise ValueError("模型目录中已有不完整的副本，请整理后重试。")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.parent / f".download-{name}" / "model.part"
    remaining = MODELS[name][1] - (partial.stat().st_size if partial.is_file() else 0)
    if shutil.disk_usage(target.parent).free < max(0, remaining) + 16 * 1024 * 1024:
        raise ValueError("资料盘可用空间不足，请腾出空间后再下载模型。")
    with LOCK:
        if any(value["running"] for value in PROGRESS.values()):
            return
        PROGRESS[name] = {"running": True, "percent": 0, "message": "正在连接模型服务器"}
        threading.Thread(target=_prepare, args=(data, name, proxy, target), daemon=True).start()


def is_running():
    with LOCK:
        return any(model["running"] for model in PROGRESS.values())
