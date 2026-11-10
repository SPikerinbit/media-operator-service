# Media Operator

## 改完即安装

凡是改了桌面程序会运行的代码（`app/`、`frontend/`、`packaging/`、`desktop_entry.py`），做完后默认打包并完成本地安装更新，不要停在源码。用户另行说明「先不要安装」时才跳过。只改文档、只回答问题、或仍在方案阶段时不打包。

版本号保持当前值，除非用户要求升级版本。

打包命令：

```powershell
.\scripts\build_desktop.ps1 `
  -BuildDir "D:\dev\Media Operator 构建 0.2.5" `
  -OutputDir "D:\dev\Media Operator 0.5.0" `
  -InnoCompiler "D:\dev\Media Operator 构建 0.2.5\development-tools\inno\ISCC.exe" `
  -PythonExe "D:\dev\Media Operator 构建 0.2.5\development-tools\venv\Scripts\python.exe"
```

安装包复制为 `D:\dev\Media Operator 0.5.0\setup.exe`。安装前结束 `MediaOperator` 和 `MediaWhisper`。静默覆盖安装到 `D:\Media Operator`，目录参数必须带引号：

```powershell
$arg = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /DIR="D:\Media Operator" /LOG="D:\dev\Media Operator 0.5.0\install.log"'
Start-Process -FilePath "D:\dev\Media Operator 0.5.0\setup.exe" -ArgumentList $arg -Wait
```

安装成功后启动 `D:\Media Operator\MediaOperator.exe`。核对安装目录、卸载信息里的版本，以及新程序的修改时间与本次构建一致。
