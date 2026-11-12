
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent
datas = [(str(root / "app" / "static"), "app/static"), (str(root / "VERSION"), "."),
         (str(root / "app" / "stages"), "app/stages")]
binaries = []
hiddenimports = ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                 "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "clr",
                 "keyring.backends.Windows", "win32ctypes.pywin32.win32cred",
                 "app.desktop_bilibili"]
for package in ("webview", "faster_whisper", "ctranslate2", "bilibili_api"):
    data, libs, imports = collect_all(package, include_py_files=False)
    datas += data
    binaries += libs
    hiddenimports += imports
hiddenimports += collect_submodules("huggingface_hub")

analysis = Analysis(
    [str(root / "desktop_entry.py")], pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, excludes=["torch", "tensorflow", "pytest", "tkinter"],
)
pyz = PYZ(analysis.pure)
desktop = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="MediaOperator", console=False, upx=False)
worker = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="MediaWhisper", console=True, upx=False)
distribution = COLLECT(desktop, worker, analysis.binaries, analysis.datas, name="MediaOperator", upx=False)
