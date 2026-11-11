# 书房动效与材质

工作台从里到外是一间暖光书房。光源只有左上方一处，阴影用同一套暖棕色，不再用蓝灰。

## 材质

程序生成、打进样式的平铺图在 `frontend/public/workbench/materials/`（由 `frontend/fixture/textures.py` 重新生成）：

| 图 | 用在 |
| --- | --- |
| `walnut.webp` | 桌面外框 |
| `leather.webp` | 左侧缝线皮革 |
| `linen.webp` | 信箱、队列的亚麻垫 |
| `paper.webp` | 信纸、设置页、纸条、成功卡 |
| `brass.webp` | 边栏黄铜信槽 |
| `torn-mask.webp` | 退回纸条的纤维毛边 |

已接上、以前没用的插图：`mailbox/brazier/shredder/trash` 的 `*-shadow.webp` 接触阴影、折信时的 `paper-bend` 图集、投影幕 `projector-light-screen-open`、42px 衬线 `.progress-number`。

按钮是有顶高光和底边的体积按钮。按下只改 `transform`（下沉），松开用带回弹的曲线弹回。输入框是内凹槽。火漆、折角、木柴、导航铭牌同样是按下快、松开弹。

## 动效 token

`frontend/src/motionSystem.ts`

- `SPRING.soft`：刚度 180、阻尼 18.8、质量 1。阻尼比约 0.70，过冲约 5%，大约 0.6 秒落定。用于飞行、翻页、抽屉。
- `SPRING.press`：刚度 460、阻尼 30。用于按钮类的更快回弹。
- `ramp(u, a, b)`：平滑阶跃。投递的折、塞、封、入、飞在时间上重叠，所以段与段之间速度不归零。
- CSS 曲线 `--spring: cubic-bezier(.18, 1.28, .32, 1)`。按下用 `--press`，大约 80ms。

飞行（折信、翻页、木柴、任务纸、进垃圾桶、退回条）只写 `transform` 和 `opacity`，必要时 `clip-path`。`left/top/width/height` 只在开始和落地各写一次。途中不再改 `z-index`。透明度用交叉淡入，不用硬切。

`prefers-reduced-motion` 时跳过飞行，CSS 动画和过渡被关掉。

## 进出场

- 信箱 ↔ 投稿 / 笔记：抽屉式平移，落地大约 4% 过冲。
- 投稿 ↔ 笔记：同一张桌面上推拉。
- 设置：从左侧书脊翻开的皮面手册。
- 设置信、点火条、处理日志、撤销条、成功卡、退回纸条：`Presence` 同时做进入和离开。
- 换一封信：先短离场，再换上新信。
- 投影幕：整块幕布用 `translateY` 放下来，不再拉宽高。
- B 站凭据折叠：高度用网格行过渡，箭头仍是弹簧。

## 本地预览

```bash
cd frontend && WORKBENCH_FIXTURE=1 npx vite --host 127.0.0.1 --port 5173
```

打开 `/static/desktop-ui/#home`。夹具在 `frontend/fixture/plugin.mjs`，不进生产构建。
