# 0.5.0 动效工作台交付记录（2026-11-12）

分支：`polish/dev-motion-workbench`。远端参照固定为 `195d4c9`；当前本地修复完整保存为 `7bcd93e`，并标记 `motion-workbench-local-baseline`。版本保持 0.5.0。

本轮按“可靠触发、同一物件连续运动、机器位置固定、内容内部滚动”实施。最终原生窗口动效验收尚未签收：本机桌面控制连接不可用，隔离 WebView2 辅助窗口启动被自动审批拒绝（仅返回 `blocked by policy`）。浏览器录像、API 和截图均不替代原生窗口、实际 Windows 100%/150% 缩放与连续帧签收。

## 实现

- 投递响应与推送独立对账，以投递 ID 去重；等待识别期间保留冻结输入，失败可直接重试。折纸、装封、合封压蜡、入箱、分送统一为 980/420/560/980/480 ms；隐藏页面暂停，返回续播，缩放跟随当前几何。侧栏数量在送达时更新。
- 首页去除拨杆，双列场景居中；按素材轮廓计算信纸和信封的间距，打开封舌时动态让位。
- 笔记接收只分类与检查文件，不提前读取正文、转录或调用 AI。`POST /desktop/inbox/groups/{id}/start` 接受 `notes_mode`，锁内登记任务，重复请求不重复启动。每条任务独立保存选择及执行档位。重新整理前保存编辑并复用原文，无密钥时仍可取得原文。
- 笔记四种状态共用机器布局；队列、观点、原文各自滚动，窄窗口使用队列抽屉和内容标签。长标题不增加队列行高；短窗口仍可操作开始按钮。
- 分离笔记进纸和投稿燃烧；保留火盆准备、点火、暖光和预览。恢复持续纸屑，当前组全部八张观点按稳定 ID 关联纸片；删除观点连线，点击纸屑只定位内容框。
- 删除在请求前保存纸面、位置和占位；成功项独立揉纸、错峰投桶，最多三个可见纸团，桶前沿覆盖入桶纸团。失败项保留，撤销恢复选择，切页取消会结清等待并清理节点。

## 验证与证据

- 后端：87 项通过，两个既有 FastAPI 弃用提示。[日志](../data/motion-polish-20261112/pytest.log)
- TypeScript 与 Vite 构建通过；仍有主 JS 大于 500 kB 的既有构建提示。[日志](../data/motion-polish-20261112/frontend-build.log)
- `ruff check .`、`git diff --check` 通过。
- 新的可复跑界面验收：[tests/verify_motion_workbench.py](../tests/verify_motion_workbench.py)。使用隔离 fixture，覆盖两种投递顺序、暂停/缩放续播、网络恢复、部分退信、三档重新整理与编辑保存、两页批量部分失败/撤销/切页取消、31 张观点和 600 段长原文、独立滚动、短窗口及减少动态。[结果](../data/motion-polish-20261112/browser/results.json)
- 原有界面回归也通过：三档请求、键盘换档、编辑保留、44 个页面/尺寸组合、隐藏页焦点隔离、信封铰链、缩放续播和减少动态。[结果](../data/motion-polish-20261112/legacy-ui/ui-results.json)
- 1280×800、1920×1080、1280×720、853×533 是浏览器逻辑视口，不是 Windows 实际缩放。[截图目录](../data/motion-polish-20261112/browser)

## 同场景动态对照

同为 1280×800、同一受控后端、单次队列推送先于 HTTP 响应，抑制无关推送；分别实际加载三个版本构建资源，记录模块文件名核对版本。结果：`dev` 与修改前均停留 `identify`，删除没有飞纸；修改后完整走过五段到 `idle`，删除可见纸团。

| 版本 | 动态记录 |
|---|---|
| dev `195d4c9` | [录像](../data/motion-polish-20261112/comparison/dev/same-scene.webm) |
| 修改前 `7bcd93e` | [录像](../data/motion-polish-20261112/comparison/before/same-scene.webm) |
| 修改后 | [录像](../data/motion-polish-20261112/comparison/after/same-scene.webm) |

[对照结果与逐帧 RAF 采样](../data/motion-polish-20261112/comparison/comparison.json)。这是 headless Edge 的受控竞态录像，不是 WebView2 成品签收录像；录制帧率与应用 RAF 分开记录，不能推断全程稳定 60fps。

三份录像均为 1280×800、VP8、25 fps。修改后 RAF 帧间隔中位数 16.7 ms、P95 17.3 ms、最大 116.5 ms；此次对照期间机器同时在构建安装包，数据用于保留实际采样，不作为稳定帧率结论。[分项统计](../data/motion-polish-20261112/comparison/frame-metrics.json)。修改后录像已导出[全部连续帧](../data/motion-polish-20261112/comparison/after/frames)及[概览图](../data/motion-polish-20261112/comparison/after/contact-sheet.png)。

## 构建与安装

已按仓库脚本完成 PyInstaller、冻结运行时启动检查和 Inno Setup 构建，2026-11-12 13:40 静默覆盖安装成功，无需重启。安装目录为 `D:\Media Operator`，程序已启动，窗口标题为 Media Operator，WebView2 子进程与本地服务均已创建，没有新增启动错误。此项仅确认启动，不替代三条原生动效签收。[构建日志](../data/motion-polish-20261112/build.log)、[安装日志](../data/motion-polish-20261112/install.log)、[启动记录](../data/motion-polish-20261112/installed-startup.json)。

安装包来自干净提交 `a78c8d4`，版本及卸载信息均为 0.5.0。两个程序的 SHA-256 与构建产物和清单一致，修改时间在安装时间戳精度内一致；145 个前端文件与 228 个运行时源码摘要全部匹配。设置文件与原有 31 张观点的完整摘要在安装前后相同。[安装核对结果](../data/motion-polish-20261112/installation.json)、[更新前核对](../data/motion-polish-20261112/preservation-before.json)。上一安装包保留在本机输出目录的 `setup-before-motion.exe`。

实施提交依次为：`7bcd93e` 本地基线、`fa779a0` 笔记确认接口、`fa508f6` 投递竞态及连续动作、`2f1772b` 固定工作台与纸团投桶、`a78c8d4` 回归覆盖及木块/机器位置修复。文档验收记录另行提交，不改变运行时产物。

## 保留验收项

1. 安装后原生 WebView2 三条完整动作、最大化恢复、Windows 实际 100%/150% 缩放。
2. 原生连续关键帧的纸张接缝、箱口与桶沿遮挡、托盘碰撞和火盆层级人工签收。
3. 真实外站、账号、模型生成质量延续既有验收边界；fixture 不证明真实投稿或 AI 输出质量。
