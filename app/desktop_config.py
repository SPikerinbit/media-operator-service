
"""Per-user desktop settings, credentials and worker process environment."""
import json
import os
from pathlib import Path
import threading

from keyring.backends.Windows import WinVaultKeyring

HOME = Path(os.getenv("MEDIA_DESKTOP_HOME") or Path(os.environ["LOCALAPPDATA"]) / "MediaOperator")
SETTINGS = HOME / "settings.json"
VAULT = WinVaultKeyring()
SERVICE = "Media Operator Desktop"
CREDENTIALS = (
    "TRANSLATE_API_KEY", "BILI_SESSDATA", "BILI_JCT", "BILI_BUVID3", "BILI_DEDEUSERID", "BILI_AC_TIME_VALUE",
)
LOCK = threading.RLock()


def settings():
    with LOCK:
        if SETTINGS.is_file():
            return json.loads(SETTINGS.read_text(encoding="utf-8"))
    return {}


def data_dir():
    return Path(settings().get("data_dir") or HOME / "data")


def credentials():
    with LOCK:
        return {name: VAULT.get_password(SERVICE, name) or "" for name in CREDENTIALS}


def update(changes, secrets):
    with LOCK:
        current = settings()
        if changes.get("data_dir"):
            path = Path(changes["data_dir"])
            if not path.is_absolute():
                raise ValueError("请选择绝对资料目录")
            path.mkdir(parents=True, exist_ok=True)
            changes["data_dir"] = str(path.resolve())
        current.update(changes)
        for name, value in secrets.items():
            if name not in CREDENTIALS or value is None:
                continue
            if value:
                VAULT.set_password(SERVICE, name, value)
            elif VAULT.get_password(SERVICE, name):
                VAULT.delete_password(SERVICE, name)
        HOME.mkdir(parents=True, exist_ok=True)
        temporary = SETTINGS.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(SETTINGS)


def gpu_dir(root):
    return root / "gpu" / "cuda12-cudnn9"


def worker_environment():
    from app import main as media

    env = os.environ.copy()
    gpu = gpu_dir(media.DATA_DIR)
    env["WHISPER_DEVICE"] = "cpu"
    env["WHISPER_COMPUTE_TYPE"] = ""
    env["PYTHONUTF8"] = "1"
    env["HF_HOME"] = str(media.DATA_DIR / "models" / "huggingface")
    if settings().get("gpu_enabled") and (gpu / ".ready").is_file():
        env["WHISPER_DEVICE"] = "cuda"
        env["WHISPER_COMPUTE_TYPE"] = "int8_float16"
        env["MEDIA_GPU_DLL_DIR"] = str(gpu)
        env["PATH"] = str(gpu) + os.pathsep + env.get("PATH", "")
    return env
