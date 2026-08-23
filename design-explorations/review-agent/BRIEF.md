# Review Today 品牌角色 Demo 简报

> 状态：第一轮静态视觉探索，等待 Rex 视觉选择
> 证据边界：两张概念板只验证母形、情绪与品牌同源关系；不证明小尺寸图标、矢量结构、Spine 拆件、动画节奏或原生界面已经完成。

## 已确认方向

- 角色是具备老师能力的女性 AI 搭档：贴心、随时回应、知道用户提供的内容、温柔提醒，纠正但不指责。
- 外形保持中性，女性人格通过女声、措辞、停顿和动作表达，不使用长发、睫毛、裙子或蝴蝶结。
- 静止母形借鉴稳定、略带手绘感的小人；动态语言借鉴“活着的声音线”，不复制任何参考角色的具体轮廓或五官。
- 大头、小型悬浮身体、无明确双腿、点状眼睛、固定两臂。
- 默认表情略微发呆但专注倾听，不长期挂标准微笑。
- 圆角“声音口”保留可爱记忆点；安静时像微张小嘴，说话时成为发光的声音窗口，不表现成牙齿。
- 吉祥物、App 图标和极简 Logo 来自同一个角色：完整身体 → 头部近景 → 头部线圈与声音口。
- 为未来 Spine 保持固定拓扑：头、身体、左臂、右臂、眼睛、声音口；不依赖任意增生或每帧重画。

## 本轮保留资产

- `mascot-concept-v1.png`：角色母形、倾听、思考、说话、温柔纠正与头部近景。
- `app-icon-logo-concept-v1.png`：浅色／深色 App 图标与小尺寸 Logo 简化关系。

第一轮生成的圆头五指版本因过于标准、儿童化与轻 3D 被放弃，没有纳入项目资产。

## 当前观察

- 成立：无腿悬浮、点眼、声音口、同源图标关系与固定拓扑已经可见。
- 仍需选择：当前连续线条母形是否足够有“她”的个性，还是需要增加更明显的不对称、手绘笨拙感或独有姿态。
- 后续不是直接描摹生成图。方向被接受后，需要重新构造矢量母版、16–1024 px 图标测试和 Spine 拆件图。

## 保留角色概念板提示词

```text
Use case: style-transfer
Asset type: second-iteration original Review Today voice-agent mascot character sheet for later Spine rig planning
Input images: Image 1 is the edit target and current first draft. Image 2 is reference only for the abstract idea of living luminous voice-line energy, never copy its character silhouette or facial geometry. Image 3 is reference only for quiet hand-drawn charm, slight awkwardness, dot eyes, and compact doodle proportions, never trace it.
Primary request: Redesign the exact concept in Image 1 to feel less generic, less babyish, less polished-3D, and more like a distinctive living voice line. Preserve the same character identity: large simple head, tiny dot eyes, small rounded-rectangle voice mouth, compact floating legless torso, two arms, attentive slightly absent-minded expression, gentle female AI personality expressed without female stereotypes.
Change only these design qualities: replace the perfect circular head with a gently asymmetrical hand-drawn loop; compress the body into a smaller soft taper connected naturally to the head; transform both arms into simple continuous luminous ribbon lines ending in tiny abstract rounded nubs or one soft mitten curve, with no fingers and no human hands; remove volumetric airbrushed shading and remove glossy 3D rendering; use mostly flat warm-paper negative space with one subtly imperfect teal luminous contour and an extremely faint translucent wash inside; make the mouth feel like a tiny quirky rounded voice tile rather than neon sci-fi hardware. Let one side of the head/torso contour subtly thicken and brighten like sound traveling through it. Keep anatomy fixed and riggable.
Composition: refined character exploration sheet on warm off-white. One large hero default listening pose; four smaller exact-same-character states: idle/listening, thinking with one internal traveling light, speaking with a subtle mouth pulse, gently correcting with slight head tilt and one open ribbon arm; one clean head close-up suitable for an App icon crop. No labels or text.
Style/medium: premium minimalist 2D line character, tactile pencil-like imperfection controlled into a vector-friendly contour, restrained editorial macOS brand feel, more graphic than illustrative, no photorealism, no 3D
Color palette: warm off-white, restrained deep teal outline, pale cyan-white voice glow, charcoal eyes; limited palette
Mood: quietly cute, intelligent, patient, a little odd in a memorable way, adult companion rather than toddler
Invariants: exactly two eyes, one rounded voice mouth, one head, one small legless body, exactly two simple arms in every full-body pose; same proportions across all poses; no arbitrary topology changes; no text; no watermark
Avoid: perfect circle head, snowman, generic corporate mascot, Baymax-like form, baby, plush toy, ghost, animal, blob monster, fingers, human hands, shoulders, legs, feet, hair, eyelashes, skirt, bow, cap, whistle, books, glasses, classroom objects, bevels, gradients, strong shadows, glossy highlights, realistic materials, permanent smile, Pixar or Soul character replication, Jerry-like exact single-line silhouette, chaotic morphing.
```

## 保留 App 图标／Logo 概念板提示词

```text
Use case: logo-brand
Asset type: Review Today App icon and logo exploration sheet derived from the approved mascot direction
Input image: Image 1 is the exact character identity source. Preserve its gently asymmetrical hand-drawn head loop, two tiny charcoal dot eyes, small rounded-rectangle voice mouth, restrained teal living-line contour, quiet attentive expression, and warm off-white interior. Do not invent a different mascot.
Primary request: Show a coherent same-origin brand system where the mascot becomes a macOS App icon and then a minimal logo. Create one presentation board with: one large polished macOS App icon concept using a close crop of the character head; one smaller light-appearance icon; one smaller dark-appearance icon; three very small monochrome logo-mark tests distilled from the same head loop plus voice mouth, suitable for menu bar, favicon, and watermark. No wordmark and no text labels.
App icon composition: a clean rounded-square macOS icon container with generous safe area. The character head fills the central area but never touches the outer edge. Preserve both dot eyes and the rounded voice mouth at readable sizes. The icon should feel calm and premium, not like a children's game. Light version uses warm paper-white surface with deep teal line; dark version uses deep charcoal-teal surface with a pale cyan-white line and mouth glow. Keep the same geometry across appearances.
Logo simplification: reduce to a slightly asymmetrical single head loop with a small rounded voice aperture; one test may retain the two dot eyes, while the two smallest tests should explore whether the voice aperture alone can carry recognition. Use true flat one-color marks, no text.
Style/medium: crisp vector-friendly 2D brand exploration, subtly hand-drawn but controlled, quiet editorial macOS polish, restrained and memorable, no photorealism and no 3D mascot rendering
Color palette: warm off-white, deep charcoal, restrained teal, pale cyan-white; no rainbow colors
Constraints: exact same recognizable character DNA in every icon and mark; no legs, body, arms, hands, hair, eyelashes, skirt, bow, cap, whistle, books, glasses, microphone pictogram, brain, graduation cap, checkmark, calendar, flame, letter R, text, watermark. No gradients in the monochrome marks. App icon may use only an extremely subtle material depth in the rounded-square container, while the character itself remains flat.
Avoid: generic chat bubble logo, generic microphone logo, smiling face app icon, emoji, baby app, game icon, glossy 3D, overly cute kawaii styling, perfect circle, Pixar or Soul replication, complex decorative background, tiny unreadable details.
```

## 生成方式

本轮使用 Codex 内置 `imagegen` 生成；工具没有暴露具体模型标识，因此不把本轮资产标记为已确认由某个指定模型生成。
