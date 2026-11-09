# Media Operator Windows 试用说明

在 Windows 11 x64 上运行 MediaOperatorSetup.exe，然后从桌面打开 Media Operator。安装包未签名。首次转录会下载 Whisper 模型，缓存后可离线转录本地素材。若系统缺少 WebView2，安装程序会联网补齐。

## 视频制作

添加本地视频或 YouTube 链接，按需调整素材顺序。选择批次默认参数，或为当前素材单独设置。可抓取实际字幕预览，然后提交任务。在任务记录中查看进度、从失败阶段重试，或导出视频和字幕。

## 字幕分析与 Obsidian

1. 在 Obsidian 打开或创建一个 Vault。到 Media Operator 的设置中选择该 Vault 的根目录，保存设置。
2. 导入视频、音频、SRT 或 VTT，也可以从视频任务打开已有字幕。
3. 配置 DeepSeek 后提取观点，对照原话编辑，勾选需要长期保留的卡片。
4. 点击「发布到 Obsidian」。每张卡生成一篇观点笔记，并链接到共享素材页。发布成功并核对写入结果后，对应的本地草稿会清理。发布失败的草稿可重试。
5. 在 Obsidian 继续编辑、移动和添加双链。应用遇到重复发布会显示原笔记，另存新版本会创建独立文件。

## 资料与构建

设置中可选 D 盘资料目录、DeepSeek 模型、B 站凭据和 NVIDIA 转录加速。DeepSeek 密钥与投稿凭据由 Windows 凭据管理器保存。报告问题时可从设置导出脱敏诊断。

从源码构建需要 Windows x64 的 Python 3.12、Node.js 24 和 Inno Setup 7。安装 requirements-desktop.txt 后，运行 scripts/build_desktop.ps1，并传入构建目录、输出目录、ISCC.exe 和 Python 解释器的路径。构建脚本会安装锁定的前端依赖，将生成的静态资源打入安装包。
