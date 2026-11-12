# 待修改

还没做的改动记在这里。下面这一项只记录问题和做法，代码尚未改。

## 本地 GPU 排队，显存不足仍留在 GPU

记录日期：2026-11-12。版本仍是 0.5.0。

### 问题

Whisper 已经在用 NVIDIA GPU。这次失败不是没开加速，而是两路严格 GPU 转录同时占同一张卡，显存不够，进程退出。

两路都是 `gpu_only`、`large-v3-turbo`、`device=cuda`、`compute_type=int8_float16`、`batch_size=4`：

- `jobs/stage_transcribe_ea7ca1d98429`：2026-11-12 15:01:22 UTC 开始，音频 545.9 秒。15:01:33 在 faster-whisper 的 `encode` 里报 `CUDA failed with error out of memory`，进程 32536。
- `jobs/stage_transcribe_88b90f37528c`：15:01:33 开始，音频 1402 秒。15:01:46 同样显存不足，进程 36652。

两路重叠约 13 秒。工作台默认 `batch_concurrency=2`（`app/workbench_inbox.py` 提交批次，`app/desktop_jobs.py` 的 `enqueue` 用这个并发）。两份 large 模型各自再按 batch 4 推理，挤在同一张卡上。

严格模式在 `app/stages/transcribe.py` 里遇到 CUDA 错误就停止。它不改用 CPU，也不换更小的 batch。worker 进程因此直接退出。

同一张卡空出来之后，单路转录是成功的：

- `stage_transcribe_3529419cfecc`：3872.8 秒，15:02:21–15:05:35，`cuda` / `int8_float16`。
- `stage_transcribe_2ad493789df4`：545.9 秒，15:05:36–15:05:59，同样是 CUDA。

烧录 `stage_burn_132ce756f81e` 已是 NVENC，且 `decode=cuda`，1080p 约 12.7 倍速。字幕 `ass` 滤镜仍在 CPU 上绘制，这是现有设计，不在这项里改。

下载、翻译、投稿没有本地 GPU 工作：下载是网络和封装，翻译走 DeepSeek，投稿走网络。这三步不改成 GPU 加速。

### 计划中的改法

只动后端调度和转录重试。前端、烧录画质参数，以及严格模式「不回退 CPU」，都不动。

- 在已经会打进安装包的 `app/desktop_config.py` 加一把进程内 GPU 锁。CUDA 转录子进程，以及 NVENC / CUDA 解码烧录，进入前取得这把锁，结束或失败后释放。下载和翻译不取锁，批次仍可同时做网络步骤。第二路只在轮到转录或烧录时等待。
- `app/stages/transcribe.py`：CUDA 转录包在这把锁里。错误文本含 `out of memory` 且模式是 `gpu_only` 时，不改 `WHISPER_DEVICE`。丢掉已退出的 worker，用新进程、同一张卡、`WHISPER_BATCH_SIZE=1` 再跑一次。worker 启动时读这个环境变量（`app/main.py` 的 `WHISPER_BATCH_SIZE`，`app/whisper_worker.py` 用于 large 模型）。再失败才按现在的文案停止。其它 CUDA 错误仍然一次就停，不降 batch，也不改 CPU。自动模式现有的 CPU 回退保持原样。
- `app/stages/subtitles.py`：NVENC 烧录（先尝试 CUDA 解码，失败再软件解码加 NVENC）包在同一把锁里。解码失败仍只回退软件解码。只有 NVENC 自身失败时，才走原来的 libx264 回退。

### 做的时候要改的测试

- `tests/test_transcription_recovery.py` 的 `test_strict_gpu_preserves_failure` 现在要求显存不足只调用一次 CUDA。改为两次都是 `cuda`，第二次 `WHISPER_BATCH_SIZE=1`，仍然抛出显存错误，并且不出现 `cpu`。
- `tests/test_desktop.py` 的 `test_strict_gpu_does_not_fall_back` 用的是 `CUDA unavailable`，不是显存不足，保持只调用一次。

做完后版本保持 0.5.0，按现有脚本打包并覆盖安装。
