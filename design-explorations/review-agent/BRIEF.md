# Review Today 品牌角色 Demo 简报

> 状态：第一轮静态视觉探索未通过；第二轮重新验证单色角色母形
> 证据边界：概念板只验证母形、情绪与品牌关系；不证明小尺寸图标、矢量结构、Spine 拆件、动画节奏或原生界面已经完成。

## 已确认方向

- 角色是具备老师能力的女性 AI 搭档：贴心、随时回应、知道用户提供的内容、温柔提醒，纠正但不指责。
- 外形保持中性，女性人格通过女声、措辞、停顿和动作表达，不使用长发、睫毛、裙子或蝴蝶结。
- 静止母形借鉴稳定、略带手绘感的小人；动态语言借鉴“活着的声音线”，不复制任何参考角色的具体轮廓或五官。
- 大头、小型悬浮身体、无明确双腿、点状眼睛、固定两臂。
- 平时呆萌、回应时机灵；依靠歪头、前倾、收腹和弯曲形成俏皮动作，不长期挂标准微笑。
- 嘴恢复为不规则手绘表情，可偶尔像露出一颗方牙；不发光，也不承担语音硬件标识。
- 语音与 AI 感改由轮廓脉动、身体伸缩、重心变化和沿线游光表达。
- 吉祥物、App 图标和极简 Logo 来自同一个角色：完整身体 → 头部近景 → 头部线圈与声音口。
- 为未来 Spine 保持固定拓扑：头、身体、左臂、右臂、眼睛、声音口；不依赖任意增生或每帧重画。

## 第一轮资产与结论

- `mascot-concept-v1.png`：角色母形、倾听、思考、说话、温柔纠正与头部近景。
- `app-icon-logo-concept-v1.png`：浅色／深色 App 图标与小尺寸 Logo 简化关系。

以上两张保留为未通过探索的决策证据，不能继续作为实现参考。Rex 的视觉反馈是：发光胶囊嘴出戏；角色偏丧；机械换色难看；整体缺少参考草图的俏皮和吉祥物感。

更早生成的圆头五指版本因过于标准、儿童化与轻 3D 被放弃，没有纳入项目资产。

## 当前观察

- 可保留：无腿悬浮、点眼、中性外形与固定拓扑。
- 必须重做：正圆直立母形、发光胶囊嘴、被动垂手、机械深色反相和过早 Logo 提炼。
- 第二轮只验证单色动画草图中的轮廓、表情与动作张力。方向被接受后，才重新构造矢量母版、16–1024 px 图标测试和 Spine 拆件图。

## 第二轮性格与动作方向稿

- `mascot-character-study-v2.png`：单色动画开发草图，验证方牙回归表情、S／逗号形头身重心、压缩与弹起，以及“平时呆萌、回应时机灵”。
- 当前成立：主姿态比第一轮更俏皮、更像角色；嘴不再像硬件；思考、理解、纠正和鼓励可以通过全身动作区分。
- 尚未解决：部分小稿出现手指，部分笑脸略偏儿童动画，各姿态的固定比例还不够严格。这张图只能作为性格与动作方向稿，不能直接作为 Spine 模型表。

## 回声线示范与结论

- `echo-line-motion-demo-v2.png`：左侧为补齐两眼的基础形象，中间为静止错位轮廓，右侧为说话时轮廓弹开的示意。
- Rex 确认回声线更像动作表现，不是角色自带特征。
- 当前有效结论：回声线只在说话、思考或理解时短暂出现；静止母形不得依赖回声线建立辨识度。
- `mascot-character-study-v2.png` 左侧主立绘少一只眼属于生成错误。正面与三分之二侧面必须保留两颗豆豆眼，只有完整侧面允许隐藏一只。

### 回声线示范提示词

```text
Use case: stylized-concept
Asset type: a simple three-panel visual explanation of an optional 'echo contour line' signature for the existing Review Today mascot
Input image: use Image 1 only as the identity reference for the mascot: graphite animation sketch, irregular large head, tiny curled S/comma torso, two small arms tucked near the belly, tiny bean-dot eyes, one cute uneven square-tooth mouth, warm white paper. Preserve the same personality and proportions. Correct the source generation defect: every front or three-quarter view must have exactly TWO visible bean-dot eyes. Never omit an eye.
Primary request: Draw the exact same mascot in the exact same gentle three-quarter listening pose three times from left to right, at equal size, so the only meaningful difference is the echo contour line concept.
Left figure: baseline character with one normal graphite outline and no echo line.
Center figure: resting echo-line version. Add one deliberate, clean secondary graphite arc slightly outside the character's back-left head contour, offset by a small consistent gap. It starts near the upper-left crown, follows only about one third of the head curve, and fades before the neck. It should read as a delayed pencil echo, not hair, halo, shadow, duplicate character, or messy construction line.
Right figure: speaking echo-line version. Preserve the same secondary arc, but let it separate into two short gently expanding graphite arcs behind the back-left head contour, plus one tiny motion beat near the upper torso, suggesting that the voice traveled through the outline. The mascot itself subtly perks up and opens the hand-drawn tooth mouth, but the mouth does not glow.
Composition: clean horizontal three-panel comparison on warm white animation paper, generous spacing, no text, no labels, no arrows, no borders, no app icon, no logo. Each figure remains fully visible and similarly sized.
Style/medium: monochrome graphite animation development drawing, lively controlled pencil line, a little roughness and varied pressure, no polished vector treatment
Color palette: graphite black and soft gray only; no color, glow, gradient, or dark-mode version
Constraints: exactly one mascot per panel; same character identity and fixed topology in all three; exactly two visible eyes per figure; exactly one head, one tiny torso, two arms, no legs; echo line only on the center and right figures. The echo arc must be visibly separate from the main body contour and easy to understand at a glance.
Avoid: missing eye, one-eyed character, extra eyes, hair, antenna, eyebrow, ear, halo, aura, sound-wave icon, Wi-Fi symbol, multiple full outlines, double exposure, shadow silhouette, ghosting, neon effect, hardware mouth, fingers, human hands, sad expression, generic corporate mascot, Pixar or Soul replication, text, watermark.
```

### 第二轮提示词

```text
Use case: stylized-concept
Asset type: second-round animation preproduction pencil model sheet for an original Review Today voice-agent mascot, intended to validate personality and later inform a fixed Spine rig
Primary request: Design one original mascot character who feels like a caring review teacher and always-available voice AI companion. The emotional formula is: quietly goofy at rest, suddenly alert and clever when responding, playful but never noisy or childish. The character gently corrects mistakes without blame.
Input image: use only as high-level reference for lively animation-sketch energy, pose compression and expansion, imperfect pencil line weight, asymmetrical facial acting, and mascot charm. Do not trace or copy any existing silhouette, face, pose, costume, or character from the reference.
Subject: a tiny floating gender-neutral line character with exactly one large softly irregular head, one very small curved torso, no legs or feet, exactly two short simple arms, two tiny dot eyes, and a small hand-drawn mouth. Head and torso are slightly offset so the resting silhouette has a gentle S-curve or curled-comma rhythm, not a straight snowman. The head is not a perfect circle. The torso feels compact and tucked, not dangling. One eye may sit subtly higher than the other. The mouth is an uneven short pencil shape, sometimes reading like one cute square tooth, but never a glowing capsule, screen, device, or voice indicator.
Personality acting: the rest pose leans forward slightly with both little arms tucked near the belly, looking curious and awake rather than sad. When the character understands, the head lifts and the whole S-curve springs open. Thinking curls the body inward with one arm near the chin. Speaking uses natural tiny mouth changes while the outline and posture carry the rhythm. Gentle correction uses a slight head tilt and one relaxed open arm. Encouragement uses one small buoyant bounce, not celebration.
Composition: one large hero three-quarter resting pose, plus six smaller drawings of the exact same character: listening, perk-up/understood, thinking, speaking, gently correcting, and encouraging. Add three small head-expression studies and one side-view construction sketch. Arrange freely like a professional animation animator's rough model sheet. No labels, no text, no UI, no icon, no logo.
Style/medium: monochrome graphite animation development drawing on warm white animation paper; loose exploratory pencil strokes, subtle construction lines, varied pressure, a few deliberate redraw marks and faint smudges; readable silhouette and professional character design underneath the roughness. Mostly contour drawing, minimal soft graphite fill only where needed for expression. Not polished vector art.
Color palette: graphite black and soft gray only on warm white paper; absolutely no teal, cyan, colored glow, gradients, dark-mode version, or color variants
Rig constraint: despite elastic poses, preserve the same fixed parts and recognizable proportions: head, torso, left arm, right arm, two eyes, mouth. No extra limbs or topology changes.
Mood: warm, mischievously intelligent, attentive, safe, slightly odd and memorable; an adult companion with mascot charm
Avoid: sad, depressed, sleepy, drooping, vacant, timid, permanently surprised, permanent smile, generic corporate mascot, perfect circular head, symmetrical front-facing stiffness, straight vertical body, snowman, ghost, sperm or tadpole silhouette, animal, human woman, baby, plush toy, glossy 3D, polished vector, hardware mouth, neon mouth, microphone, headphones, hair, eyelashes, skirt, bow, cap, whistle, books, glasses, classroom props, logo presentation, app icon mockup, Pixar or Soul character replication, any recognizable existing character.
```

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
