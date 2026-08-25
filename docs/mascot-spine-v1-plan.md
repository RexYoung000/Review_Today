# 吉祥物 Spine V1 制作计划

> 当前阶段：motion direction aligned；尚未制作正式 Spine 工程、骨骼、网格或运行时集成
> 第一目标：用一套不改变角色身份的骨骼，完成语音 Agent 最核心的状态表达

下一项实际制作物不是动作，而是“Rig-ready 分层母版 + 静止重组对比图”。只有默认姿态能无缝还原已接受角色，才开始绑定骨骼与制作 `idle_loop`。

## 1. 为什么先做语音核心 Rig

V10 已证明让生成模型独立重画头、身体和手臂会改变角色拓扑。Spine V1 的第一风险不是动作数量，而是拆件后能否在默认姿态无缝还原已接受母图。因此第一阶段只做待机、聆听、说话、打断和句末反馈；看书、抱卡／递卡和卡片柜整理放入第二动作包。

## 2. Rig-ready 母版门槛

正式建骨骼前，必须从同一张被接受完整母图制作分层源文件，并补齐被遮挡区域；不得分别生成互不一致的头、身体和手臂。

建议图层与遮挡顺序：

```text
root
├─ headset_band_back
├─ body_mesh
├─ head_mesh
│  ├─ eye_left / eye_right / blink
│  ├─ mouth_closed / small / medium / wide / finish_smile
│  ├─ bangs
│  └─ ahoge
├─ arm_left / arm_right
├─ earcup_left / earcup_right
├─ card_back / card_front
└─ optional_echo_line
```

默认姿态把全部图层归位后，必须与已接受完整角色逐像素叠加检查：头身比例、连续 S／逗号轮廓、两颗眼睛、刘海、呆毛、双臂连接和耳机位置不能漂移。未通过该门槛，不进入动画。

## 3. 第一套骨骼

- `root`：只负责整体位置与缩放。
- `body`、`head`：允许极低幅呼吸、前倾和回弹；不把头从身体上拉开。
- `arm_left`、`arm_right`：保留圆钝手臂，不生成手指；第一阶段只做小幅收放。
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
