# 吉祥物 Spine V1 制作计划

> 当前阶段：V13.1 拆件关系已由 Rex 接受；开始制作透明生产层，尚未制作正式 Spine 工程、骨骼、网格或运行时集成
> 第一目标：用一套不改变角色身份的骨骼，完成语音 Agent 最核心的状态表达

下一项实际制作物不是动作，而是“Rig-ready 分层母版 + 静止重组对比图”。只有默认姿态能无缝还原已接受角色，才开始绑定骨骼与制作 `idle_loop`。

## 1. 为什么先做语音核心 Rig

V10 已证明让生成模型独立重画头、身体和手臂会改变角色拓扑。Spine V1 的第一风险不是动作数量，而是拆件后能否在默认姿态无缝还原已接受母图。因此第一阶段只做待机、聆听、说话、打断和句末反馈；看书、抱卡／递卡和卡片柜整理放入第二动作包。

## 2. Rig-ready 母版门槛

正式建骨骼前，必须从同一张被接受完整母图制作分层源文件，并补齐被遮挡区域；不得分别生成互不一致的头、身体和手臂。为避免再次出现头身或手臂断裂，V1 不把头、身体和胸前静置双臂导出为独立纹理，而是保留一张连续的 `core_body_with_resting_arms_mesh`，在同一网格内用头部、身体和手臂局部骨骼做低幅权重变形。

建议图层与遮挡顺序：

```text
root
├─ headset_band_back
├─ core_body_with_resting_arms_mesh
├─ eye_left / eye_right / blink
├─ mouth_closed / small / medium / wide / finish_smile
├─ bangs
├─ ahoge
├─ earcup_left / earcup_right
├─ card_back / card_front
└─ optional_echo_line
```

默认姿态把全部图层归位后，必须与已接受完整角色逐像素叠加检查：头身比例、连续 S／逗号轮廓、两颗眼睛、刘海、呆毛、双臂连接和耳机位置不能漂移。未通过该门槛，不进入动画。

V13 第一张候选把双臂拆成独立豆形部件，视觉上失去原角色的向内收拢弧线并存在悬空风险，已停止沿用。Rex 已接受 `design-explorations/review-agent/mascot-spine-rig-decomposition-v13-1-candidate.png` 的拆件关系：胸前静置双臂合并回连续核心身体，只拆耳机、五官、刘海、呆毛和五档嘴型。当前开始逐层制作透明生产资产，尚未通过静止像素重组验收。

第一张透明生产层为 `design-explorations/review-agent/spine-v1-layers/core-body-with-resting-arms-v13-1.png`。它直接裁取 V13.1 验收板的中央核心身体并执行确定性连通背景提取，没有再次生成或重画角色；尺寸为 520 × 800 px，不透明边界为 415 × 697 px、位于 `(38, 61)`，四角 Alpha 为 0。Rex 已允许沿用该核心层，当前继续制作耳机三层；全部图层仍需完成静止重组验收。

耳机透明源层已从同一 V13.1 母板机械提取：`headset-band-back-v13-1.png`、`headset-earcup-screen-left-v13-1.png` 和 `headset-earcup-screen-right-v13-1.png`。三张均通过真实 Alpha 与透明角检查。由于验收板右侧采用拆件展示比例，它们尚未获得相对于 520 × 800 核心层的最终装配缩放与坐标；完成耳机静止重组前不能称为可直接导入 Spine 的最终附件。

`design-explorations/review-agent/spine-v1-headset-recomposition-v13-1.png` 是耳机静止重组基线：头梁按 1.45 倍置于核心身体后方，两个耳罩按 1.30 倍置于头部前方。输出保持 520 × 800 px、四角透明，内容边界为 508 × 710 px @ `(3, 48)`。Rex 认为当前视觉重量可以沿用。

眼睛、眨眼、刘海和呆毛透明源层也已从同一 V13.1 母板机械提取。`spine-v1-face-open-recomposition-v13-1.png` 与 `spine-v1-face-blink-recomposition-v13-1.png` 是完整脸部静止重组候选：两张均为 520 × 800 px、四角透明，内容边界为 508 × 747 px @ `(3, 11)`；当前复用 V12.1 闭口嘴型作为位置占位。候选已通过脚本复现和 Alpha 检查，但尚未经过 Rex 的最终视觉确认，也不代表五档嘴型已经迁移完成。

## 3. 第一套骨骼

- `root`：只负责整体位置与缩放。
- `body`、`head`：共同影响同一张 `core_body_with_resting_arms_mesh`，允许极低幅呼吸、前倾和回弹；不存在可被拉开露缝的独立头部纹理。
- `arm_left_zone`、`arm_right_zone`：只影响同一核心网格里的局部手臂区域，第一阶段仅做极小幅收放，不产生独立边缘。递卡、看书等大动作改用第二动作包的专用遮挡纹理。
- `eye_left`、`eye_right`：独立眨眼槽，不用缩放整张脸模拟眨眼。
- `mouth`：五槽切换，由语音包络驱动，不做自由拉伸变形。
- `bangs`、`ahoge`：只承担很小的延迟与回弹。
- `headset`：头梁位于头后，耳罩位于头前；待机隐藏，语音会话显示。

第一阶段不做大幅网格扭曲、夸张 squash-and-stretch、物理头发、手指、腿或任意新增部件。

## 4. Spine V1 动作包

| 动作 | 产品意义 | 验收重点 |
|---|---|---|
| `idle_loop` | 安静待机、未监听 | 轻微呼吸与悬浮，不持续微笑或大幅摆动 |
| `session_enter` | 用户进入语音会话 | 耳机状态清楚；Reduce Motion 直接切换 |
| `listening_loop` | 正在听用户 | 轻微前倾、闭口、自然眨眼，不机械点头 |
| `speaking_loop` | Agent 正在回应 | 四档嘴型跟随真实语音，身体只作低幅次级响应 |
| `interrupt_to_listen` | 用户打断 Agent | 立即闭嘴并回到聆听，最终状态服从用户操作 |
| `finish_smile` | 一句话结束 | 无板牙温柔月牙笑短暂出现后回到聆听 |
| `reduced_motion` | 系统减少动态效果 | 保留状态、嘴型和文字，停止持续位移与弹性 |

## 5. 第二动作包（V1 通过后）

- `hold_cards_idle`：抱着今日复习卡待机。
- `offer_card`：向用户递卡，表达邀请复习。
- `read_book`：自己安静看书，不抢占用户任务。
- `organize_card_drawer`：在卡片柜中归档资料，表达文档整理。

第二动作包会引入手臂遮挡、卡片前后层、书页和柜体道具，只有语音核心 Rig 证明角色身份稳定后才进入。

## 6. 交付与证据门槛

1. 分层母版和静止重组对比图通过 Rex 视觉确认。
2. Spine 工程能在编辑器中播放全部 V1 动作，快速切换无跳帧、部件分离或轮廓突变。
3. 导出到隔离的 macOS 播放器，使用真实 TTS 驱动嘴型，并保留可打断与 Reduce Motion。
4. 保存一段代表速度录屏：待机 → 进入会话 → 聆听 → 说话 → 停顿 → 句末 → 打断 → Reduce Motion。
5. 完成以上证据后，再决定替换现有 SpriteKit POC 或继续保留原生位图方案。
