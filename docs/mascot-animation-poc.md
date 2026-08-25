# 吉祥物动画原生 POC

> 当前阶段：V11 只通过“角色不分离”验收；V12.1 无板牙嘴型已替换运行资源并通过构建与透明边距检查，等待代表速度录屏
> 交付契约：Native Prototype

## 1. 要回答的问题

在不购买 Rive 或 Spine 的前提下，Review Today 已接受的手绘吉祥物能否在真实 macOS 窗口中清楚、温柔且可打断地表达语音 Agent 状态？

本 POC 只回答角色动态与状态可读性，不证明正式语音、评分、复习流程或生产动画资产已经完成。

## 2. 实现边界

- 使用 GPT Image 生成并选择的完整透明角色状态图；每张图必须是连体角色，不在运行时拆分头、身体和手臂。V12 只允许在完整角色上叠加嘴型、闭眼和其他不改变身体拓扑的局部表情位图。
- SpriteKit 驱动完整角色位图与 GPT Image 生成的局部表情位图，不使用 SVG、Bezier 或 Canvas 重画角色。
- 使用独立开发窗口和本地演示状态，不读取或修改 SwiftData，不接入麦克风、Realtime、评分或 FSRS。
- V12 使用本机测试文案生成并播放真实 TTS 音频，读取播放音量驱动嘴型；它不代表正式 Agent 语音链路已接入。手动语音强度只作为调试回退。
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
  ├─ TTS 播放音量变化 → 闭口／小开口／中开口／大开口
  ├─ 自然节奏 → 眨眼、呆毛回弹、轻微重心响应
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
- 播放测试语音：生成并播放一段本机 TTS，实时显示音量并驱动嘴型。
- 手动语音强度：0–1 连续值，只作为无音频时的调试回退，同样驱动嘴型。
- 完整状态图说明：待机图固定抱卡且无耳机；聆听／说话图固定无卡片且佩戴双耳耳机，不再独立拼装配件。
- 打断：说话中立即切换到聆听。
- 模拟 Reduce Motion：用于在不修改系统设置时预览等价表达；真实系统设置仍由 SwiftUI 环境读取。

角色画面作为装饰性状态反馈，从辅助功能树隐藏；状态名称、说明、按钮和滑杆提供可读、可键盘操作的等价路径。

## 5. V10 真实 Mac 验证结论：视觉不通过

| 场景 | 当前结果 | 证据边界 |
|---|---|---|
| 待机 | 机制通过，视觉不通过：抱卡状态也已换成重新生成的圆头／葫芦身体 | `mascot-spritekit-poc-idle-v10.png` 只作失败证据 |
| 进入聆听 | 机制通过，视觉阻塞：头部领口与身体边线重叠，双臂悬空 | `mascot-spritekit-poc-listening-v10.png` 只作失败证据 |
| 说话 + 音量 | 机制通过，视觉阻塞：口型可切换，但角色轮廓已不再是 V8 母形 | `mascot-spritekit-poc-speaking-v10.png` 只作失败证据 |
| 说话中打断 | 通过冒烟：按钮与 Escape 都会立即从说话回到聆听，音量归零 | 原生辅助功能树与交互观察；尚无快速重复录屏 |
| Reduce Motion | 通过模拟开关冒烟：停止持续悬浮、呼吸和眨眼，保留状态、口型和配件表达 | `mascot-spritekit-poc-reduce-motion-v10.png`；尚未切换真实系统设置 |
| 深色背景 | 通过冒烟：透明分层在石墨底上可见，没有假棋盘格 | 原生深色预览；深色版本本身仍未完成品牌验收 |
| 窗口缩放 | 默认 920 × 680 窗口通过；顶部裁切已通过缩小角色并下移修正 | 最小窗口仍未单独验证 |
| 键盘路径 | Escape 打断通过；状态、配件和滑杆均出现在原生辅助功能树中 | 尚未完成纯键盘全路径录屏 |

Debug 签名构建已从 `设置 → 开发 → 打开吉祥物动画 POC` 进入真实窗口。该入口只在 Debug 构建中出现，不进入 Release 产品表面。上述验证只证明状态机和输入路径可运行；Rex 的真实截图验收已确认角色分离和形状改变，因此 V10 不能提升为体验通过。

## 6. V10 拆件失败来源

- 身份母图：`brand/raster/mascot-cutout-v8.png`。
- 耳机状态参考：`design-explorations/review-agent/mascot-voice-mode-study-v9.png`。
- 被拒绝的真实 Alpha 部件表：`design-explorations/review-agent/mascot-rig-parts-sheet-v10.png`；只保留为失败证据，不再作为运行资产。
- 第一轮生成的构图可用，但把透明棋盘格画进 RGB，已拒绝；第二轮只修复背景为真实 Alpha，不允许改变部件。

主生成提示词：

```text
Using the accepted V8 mascot as the exact identity reference and V9 only as the lightweight complete-headphone reference, create one transparent 4 x 4 sprite-rig parts sheet. Keep the exact warm cream, graphite pencil contour, terracotta accents, bangs, single ahoge and two bean eyes. Row 1: head shell, compact comma torso, left rounded-nub arm, right rounded-nub arm. Row 2: open eye pair, blink eye pair, bangs, ahoge. Row 3: closed smile, small speaking mouth, medium speaking mouth, wide speaking mouth. Row 4: complete thin headband, left earcup, right earcup, two review cards. Every part must be isolated with generous transparent padding, no labels, no checkerboard, no shadows, no SVG or vector redraw, no new anatomy.
```

最终透明修复提示词：

```text
Edit only the background of this exact sprite-rig parts sheet: replace the baked checkerboard with real transparent alpha. Preserve every part, pixel-scale relationship, color, pencil texture, outline and position exactly. Add nothing and redraw nothing.
```

失败原因不是 Alpha，而是生成模型把每个部件重新画了一遍：头、身体、手臂没有共同的连接与遮挡几何。透明修复只能修正包装，不能恢复角色拓扑。

## 7. V11 替换实现与真实 Mac 验证

- 待机直接使用已接受的 `brand/raster/mascot-cutout-v8.png`，工程资源名为 `MascotIdleFull`。
- `mascot-voice-listening-full-v11.png` 与 `mascot-voice-speaking-full-v11.png` 是完整、连体的真实 Alpha 角色图；两张均保持连续 S／逗号轮廓和贴合主体的双臂。
- SpriteKit 同一时间只切换完整待机、聆听或说话纹理；标准动态只对整张角色做轻微悬浮、倾斜和低幅伸缩，Reduce Motion 直接切换状态并停止持续形变。
- 原生控制不再提供独立耳机／卡片开关，避免再次制造不存在的组合资产；状态说明明确当前完整图包含的配件。

| 场景 | V11 当前结果 | 证据边界 |
|---|---|---|
| 待机 | 通过冒烟：直接显示 V8 抱卡母图，无重新生成轮廓 | `mascot-whole-state-poc-idle-v11.png` |
| 聆听 | 通过冒烟：头身连续、双臂贴合、无领口双线，完整双耳耳机可辨认 | `mascot-whole-state-poc-listening-v11.png` |
| 说话 | 通过冒烟：与聆听保持同一完整轮廓，只使用小幅开口表情 | `mascot-whole-state-poc-speaking-v11.png` |
| 100% 语音强度 | 通过冒烟：只产生低幅整体响应，没有拉开头身或手臂 | 原生运行观察；尚无代表速度录屏 |
| 说话中打断 | 通过冒烟：Escape 立即回到完整聆听图，语音强度归零 | 原生辅助功能树与运行观察 |
| Reduce Motion | 通过模拟开关冒烟：完整状态图直接切换并停止持续悬浮、倾斜与伸缩 | 尚未切换真实系统设置 |
| 深色背景 | 通过冒烟：两张 V11 图均为真实 Alpha，没有棋盘格；浅色轮廓边缘可见 | 深色版本本身仍未完成品牌验收 |

V11 已满足“角色不分离”的修正目标，但 Rex 的真实体验反馈确认说话状态仍像待机：嘴型不随语音变化、没有眨眼与独立次级动作。它不能提升为说话体验通过，也不能继续称为 Spine 效果。未来若进入专业 Spine 拆件，全部部件在默认姿态归位时仍必须重组为已经验收的完整角色。

## 8. V11 生成来源与最终提示词

- 身份与连接几何：`mascot-bangs-ahoge-study-v4.png` 左侧完整大角色。
- 正式颜色、表情与纸笔质感：`brand/raster/mascot-cutout-v8.png`。
- 双耳耳机只参考 `mascot-voice-mode-study-v9.png`，不采用其身体比例。
- 直接从 V8 移除卡片的首张候选再次变成雪人身体，已拒绝；最终改用 V4 完整身体锁定连接几何。
- 生成工具多次输出假棋盘格；被选中的聆听与说话状态都经过单独的 background-extraction 编辑，并通过 `validate_alpha.swift`。

最终聆听状态主提示词：

```text
Use Image 1's large full-body hero as the exact authority for the connected S/comma silhouette, asymmetrical lean, head-to-body proportion and attached rounded arms. Use Image 2 only for the accepted warm cream, graphite and terracotta finish, two eyes, closed smile, bangs and ahoge. Use Image 3 only for a normal lightweight complete two-ear headset. Render one complete connected listening mascot; preserve the continuous head-to-torso contour, attached arms and compact offset body. No cards, no collar, no horizontal seam, no snowman or separated pieces. Center the full character on genuine transparent alpha.
```

最终说话状态编辑提示词：

```text
Edit the selected complete listening mascot. Change only the centered closed smile into a very small gentle open speaking mouth with a restrained terracotta interior. Preserve the complete connected S/comma silhouette, attached arms, headset, bangs, ahoge, eyes, colors, scale and placement. Then replace only any baked checkerboard with genuine transparent alpha; no other character changes.
```

## 9. 通过后的决定

- 动作少、只服务 Apple 平台且维护可控：评估继续使用 SpriteKit。
- 需要设计师直接编辑状态机、跨平台或大量参数动画：评估 Rive Cadet。
- 需要专业角色动画师、复杂蒙皮和长期动作资产：评估 Spine Professional。

V10 证明“让模型独立生成拆件”不可用；V11 证明免费原生路径可以在不分离角色的前提下承载完整状态切换、打断和动态辅助功能。最终视觉节奏与动画运行时仍由 Rex 在真实 POC 中验收后决定。

## 10. V12 真实说话表现契约

V12 只验证“角色说话时是否真的活起来”，不扩展复习、纠正、鼓励、看书或整理卡片动作。

- 身体继续使用完整连体语音角色，不拆头、身体、手臂或耳机。
- GPT Image 生成一张无嘴完整语音母图，以及闭口、小开口、中开口、大开口和句末微笑局部位图；局部素材必须共享同一中心、比例、石墨线宽、奶油底色与陶土口腔色。闭口与句末微笑采用完整尖尾月牙，小开口采用近圆 O；每个张嘴轮廓必须完整封闭、上下均有自然弧度并保留透明安全边距，不得出现统一平顶、贴边或像被矩形裁断的横向切线。
- 真实 TTS 播放音量采用平滑后的包络驱动四档说话嘴型；静音与自然停顿必须回到闭口，不能随机持续张嘴。
- 更宽的温柔月牙笑不按音量触发，只用于一句话结束后的短暂亲和反馈；V12.1 不再使用板牙。
- 眨眼使用独立自然间隔，不与每个音节同步；身体、头部与呆毛只承担低幅次级节奏，不能代替嘴型。
- 用户打断必须立即停止 TTS、闭嘴并回到聆听；Reduce Motion 保留嘴型和状态变化，但停止持续悬浮、伸缩与次级摆动。

验收必须包含一段 10–15 秒代表速度的真实 Mac 录屏：连续说话、短停顿、句末反馈、播放中打断和 Reduce Motion。构建、静态截图或手动滑杆都不能单独证明 V12 体验通过。

## 11. V12 实施与当前证据

- 第一张嘴型表因小／中／大开口共享平直上沿而作废；它在连续切换时形成明显横向截断带，不是 SpriteKit 裁切问题。
- V12 第二稿仍被 Rex 指出闭口线端、小开口扁平度与方牙横线存在截断感。被接受的 V12.1 `design-explorations/review-agent/mascot-mouth-sheet-v12-1.png` 改用完整尖尾月牙、近圆小 O、完整中／大 O 和无板牙句末月牙笑。
- `brand/split_mouth_sheet.swift` 只负责移除生成图的连通纸色背景、切分和统一透明画布；它不重画嘴型。五张运行资源均为 126 × 92 px，并通过透明角与内容边界检查。最宽嘴型的不透明边界为 106 × 72 px、位于 `(10, 10)`，四周均保留安全边距，不再贴边截断。
- `design-explorations/review-agent/mascot-mouth-animation-preview-v12-1.png` 是 V12.1 统一定位后的五状态静态检查板；替换后的原生代表速度证据仍待补录。
- 本机 TTS 检查结果为 13.92 秒，四档采样均被实际触发：闭口 191、小开口 135、中开口 853、大开口 21；V12.1 运行资源替换后的 Debug 构建通过。
- 当前可以称为“V12.1 静态嘴型与运行资源通过”，但仍缺一段覆盖连续说话、停顿、句末温柔微笑、播放中打断和 Reduce Motion 的 10–15 秒原生录屏，因此尚不能宣布 V12.1 动态体验通过或正式 Spine 资产完成。

最终嘴型表生成提示词摘要：以已接受角色预览锁定细铅笔线、微小面部比例与陶土口腔色，以被拒绝嘴型表只锁定五状态顺序和中心；依次生成完整尖尾月牙闭口、近圆小 O、完整中 O、完整大 O 和更宽的无板牙句末月牙笑。所有嘴型都不得暴露硬切端点、使用平顶、D 形、扁胶囊、牙齿横线、裁切边或共享水平线；背景保持单一暖白，后续只做机械去底和切分。
