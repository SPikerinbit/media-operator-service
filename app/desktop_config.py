
"""Per-user desktop settings, credentials and worker process environment."""
import json
import os
from pathlib import Path
import threading


def _profile_home() -> Path:
    chosen = os.getenv("MEDIA_DESKTOP_HOME")
    if chosen:
        return Path(chosen)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "MediaOperator"
    return Path.home() / ".media-operator"


class _LazyVault:
    """Open Windows Credential Manager on first use.

    Importing this module must work on other systems. Tests and non-Windows
    checks never touch the vault unless a caller asks for a credential.
    """

    def __getattr__(self, name):
        from keyring.backends.Windows import WinVaultKeyring

        vault = WinVaultKeyring()
        globals()["VAULT"] = vault
        return getattr(vault, name)


HOME = _profile_home()
SETTINGS = HOME / "settings.json"
VAULT = _LazyVault()
SERVICE = "Media Operator Desktop"
CREDENTIALS = (
    "TRANSLATE_API_KEY", "BILI_SESSDATA", "BILI_JCT", "BILI_BUVID3", "BILI_DEDEUSERID", "BILI_AC_TIME_VALUE",
)
GPU_LIBRARIES = ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll", "cudart64_12.dll")
LOCK = threading.RLock()


class CredentialError(RuntimeError):
    pass


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
            try:
                existing = VAULT.get_password(SERVICE, name) or ""
                if value and value != existing:
                    VAULT.set_password(SERVICE, name, value)
                elif not value and existing:
                    VAULT.delete_password(SERVICE, name)
                if (VAULT.get_password(SERVICE, name) or "") != value:
                    raise CredentialError()
            except Exception as error:
                raise CredentialError("无法写入 Windows 凭据管理器。请检查系统凭据服务后重试。") from error
        HOME.mkdir(parents=True, exist_ok=True)
        temporary = SETTINGS.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(SETTINGS)


def gpu_dir(root):
    selected = settings().get("gpu_install_dir")
    if selected:
        return Path(selected) / "cuda12-cudnn9"
    legacy = root / "gpu" / "cuda12-cudnn9"
    if legacy.exists() or not Path("D:/").is_dir():
        return legacy
    return Path("D:/Media Operator NVIDIA/cuda12-cudnn9")


def gpu_ready(directory):
    return (directory / ".ready").is_file() and all((directory / dll).is_file() for dll in GPU_LIBRARIES)


def worker_environment(enable_gpu=False):
    from app import main as media

    env = os.environ.copy()
    gpu = gpu_dir(media.DATA_DIR)
    env["WHISPER_DEVICE"] = "cpu"
    env["WHISPER_COMPUTE_TYPE"] = ""
    env.pop("MEDIA_GPU_DLL_DIR", None)
    env["PYTHONUTF8"] = "1"
    env["HF_HOME"] = str(media.DATA_DIR / "models" / "huggingface")
    env["HF_HUB_OFFLINE"] = "1"
    if (enable_gpu or settings().get("gpu_enabled")) and gpu_ready(gpu):
        env["WHISPER_DEVICE"] = "cuda"
        env["WHISPER_COMPUTE_TYPE"] = "int8_float16"
        env["MEDIA_GPU_DLL_DIR"] = str(gpu)
        env["PATH"] = str(gpu) + os.pathsep + env.get("PATH", "")
    return env
