# 吉祥物动画原生 POC

> 当前阶段：原生 POC 已实现并完成真实 Mac 交互冒烟；等待 Rex 视觉与动态节奏验收
> 交付契约：Native Prototype

## 1. 要回答的问题

在不购买 Rive 或 Spine 的前提下，Review Today 已接受的手绘吉祥物能否在真实 macOS 窗口中清楚、温柔且可打断地表达语音 Agent 状态？

本 POC 只回答角色动态与状态可读性，不证明正式语音、评分、复习流程或生产动画资产已经完成。

## 2. 实现边界

- 使用 GPT Image 生成并选择的透明分层位图；角色身份、颜色、刘海、呆毛、两颗豆豆眼和逗号身体沿用 V8 母图。
- SpriteKit 只驱动位图部件的位移、旋转、缩放、透明度与轻微呼吸形变，不使用 SVG、Bezier 或 Canvas 重画角色。
- 使用独立开发窗口和本地演示状态，不读取或修改 SwiftData，不接入麦克风、Realtime、评分或 FSRS。
- 所有语音输入均为模拟控制；音量滑杆只验证嘴型和身体响应映射。
- POC 通过不等于最终运行时锁定。后续仍可迁移到 Rive 或 Spine。

## 3. 状态与转换

```text
待机
  ├─ 开始语音 → 聆听
  └─ 开始复习 → 待机 + 显示复习卡

聆听
  ├─ Agent 回应 → 说话
  └─ 结束会话 → 待机

说话
  ├─ 音量变化 → 嘴型与轻微身体响应
  ├─ 用户打断 → 聆听
  └─ 回应完成 → 聆听
```

规则：

- 待机不戴耳机；进入语音会话后显示完整头梁和两个耳罩。
- 复习卡表达“带着内容帮用户重温”，耳机表达“已进入语音会话”，二者不是录音或隐私的唯一反馈。
- 打断必须以用户最后一次操作为准，不能等待当前表演结束。
- 标准动态采用轻微悬浮、前倾、回弹和呆毛反馈；不做大范围位移或夸张庆祝。
- Reduce Motion 下停止持续悬浮和弹性伸展，直接切换姿态与配件，并保留状态文字。

## 4. 原生 POC 控制

- 状态：待机／聆听／说话。
- 模拟音量：0–1 连续值。
- 配件：耳机、复习卡分别显示或隐藏。
- 打断：说话中立即切换到聆听。
- 模拟 Reduce Motion：用于在不修改系统设置时预览等价表达；真实系统设置仍由 SwiftUI 环境读取。

角色画面作为装饰性状态反馈，从辅助功能树隐藏；状态名称、说明、按钮和滑杆提供可读、可键盘操作的等价路径。

## 5. 2026-08-25 真实 Mac 验证

| 场景 | 当前结果 | 证据边界 |
|---|---|---|
| 待机 | 通过冒烟：无耳机、显示复习卡，角色完整落在默认窗口内 | `mascot-spritekit-poc-idle-v10.png` |
| 进入聆听 | 通过冒烟：完整头梁与两个耳罩出现，卡片隐藏，状态文字同步 | `mascot-spritekit-poc-listening-v10.png` |
| 说话 + 音量 | 通过冒烟：默认 56% 与 100% 音量可切换不同口型，身体响应继续运行 | `mascot-spritekit-poc-speaking-v10.png`；尚无代表速度录屏 |
| 说话中打断 | 通过冒烟：按钮与 Escape 都会立即从说话回到聆听，音量归零 | 原生辅助功能树与交互观察；尚无快速重复录屏 |
| Reduce Motion | 通过模拟开关冒烟：停止持续悬浮、呼吸和眨眼，保留状态、口型和配件表达 | `mascot-spritekit-poc-reduce-motion-v10.png`；尚未切换真实系统设置 |
| 深色背景 | 通过冒烟：透明分层在石墨底上可见，没有假棋盘格 | 原生深色预览；深色版本本身仍未完成品牌验收 |
| 窗口缩放 | 默认 920 × 680 窗口通过；顶部裁切已通过缩小角色并下移修正 | 最小窗口仍未单独验证 |
| 键盘路径 | Escape 打断通过；状态、配件和滑杆均出现在原生辅助功能树中 | 尚未完成纯键盘全路径录屏 |

Debug 签名构建已从 `设置 → 开发 → 打开吉祥物动画 POC` 进入真实窗口。该入口只在 Debug 构建中出现，不进入 Release 产品表面。

## 6. 分层位图来源

- 身份母图：`brand/raster/mascot-cutout-v8.png`。
- 耳机状态参考：`design-explorations/review-agent/mascot-voice-mode-study-v9.png`。
- 选用的真实 Alpha 部件表：`design-explorations/review-agent/mascot-rig-parts-sheet-v10.png`；工程副本位于 `Assets.xcassets/MascotRigParts.imageset`。
- 第一轮生成的构图可用，但把透明棋盘格画进 RGB，已拒绝；第二轮只修复背景为真实 Alpha，不允许改变部件。

主生成提示词：

```text
Using the accepted V8 mascot as the exact identity reference and V9 only as the lightweight complete-headphone reference, create one transparent 4 x 4 sprite-rig parts sheet. Keep the exact warm cream, graphite pencil contour, terracotta accents, bangs, single ahoge and two bean eyes. Row 1: head shell, compact comma torso, left rounded-nub arm, right rounded-nub arm. Row 2: open eye pair, blink eye pair, bangs, ahoge. Row 3: closed smile, small speaking mouth, medium speaking mouth, wide speaking mouth. Row 4: complete thin headband, left earcup, right earcup, two review cards. Every part must be isolated with generous transparent padding, no labels, no checkerboard, no shadows, no SVG or vector redraw, no new anatomy.
```

最终透明修复提示词：

```text
Edit only the background of this exact sprite-rig parts sheet: replace the baked checkerboard with real transparent alpha. Preserve every part, pixel-scale relationship, color, pencil texture, outline and position exactly. Add nothing and redraw nothing.
```

## 7. 通过后的决定

- 动作少、只服务 Apple 平台且维护可控：评估继续使用 SpriteKit。
- 需要设计师直接编辑状态机、跨平台或大量参数动画：评估 Rive Cadet。
- 需要专业角色动画师、复杂蒙皮和长期动作资产：评估 Spine Professional。

当前实现证明免费原生路径能够承载状态、口型、配件、打断与动态辅助功能；它尚未证明分层资产已经达到正式 Spine 制作质量。最终视觉节奏、耳机造型、身体拼接与角色是否“温柔、机灵、不幼态”必须由 Rex 在真实 POC 中验收。
