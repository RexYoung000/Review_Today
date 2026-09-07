# 吉祥物随机待机与眼部修正

2026-09-07，已实现，待 Rex 视觉验收。接入待处理空态；不改变思考和语音停止后的收尾。

## 表现与播放

- 黑色和银白主体均为白眼白、黑瞳孔。银白主体仅眼眶有约 1 pt 中性深灰细线，随眨眼缩放，身体无外描边。
- 四段 Spine 轨道：`idle_look` 4 秒，`idle_hop` 3.2 秒，`idle_stretch` 3.6 秒，`idle_book` 6 秒。无手造型，本子悬浮展开、翻页和收起，无文字。
- 首次等待 1 秒；每段完整结束后停顿 1.5–3 秒，从另外三段等概率选择，不连续重复。停顿轻微呼吸。
- 隐藏暂停，恢复不追赶；销毁后重新进入重新选择。减少动态效果立即静止，收起道具。
- 原角色网格、权重、原有骨骼索引及既有动画轨道逐项比较未改变。新增两个道具骨骼、两页独立 atlas 纹理。

## 查看入口

App：`output/default-brand-build/Build/Products/Debug/Review_Today.app`，进入「待处理」无任务页面，保持窗口前台观察轮播。

HTML：运行 `node tools/mascot-motion/src/build-idle-preview.mjs`，直接打开生成的 `output/idle-web/index.html`。提供单段、随机、重新开始、浅深、半速、减少动态与 App 尺寸；底部显示当前动作或停顿倒计时。无需模型、麦克风或网络请求。

当前会话的内置浏览器安全策略拒绝打开本地 HTML，因此没有声称 HTML 控件完成浏览器交互验收。未尝试绕过；共享渲染与状态控制通过原生 WKWebView 测试。

## 验证与证据

- 27 项测试通过：既有动效回归、1000 次随机选择不重复、间隔范围、单段完成、固定随机种子重放、四段正向三角形与首尾姿态、本子收起、瞳孔不越出眼白。
- 原生运行检查通过：思考/语音、停止、零声量、减少动态、隐藏暂停、待机推进、指定本子动作打开、减少动态时道具立即收起；装饰层不抢输入焦点。
- Debug 构建与签名检查通过；实际 App 查看浅深主题小尺寸角色与眼眶。未做真实麦克风、VoiceOver 全流程或 macOS 27 验证。
- `evidence/idle_look.mp4`、`idle_hop.mp4`、`idle_stretch.mp4`、`idle_book.mp4` 与 `random.mp4` 为同一 Spine、材质和调度模块的离线渲染短视频，不是原生屏幕录制。
- `eyes-light.png`、`eyes-dark.png`、`notebook-dark.png` 用于放大检查。原生窗口截图保留于本次任务的界面检查记录。

重建资源：`node tools/mascot-motion/src/build.mjs`，然后 `node tools/mascot-motion/src/build-native.mjs`。
重建视频：`node tools/mascot-motion/src/render-idle.mjs`。
