# Media Operator

Media Operator 是跑在 Windows 上的本地桌面程序。它把本机文件，以及 YouTube、Bilibili、抖音、小红书、小宇宙的链接或分享文案，做成带字幕的视频，可以投稿到 B 站，也可以把原话整理成 Obsidian 笔记。0.5 的界面是一个双信箱工作台：首页同时收「投稿」和「笔记」。转录在本机完成。DeepSeek 翻译、投稿文案和观点摘录是可选项。

当前版本 **0.5.0**。版本号以仓库根目录的 [`VERSION`](VERSION) 为准。`main` 与 `dev` 都在这一版。

## English summary

Media Operator is a Windows desktop app. It turns local files and links from YouTube, Bilibili, Douyin, Xiaohongshu, and Xiaoyuzhou into subtitled videos, can upload those videos to Bilibili, and can file source-grounded notes into an Obsidian vault. Version 0.5 is a workbench with two inboxes, one for publishing and one for notes. Transcription runs locally. DeepSeek is optional. `main` and `dev` both carry 0.5.0.

下面是给使用者的说明。安装包未签名。桌面窗口只连接本机 `127.0.0.1`，密钥放在 Windows 凭据管理器里。

工作台用信纸、信封和火盆表示投递与处理。下面两张是界面里的插画素材，不是运行截图。

![投稿信箱插画：一只写着铭牌的邮箱](frontend/public/workbench/mailbox-light-beauty.webp)

![投稿工作台插画：用来开始处理的火盆](frontend/public/workbench/brazier-light-beauty.webp)

## 系统要求

- **系统**：64 位 Windows 11（安装脚本要求 10.0.22000 及以上）。不需要管理员权限。
- **界面**：Microsoft Edge WebView2。安装包里带有引导程序；系统里没有运行库时，安装程序会联网补齐。
- **显卡**：可选。没有 NVIDIA 也能用 CPU 转录和编码。要加速转录，需要能安装 CUDA 12 / cuDNN 9 运行库的 NVIDIA 显卡。烧录可以选择 NVENC，只加速视频编码，字幕仍由 libass 绘制。
- **磁盘**：模型按名称下载，界面里显示的大约体积是 base 0.15 GB、small 0.48 GB、medium 1.53 GB、large-v3 3.09 GB、large-v3-turbo 1.62 GB。首次安装 NVIDIA 运行库约 1.2 GB。设置里的「检测本地环境」会列出资料盘剩余空间。成片和下载的素材另外占空间。
- **网络**：在线素材、模型、NVIDIA 运行库和 DeepSeek 需要能访问对应站点。桌面程序读取 Windows 系统代理，没有单独的代理输入框。

## 安装

### 安装包

运行 `MediaOperatorSetup.exe`。安装位置可以改。有 D 盘时，新安装默认选中 `D:\Media Operator`，否则选当前用户本地程序目录下的 `Media Operator`。安装程序可以创建桌面快捷方式。装好后从开始菜单或桌面打开 **Media Operator**。

同一时间只能开一个窗口。升级或覆盖安装前，先退出 `MediaOperator` 和转录进程 `MediaWhisper`。

FFmpeg、ffprobe、yt-dlp 或 Deno 检测失败时，重新运行安装程序即可补齐随包工具。

### 从源码构建安装包

只在 Windows x64 上打包。需要 Python 3.12、Node.js 和 Inno Setup 7。持续集成用 Node.js 22 构建前端；打包说明里写的是 Node.js 24，两者都能跑当前的前端构建。

在仓库根目录安装 `requirements-desktop.txt`，然后运行 `scripts/build_desktop.ps1`，传入构建目录、输出目录、`ISCC.exe` 和 Python 解释器。脚本会安装锁定的前端依赖，把生成的界面打进安装包，成品是输出目录里的 `MediaOperatorSetup.exe`。版本号读仓库根目录的 `VERSION`。路径用本机环境变量，不要写进仓库。示例见 [`AGENTS.md`](AGENTS.md)。

只改界面、不打包时，在 `frontend` 里执行 `npm ci` 和 `npm run build`。产物写到 `app/static/desktop-ui/`。

## 第一次打开

侧栏从上到下是 **信箱**、**投稿**、**笔记**、**设置**。先把设置补齐，再投递。

1. **资料目录**：「设置 → 常规与目录」选择一个绝对路径。任务、媒体和未发布草稿都放在这里。换目录后需要重启应用。这里也可以导出一份脱敏诊断 JSON。
2. **转录模型**：「设置 → 转录与本地资源」点「检测本地环境」，再下载要用的 Whisper 模型。下载完成后可离线转录。缺少模型时，任务会在处理前提示。默认使用 `small`。
3. **DeepSeek**（翻译、投稿文案、观点摘录才需要）：「设置 → DeepSeek」填写模型名和 API Key，点「保存 DeepSeek 设置」。密钥进 Windows 凭据管理器，不写入设置文件。留空表示保留已保存的密钥。未配置时，默认模型名是 `deepseek-flash`。
4. **B 站投稿**：「设置 → B 站投稿」填入创作中心凭据：`SESSDATA`、`bili_jct`、`buvid3`、`DedeUserID`、`ac_time_value`。留空保留已保存的值。这是凭据字段，不是在应用里打开 B 站登录页。
5. **Obsidian**（只要笔记发布）：先在 Obsidian 里打开或创建一个库，再在「设置 → Obsidian」选择该库的根目录。目录里必须有 `.obsidian`。发布的观点和来源笔记写入其中的 `Media Operator` 文件夹。
6. **抖音 / 小红书**：公开链接读不到时，到「设置 → 站点登录」。可以打开站点登录窗口，或导入 Netscape Cookie 文本。导入或登录后的一小时内，该站点的链接会带上这次登录。YouTube、B 站和小宇宙不走这个登录页。
7. **NVIDIA**（可选）：仍在「转录与本地资源」的「转录加速」里选择安装目录。确认后首次下载约 1.2 GB。装好后勾选「使用 NVIDIA 加速」。自动模式优先用 GPU；GPU 失败时改用 CPU。严格 GPU 模式不会回退，见下文。

在线素材的预览和下载走 Windows 系统代理。系统代理拒绝连接时，界面会提示检查代理或网络，详细原因留在本地任务记录里。

## 使用工作台

### 在信纸上写信

首页左右各一只信箱：左边 **投稿**，右边 **笔记**。每只信箱一张横线信纸。

- 一行写一条：一个链接、一整段分享文案，或一个本机文件路径。
- Enter 换到下一行。一行写满时，右下角可以翻到下一页，左下角回到上一页。短窗口每页 5 行，否则 7 行。
- Ctrl+Enter，或点击信封上的火漆，把写了字的行投出去。火漆的名称是「投递投稿信件」或「投递笔记信件」。
- 投出后信封会封上并送进信箱。识别过程中不要把同一条再投一次。

一行里放了多条链接或路径时，这条会退回，原因是「每行只能放一条链接、分享文案或文件路径」。退回的纸条叠在信箱下方，点「恢复编辑」放回信纸。

### 投稿队列

打开侧栏 **投稿**。标题是「投稿工作台」，说明是「备齐设置，再点火处理」。

识别成功后状态是 **待设置**。投稿只收视频。音频会退回并说明需要视频；SRT/VTT 会退回并说明投稿只接收视频。已经在队列里的同一条素材标成 **已在队列**，不会再开一份任务。

待设置的来信旁边有四块木片，必须四块都备齐才能开始：

| 木片 | 里面有什么 |
| --- | --- |
| 输出 | 字幕是原文、译文还是双语；素材语言；画幅（原比例、16:9、9:16、1:1）；烧录编码；Whisper 模型和推理模式；清晰度、帧率、文件名 |
| 字幕样式 | 字体、字号、字重、位置、颜色、描边、双语顺序、可选背景条 |
| 投稿信息 | 封面与投稿内容。需要已保存的 B 站凭据；空白字段可交给 DeepSeek |
| 翻译上下文 | 背景说明和术语。翻译时才会用到 |

可以改「本次投递」里的全部稿件，也可以只改「当前稿件」。单条改过之后，点「恢复继承」回到本次投递的设置。改完一块后点「保存并放入火盆」，或一次点「使用当前设置备齐」。

四块都在火盆里之后，点「开始处理」。确认条会写明将生成字幕和成片并提交 B 站。勾选「我已确认素材使用权限及本次投稿信息」，再点 **确认并点火**。未勾选时不能提交。

处理中的阶段名称是：获取素材、Whisper 转录、生成中文译文、烧录字幕、提交 B 站。列表可以按全部、待处理、处理中、已完成筛选，也可以搜索标题。

成功后出现稿件卡，写着「投稿成功，等待审核」。点卡片会打开 B 站稿件链接。旁边的放映机播放成片。

失败或受阻时可以 **重试**，或「打开相关设置」。如果失败阶段是 B 站上传，会先弹出「确认上次投稿结果」：请到 B 站稿件管理确认没有成功，勾选「已检查，尚未投稿成功」，才能重试上传。这样是为了避免同一条成片投两次。

### 笔记队列

打开侧栏 **笔记**。标题是「笔记工作台」。

笔记信箱收下视频、音频、字幕文件（SRT、VTT）和分享文案。识别成功后会自动开始整理，不用点火，也不会投稿。没有 DeepSeek 密钥时，字幕可以先导入，整理会停在「请配置 DeepSeek，字幕已导入」。

同一条素材如果投稿侧已经下载、转写或翻译过，笔记侧会复用这些结果，只继续整理。

完成后，工作台一边是原文，一边是观点卡片。点时间戳回到原话。卡片上的译句、主题和说明可以改，改完会自动保存。点「发布到 Obsidian」后，每张卡写成一篇观点笔记，并链到共享素材页。发布成功并核对写入之后，对应的本地草稿会清掉。再次发布同一内容会指回原来的笔记。选择另存新版本会写成独立文件。发布失败的草稿可以重试。

### 删除和撤销

队列里能删的来信可以单条删除，或先勾选再「删除所选」。删除后 **10 秒**内，标题栏会出现 **撤销删除**。超时后撤销按钮消失，来信保持已移除。正在处理、不能删的条目，删除按钮是禁用的。

## 能贴什么

一行一条。分享文案里如果只有一个链接，整段可以贴在一行里，程序会取出链接、标题和作者（例如「某某的作品」）。

| 来源 | 程序认的地址 |
| --- | --- |
| YouTube | `youtube.com`、`youtu.be` |
| Bilibili | `bilibili.com`、`b23.tv` |
| 抖音 | `douyin.com`、`iesdouyin.com` |
| 小红书 | `xiaohongshu.com`、`xhslink.com`、`xhslink.cn` |
| 小宇宙 | `xiaoyuzhoufm.com` |
| 本机文件 | 单独一行的 Windows 路径、带引号的路径、`\\服务器\共享\文件`，或 `file:///` |

投稿只要视频。笔记还可以收音频和 SRT/VTT。抖音、小红书读不到公开页面时，先完成站点登录或导入 Cookie。

## 设置对照

| 分类 | 保存什么 |
| --- | --- |
| 常规与目录 | 资料目录；导出脱敏诊断 |
| 站点登录 | 抖音、小红书的登录窗口或 Netscape Cookie，约一小时有效 |
| 输出与字幕默认值 | 新投递使用的输出和字幕样式。工作台里的「重置」回到这里 |
| 转录与本地资源 | 环境检测、Whisper 模型下载、NVIDIA 运行库 |
| DeepSeek | 模型名和 API Key |
| B 站投稿 | 五段创作中心凭据 |
| Obsidian | 已有 Vault 的根目录，或解除连接 |

输出里和日常使用相关的选项：

- **字幕输出**：原文字幕、译文字幕、双语字幕。
- **推理模式**：自动（NVIDIA 优先）、严格 GPU（只使用本地模型和 CUDA，CUDA 不可用就停止）、精准、自动补漏、快速。
- **烧录编码**：自动（NVIDIA 优先，不可用则 CPU）、NVENC、CPU（libx264）。
- **字体**：安装包带思源黑体（Source Han Sans CN）和思源宋体（Source Han Serif CN）的 Light、Regular、Bold。也可以填系统里已安装的字体名，列表里有微软雅黑、黑体、宋体、楷体等。

## 无界面 API

可选。它和桌面共用下载、转录、翻译、烧录、投稿，但没有桌面那套本机会话，也没有工作台。桌面程序不读取这里的令牌。

`python -m app.main` 和 `scripts/serve_api.sh` 默认只听 `127.0.0.1:8090`。`MEDIA_BIND_HOST` 不是 `127.0.0.1`、`localhost` 或 `::1` 时，必须先设置 `MEDIA_API_TOKEN`，否则进程直接退出。令牌配上之后，每个请求都要带下面之一：

- `Authorization: Bearer <token>`
- `X-Media-Token: <token>`

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# 编辑 .env。密钥不要提交。
.venv/bin/python -m app.main
```

Docker Compose 示例在 `docker-compose.yml`，端口只发布到宿主机的 `127.0.0.1:8090`。要把容器暴露到别的网卡，先设置 `MEDIA_API_TOKEN`，再把 `MEDIA_BIND_HOST` 改成 `0.0.0.0`，并改端口映射。直接用 `uvicorn --host 0.0.0.0` 会绕过脚本里的拒绝逻辑；对外发布时请用 `serve_api.sh` 或 `python -m app.main`，并带上令牌。

健康检查是 `GET /health`。未设置令牌时，本机可以直接访问。设置了令牌就必须带上。

## 遇到问题时

- **检测里 FFmpeg、ffprobe、yt-dlp 或 Deno 未通过**：重新运行安装程序。源码运行时，这些程序需要在 PATH 上，或用 `FFMPEG_BIN`、`FFPROBE_BIN`、`YT_DLP_BIN` 指到可执行文件。
- **转录提示缺少模型**：到「转录与本地资源」下载对应模型。严格 GPU 模式不会在缺少本地模型时改用 CPU。
- **GPU 安装失败或自动模式变慢**：可以继续用 CPU。确认目录是绝对路径，并且没有同名的未完成文件夹。自动模式在 GPU 失败后会用 CPU 再试；只有「严格 GPU」会停住。
- **NVENC 不可用**：烧录编码选「自动」或「CPU」。NVENC 不绘制字幕，字幕仍要 FFmpeg 的 libass。
- **在线链接连接失败**：看 Windows 系统代理是否可用。桌面没有单独的代理地址栏。无界面服务可以用环境变量 `YT_DLP_PROXY`。
- **抖音或小红书要登录、Cookie 过期**：回到「站点登录」。登录窗口或导入的 Cookie 大约一小时内有效，过期后重新登录或再导入。
- **B 站投稿失败**：核对五段凭据是否仍有效。重试上传前先到稿件管理确认没有成功。
- **Obsidian 选不中目录**：要选库的根目录，里面得有 `.obsidian`。发布写入 `Media Operator` 文件夹，不改 Vault 里的其他笔记。
- **换了资料目录却还是旧任务**：保存后重启应用。
- **关闭窗口被拦住**：还有批次、生成、模型下载、NVIDIA 安装或 Obsidian 写入在进行。等它们结束再关。

## 给改代码的人

```text
desktop_entry.py
    └─ app/desktop.py          pywebview 窗口，仅绑定 127.0.0.1，Cookie 会话
           ├─ app/main.py      配置、请求模型和对外名字
           │    └─ app/stages/ 下载、转录、翻译、烧录、B 站投稿、HTTP API
           ├─ app/desktop_routes.py
           ├─ app/workbench_inbox.py    双信箱队列
           └─ app/whisper_worker.py     单独的转录进程
frontend/                      React 工作台，构建到 app/static/desktop-ui/
```

`app/stages/` 在导入时执行进 `app.main`。桌面、转录进程和测试都 `import app.main`，并在这个模块上替换路径或函数。站点解析在 `app/sites/` 和 `app/desktop_sources.py`。Obsidian 写入在 `app/obsidian.py`。

| 部分 | 选用 |
| --- | --- |
| 桌面壳 | Python 3.12、pywebview、WebView2、PyInstaller、Inno Setup |
| 服务 | FastAPI、uvicorn、pydantic |
| 媒体 | FFmpeg、ffprobe、yt-dlp、Deno、faster-whisper、ctranslate2 |
| 投稿 | bilibili-api-python |
| 界面 | React 19、TypeScript、Vite |
| 可选云端 | DeepSeek 对话接口 |

本地检查：

```bash
python -m pip install -r requirements-dev.txt
ruff check app tests desktop_entry.py
python -m pytest -q
```

`ruff` 只查会在运行时出错的规则，不按风格重写仓库。`tests/test_desktop.py` 只在 Windows 上收集。一条依赖 Windows 路径的工作台测试，在其他系统上会跳过。

GitHub Actions（`.github/workflows/ci.yml`）在 Ubuntu 上跑 ruff、pytest 和 `npm run build`，在 Windows 上先构建桌面界面，再分两次跑桌面测试和其余测试。推送到 `main` 或 `dev`，以及拉取请求，都会触发。

更短的桌面试用步骤在 [docs/DESKTOP_QUICKSTART.md](docs/DESKTOP_QUICKSTART.md)。

## 仓库里还有什么

- [`AGENTS.md`](AGENTS.md) 是打包约定，路径用环境变量。
- [`packaging/THIRD_PARTY.md`](packaging/THIRD_PARTY.md) 和 [`frontend/THIRD_PARTY.md`](frontend/THIRD_PARTY.md) 记录随包组件的许可。
- [`docs/archive/VALIDATION-0.3.0.md`](docs/archive/VALIDATION-0.3.0.md) 是 0.3.0 的历史验证笔记，不是当前版本的结论。

## 许可

本仓库源码使用 [MIT License](LICENSE)。安装包另外带有 FFmpeg、字体和 Python 依赖自己的许可，见 `packaging/THIRD_PARTY.md`。
