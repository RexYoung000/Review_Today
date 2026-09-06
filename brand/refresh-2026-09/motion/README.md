# 吉祥物融合动效预览

> 2026-09-07：本目录保留为早期位图节奏对照。新的骨骼、权重与局部形变小样见 [motion-rig](../motion-rig/README.md)，制作接口见 [动画 MCP](../../../tools/mascot-motion/README.md)。下文为 09-06 的历史验证，不代表新小样的能力。

2026-09-06。Rex 已确认探索「主体分出一小块绕行」和「波浪上的弹性角色」。本轮制作可操作的浏览器预览，比较分离/重组、波浪跟随以及状态即时响应。当前 V3 只作为临时角色母形，不代表静态造型定稿。

- 思考：沿用环绕等待的概念，从角色身体分出小块，再聚回；眼睛始终留在主体。
- 语音：让角色承担原波浪上方点的运动角色，增加挤压/拉伸；使用明确标注的模拟波浪，不开启麦克风或接入语音。
- 同一角色可以在思考、语音、静止、异常之间立即切换；不等待循环结束，不安排新的页面或角色入口。
- 现有原生 DotsRing 占 18 px，真实状态仍由 RunPhaseLine 驱动。预览提供 18/24/32 px 对照；放大预览不证明角色在实际小尺寸清晰。
- 预览使用 Canvas 变换和图片遮罩验证节奏，不是 Spine 工程、拆件交付或原生 App 集成。已选 R Logo 与日常 App 不变。
- 减少动态效果采用静止角色和状态文字；标签页隐藏时暂停绘制，连续点击以最后选择为准。

## 透明素材提示词（内置 ImageGen）

Use case: identity-preserve / transparent mascot asset extraction.
Extract ONLY the large LEFT teal pebble mascot from the attached Review Today concept sheet into one single reusable transparent PNG sprite. Preserve its broad horizontal asymmetric pebble silhouette, original proportions, two small white capsule eyes with teal pupils looking slightly to the right, and exact placement of the eyes. No redesign. The user is evaluating motion with this provisional character, so maintain identity. Center this single full character on a square canvas with 10% clear space around the widest dimension. Genuine transparent alpha everywhere outside the character, not a checkerboard printed on a background. Entire body fully opaque deep teal, clean edge antialiasing. No text, miniatures, other poses, page background, shadow, glow, border, gradient or new features. Single character only. This is a transparent sprite for an animation preview, not a presentation sheet.

## 预览操作与边界

打开 `index.html`（与 `motion.js`、`style.css`、`sprite.png` 保持同目录），或从本目录启动本地静态服务器。

1. 左侧「开始思考」→ 任意时刻「重组 / 停止」；也可在绕行中「模拟异常」再重新开始。
2. 右侧连续切换「聆听 → 思考 → 回应 → 停止」，同时调节模拟声量。
3. 对照实际 18/24/32 px 占位，切换深色与减少动态效果。模拟声量为零时不继续起伏。

本轮从同一透明 PNG 用遮罩取出一小块，主体随分离轻微收缩，聚回后恢复体积；避免留下大缺口像被咬掉一块。两只眼睛保留在主体；没有代码重画角色。波浪参考已有 15 条圆角条和上方点的运动概念，当前仅为模拟轨迹。具体轨迹、形变幅度和时长都是待视觉评估的提案，不视为原有动画的精确复制。

角色主体在 18 px 占位下会明显变小，这是本轮需要判断的实际取舍；不能用放大演示代替原生小尺寸验收。静态造型、Spine 拆件、真实收音/语音节奏和原生性能不在本次完成声明内。

### Alpha 修订

首轮生成的棋盘格写入 RGB（无 Alpha），未采用。第二轮使用以下提示词取得真实透明 PNG，并验证四角透明、计算有效轮廓边界后供预览等比裁切显示；未重画眼睛或身体。

Remove ONLY the fake gray/white checkerboard background from this teal pebble mascot. Return the same mascot with TRUE TRANSPARENT ALPHA, NOT a picture of transparency. Preserve the exact silhouette, proportions, placement, eye shapes and white eyes with teal pupils. Keep all antialiased edges intact. One square PNG, no new text, no shadows, no border, no grid, no background color. Every checkerboard square must disappear into zero alpha. Do not draw checkerboard, do not make background white or black. Actual transparency is required for use as an app sprite. Do not redesign the mascot. The entire teal body and white eye shapes remain opaque.

## 本轮验证

- `node --check motion.js` 通过；透明素材包含真实 Alpha，有效显示边界为 x=129、y=227、999×774 px。
- 在 Codex 浏览器 1280 px 宽度实际打开并点击：思考启动、中途重组、模拟异常、异常后重新开始；聆听→思考→回应→停止的连续切换，状态文字与选中按钮同步更新。
- 实际查看浅深主题、减少动态效果、放大动画和 18/24/32 px 对照。减少动态效果时角色恢复完整静止并保留状态文字；声量滑杆可以用键盘 Home/End 调到 0/100%。已查看零声量静止和高声量起伏。
- 检查到 1280 px 页面无横向溢出；465 px 窄面板的单列布局已查看，但该次角色尚未载入，不称为完整窄窗动态验收。
- 观察结论：18 px 占位下眼神辨识很弱；24/32 px 更容易保留角色感。拆分后改用主体轻缩，避免大缺口像被咬掉一块。具体尺寸和节奏仍由 Rex 看预览选择。
- 未接麦克风、音频、模型或原生日常 App；没有新增页面入口、改动 R 标志或替换旧语音 POC。未制作 Spine 项目/骨骼/动画文件，也不以浏览器播放冒充原生动效验收。本轮没有需要重跑的 App/服务业务测试。
