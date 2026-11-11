# Media Operator

## 改完即安装

凡是改了桌面程序会运行的代码（`app/`、`frontend/`、`packaging/`、`desktop_entry.py`），做完后默认打包并完成本地安装更新，不要停在源码。用户另行说明「先不要安装」时才跳过。只改文档、只回答问题、或仍在方案阶段时不打包。

版本号保持仓库根目录 `VERSION` 的当前值，除非用户要求升级版本。升级时同时改 `frontend/package.json` 和 `packaging/MediaOperator.iss` 里的同号，测试会核对它们一致。

打包前在本机设置这些路径，不要把个人盘符写回仓库：

- `MEDIA_BUILD_DIR`：构建缓存目录
- `MEDIA_OUTPUT_DIR`：安装包输出目录
- `INNO_COMPILER`：Inno Setup 的 `ISCC.exe`
- `MEDIA_PYTHON`：用于打包的 Python 3.12 解释器
- `MEDIA_INSTALL_DIR`：覆盖安装目录

```powershell
.\scripts\build_desktop.ps1 `
  -BuildDir $env:MEDIA_BUILD_DIR `
  -OutputDir $env:MEDIA_OUTPUT_DIR `
  -InnoCompiler $env:INNO_COMPILER `
  -PythonExe $env:MEDIA_PYTHON
Copy-Item -LiteralPath (Join-Path $env:MEDIA_OUTPUT_DIR "MediaOperatorSetup.exe") -Destination (Join-Path $env:MEDIA_OUTPUT_DIR "setup.exe")
```

安装前结束 `MediaOperator` 和 `MediaWhisper`。静默覆盖安装，目录参数必须带引号：

```powershell
$setup = Join-Path $env:MEDIA_OUTPUT_DIR "setup.exe"
$log = Join-Path $env:MEDIA_OUTPUT_DIR "install.log"
$arg = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /DIR=`"$($env:MEDIA_INSTALL_DIR)`" /LOG=`"$log`""
Start-Process -FilePath $setup -ArgumentList $arg -Wait
Start-Process -FilePath (Join-Path $env:MEDIA_INSTALL_DIR "MediaOperator.exe")
```

安装成功后核对安装目录、卸载信息里的版本，以及新程序的修改时间与本次构建一致。
