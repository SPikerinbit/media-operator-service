# Media Operator 0.5.0 本机修复与复验

**结论：本机修复、打包及覆盖更新已完成，最终成品验收仍不通过。** 未测、部分通过不计通过。72 项逐项状态已填写到 [验收清单](ACCEPTANCE_PLAN.md)。真实账号、另一台无 NVIDIA 机器、Windows 100%/150% 实际组合及完整动效签收仍有缺口。

源码基线为 `195d4c9789a69d2c4fde2b97cac2494eb4965525`，本轮改动尚未提交。版本保持 **0.5.0**。不能用基线提交的历史 CI 成功替代本轮修改的远端 CI。安装包附带 `build-manifest.json`，记录本次源文件、前端资源和两个可执行文件的 SHA-256；构建产物与安装目录逐项核对。

## 已实现

- 首页双信箱居中，设置整体居中，工作区按容器宽度切换四档布局；窄屏可收起来信列表、切换观点/原文，内容和按钮可纵向滚动到达。结构规则集中到 `workspaceLayout.css`，移除了原有列宽、负偏移和相关 `!important` 覆盖。原生窗口按当前显示器工作区域和 DPI 计算尺寸。
- 首页、拨杆和笔记会话共用三档状态，后端接受 `summary`；切档不生成，重新提取发送当前档位，先保存人工编辑。拨杆支持方向键、Home、End 及弹簧回弹。
- Whisper 即时保存原始失败、设备、计算类型和阶段；每 15 秒报告活动，标明 CPU/GPU。GPU 无阶段进展默认 180 秒终止，CPU 默认 900 秒，可用 `MEDIA_WHISPER_IDLE_TIMEOUT` 调整。自动模式仅在独立 CPU 进程中重试一次，严格 GPU 不降级。取消入口终止转录，已完成的可复用阶段保留；同一轮显示进度不倒退。
- 折纸三面使用同一全文表面；封舌正反面共享铰链，修复背面绕自身中心翻转导致的悬浮；缩放、切页和结束清理临时物件。准备与处理共用火盆木块落点及尺寸、盆内裁切，点火采用连续位移；飞纸在电视下方的处理区进入。成片保留比例，并提供加载、失败和重新载入状态。
- 碎纸机侧面拨杆让出主要机身，去掉额外拉长黑缝；托盘纳入机器边界，纸屑改为小方片。连线从托盘纸片实测位置连接观点卡左缘，跟随滚动、卡片和容器尺寸。隐藏页暂停持续绘制。
- 四平台使用可辨认字形标识，账号行底色一致。临时 Cookie 导入覆盖四站并接入首页投递，明确区别于持久登录及 B 站投稿凭据。检查 Cookie 本地到期与 B 站凭据完整性，微信读书明确拒绝登录时使状态失效；全站在线有效性仍未签收。
- 引导先建立四个平台结构，以原生 `dialog` 限定焦点，实体滑出后按完成事件清理；完成标记写入本机设置，解决随机端口及临时浏览器存储导致的重启反复弹出。隐藏页面设置 `inert`、`aria-hidden`；切页管理焦点，减少动态变化不会卡住切页状态。
- 桌面工厂不再修改共享 headless 应用的路由和中间件；CI 增加 Windows 单进程完整测试，保留分进程检查，lint 范围统一为全仓。补齐冻结包遗漏的 `VERSION` 和动态执行的 `app/stages/*.py`，构建脚本在生成安装包前实际运行冻结 worker 的导入检查。

## 可复验结果

| 检查 | 结果与证据 |
|---|---|
| 全部后端测试 | **84 passed**，2 项 FastAPI 既有弃用提示；[日志](../data/polish-20261112/pytest.log) |
| 静态检查 | `ruff check .`、`git diff --check` 通过 |
| 前端及安装包构建 | 构建脚本执行 `npm ci` 和构建；冻结运行时检查通过；仍有约 542 kB 主 JS 分块提示；[构建日志](../data/polish-20261112/build.log) |
| 三档与尺寸回归 | 三档请求、方向键、编辑保留、引用定位、隐藏页焦点、减少动态和缩放清理通过；11 组逻辑尺寸 × 4 页面通过；[请求及尺寸结果](../data/polish-20261112/ui-final/ui-results.json) |
| 真实 source supervisor | CPU、自动 GPU、严格 GPU 实际转录，进度单调；[参数和进度](../data/polish-20261112/supervised-transcription.json) |
| 同一安装构建的 worker | CPU **8.42 s**、自动 GPU **6.30 s**、严格 GPU **5.12 s**，均生成有效字幕；仅为本机 12.63 秒样片观测；[实际安装 worker 结果](../data/polish-20261112/packaged-transcription.json) |
| GPU 原问题 | 标准、批处理、严格模式均完成，原 227 秒阻塞未再现，不能宣称根因已确定；[复现记录](../data/polish-20261112/gpu-reproduction.json)。故障、超时、取消、严格模式及 CPU 单次回退另有自动化覆盖 |
| 安装后真实内容 API | SRT 导入、SRT/Markdown 实际落盘，隔离 Obsidian 库首次写入、重复指回、另存版本、失败后重试，原测试文件保持原摘要；[结果](../data/polish-20261112/installed-service-results.json) |
| 原生首次启动及重启 | [首次引导](../data/polish-20261112/installed-first-launch.png)；新端口、空浏览器完成标记时仍不重弹；[重启结果](../data/polish-20261112/installed-restart.json) |
| 真实处理中关闭 | 实际长样片处于转录阶段时原生关闭被拦截；[状态](../data/polish-20261112/closing-task.json)、[提示截图](../data/polish-20261112/native-close-protection.png)。该隔离验收任务随后为安装更新而停止，不计作长样片完成 |
| 同构建安装与卸载 | 独立目录安装、真实启动、卸载后保留独立资料和配置，随后覆盖回原安装目录；[隔离安装](../data/polish-20261112/isolated-install-result.json)、[卸载](../data/polish-20261112/uninstall-result.json)、[覆盖安装](../data/polish-20261112/production-install-result.json) |
| 版本、目录、文件一致性 | 原安装目录 `D:\Media Operator`，卸载信息为 0.5.0；可执行文件、145 个前端资源和源文件清单核对通过；安装时间戳与本次产物相差不足 2 秒，为安装包时间戳精度差，文件 SHA-256 完全一致 |
| 原资料保留 | 原设置摘要与原 **31** 张观点卡全部内容摘要一致；[保留核对](../data/polish-20261112/preservation-after.json) |

尺寸矩阵为逻辑视口验证，`actual_browser_dpr` 单独记录；`scenario_scale` 只标明模拟场景，不能当成真实系统缩放。原生最大化另有 [截图](../data/polish-20261112/native-maximized.png) 和 [窗口/显示数据](../data/polish-20261112/windows-display.json)。没有通过改 Windows 显示设置完成全部 100%/150% 组合。

## 动效与性能边界

录制及无采集对照都使用**真实 WebView2 窗口 + 受控 fixture 后端**；本地视频实际播放到 `readyState=4`。fixture 的完成、失败和观点内容不证明外站投稿成功或真实模型输出。铭牌展开日志前后均为同一矩形。

全桌面录制的 [元数据](../data/polish-20261112/video-metadata.json) 显示标称 60fps、实际平均约 53.05fps，**不足以充当有效 60fps 动效签收录像**；采集期间 RAF P95 约 50.2ms。移除录屏后的同流程 [对照](../data/polish-20261112/native-motion-control.json) 为 RAF 中位数约 16.7ms、P95 约 17.0ms、最大约 99.8ms。这说明采集开销明显，不能把采集帧率直接称为应用流畅度，也不能据此签收“中端机器全程流畅”。

[窗口裁切录像](../data/polish-20261112/native-fixture-window-60fps.mp4) 标称 60fps，实际平均约 **59.96fps**；[采集元数据](../data/polish-20261112/window-video-metadata.json) 与 [原生帧时间](../data/polish-20261112/native-motion-window-results.json) 分别记录。应用 RAF 中位数约 16.7ms、P95 约 17.0ms、最大约 150.3ms，仍有少量长帧，不签收全程稳定 60fps。

已提供四组各 **60 个连续相邻帧**，没有插帧或重复帧补齐：[合封](../data/polish-20261112/frames-sealing-60-consecutive.png)、[点火](../data/polish-20261112/frames-ignition-60-consecutive.png)、[删除撤销](../data/polish-20261112/frames-delete-undo-60-consecutive.png)、[引导离场](../data/polish-20261112/frames-onboarding-exit-60-consecutive.png)。连续帧中定位出的封舌背面旋转原点问题已修复，并以浏览器铰链位置检查防止复发。

## 仍需完成才能最终签收

1. 提供测试账号、授权素材及实际 B 站测试提交授权，完成真实登录、失效重登、投稿与站点提取。未使用用户现有密钥或账号进行这些外部操作。
2. 使用测试 DeepSeek 密钥验证真实三档数量/详略、错误密钥、超时及无效引用；fixture 不作为模型质量证明。
3. 在另一台无 NVIDIA 机器运行；完成真实 Windows 100%/150%、1280×800/1920×1080 和连续缩放组合。
4. 补齐干净 Windows 用户安装；本轮独立资料目录及独立安装目录不冒充新 Windows 用户。
5. 继续按连续帧复核合封逐像素一致、飞行遮挡、火焰光影、纸屑落入托盘与全程帧时间，达到录制和应用流畅度标准后再签收。

首次安装尝试暴露的缺资源失败及采集负载过高记录已保留用于诊断，均不计通过证据。当前交付以修复后同一构建的安装和复验结果为准。
