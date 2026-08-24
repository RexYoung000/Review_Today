# Review Today 品牌角色 Demo 简报

> 状态：`mascot-bangs-ahoge-study-v4.png` 已被 Rex 接受为当前角色母形方向；`mascot-card-expression-study-v7.png` 左侧已被接受为当前静态品牌构图与默认表情方向
> 证据边界：概念板只验证母形、情绪与品牌关系；不证明小尺寸图标、矢量结构、Spine 拆件、动画节奏或原生界面已经完成。

## V8 正式品牌资产（模型生成版，待视觉验收）

- Rex 已否决把 V7 角色重新描成 SVG 的生产路径。V8 改为以 V4 锁定角色身份、以 V7 左侧锁定闭口微笑与抱卡构图，由 GPT Image 生成工作流产出正式位图内容；人工只负责选图和工程打包，不重新绘制角色。
- `brand/raster/mascot-master-v8.png` 是统一暖白底的完整吉祥物母图；`brand/raster/app-icon-master-v8.png` 是陶土色 App 图标母图；`brand/raster/mark-master-v8.png` 是单色标志母图。三者均由模型分别生成，并以同一角色身份约束。
- V8 首轮模型母图的角色偏黄，App 图标底偏高饱和橙红且带中心晕染，与 V7 左侧草图不一致；修正版以该草图为唯一颜色参考，改为近纸白淡奶油角色、略亮暖白卡片、柔和石墨线和低饱和陶土粉橙实底，单色标志则使用中性暖灰白底。
- 代码只能对 App 图标母图进行裁切、缩放、圆角 Alpha 蒙版和 PNG 导出，不能补画五官、手臂、卡片、刘海或呆毛，也不能用 SVG 重新解释模型线条。
- 内置生成工具两次把透明棋盘格画进 RGB 文件，因此当前完整吉祥物明确使用暖白产品底，不把假透明当作正式透明 cutout。透明角色资源需要后续单独提取并以 `hasAlpha: yes` 验证。
- App 图标母图已导出为 16–1024 px 工程资源，`brand/exports/brand-acceptance-board.png` 已检查 128、64、32 与 16 px，并通过 macOS Debug 构建；真实 Dock／Finder 视觉仍待 Rex 验收。
- 产品正式名称尚未确认，本轮不制作 Wordmark。最终角色质感、陶土底、App 图标裁切与小尺寸表现仍需 Rex 检查母图和真实 Dock／Finder 后才能接受；生成成功或构建通过本身不构成体验验收。

## V7 表情与知识卡优化（左侧已接受）

- Rex 认为 V6 的不对称方牙笑近似坏笑，与抱卡邀请复习的动作不协调；V7 固定使用抱着两张复习卡的品牌动作，只比较闭口温柔微笑、居中开口微笑和居中两颗小板牙三种表达。
- 卡片缩小并下移，双臂轻托而不是紧抓；前卡使用一个短陶土色标题条和两三条长短不一的石墨内容线，后卡轻微错位。所有信息均为语言无关的内容骨架，不放真实英文、产品 Logo、问题、答案、问号或对勾。
- 完整吉祥物可使用极浅的哑光纸纹和轻微纤维感帮助卡片区别于普通色块；App 图标与单色 Logo 只保留标题条／内容线的平面结构，不使用厚阴影、折角、高光或拟真纸张。
- Rex 已选择 V7 左侧闭口温柔微笑与抱卡构图作为当前方向；该选择确定静态品牌表达基准，但不会直接证明最终 App 图标、矢量 Logo、16–1024 px 表现、角色标准表情或 Spine 嘴型已经完成。
- `mascot-card-expression-study-v7.png`：左、中、右分别为闭口温柔微笑、居中开口无牙与居中两颗小板牙；每组包含完整角色、App 图标和单色小 Logo。
- 已接受结论：卡片的标题条、内容线与极浅纸纹在不使用真实文字时建立知识资料语义；左侧闭口微笑用于当前静态品牌与默认 App 图标方向。右侧两颗居中板牙保留为角色说话或鼓励状态候选；中间开口无牙更像正在发声或轻微惊讶，不用于静态 Logo。

### V7 表情与知识卡优化提示词

```text
Use case: logo-brand
Asset type: V7 expression and knowledge-card refinement board for the Review Today mascot and app icon
Input images: Image 1 is the exact accepted V4 mascot identity, proportions, bangs, ahoge, eyes, floating S/comma torso, arms, and lively graphite line reference. Image 2 supplies only the left holding-two-cards composition, warm cream/graphite/terracotta palette, and app-icon extraction relationship. Correct Image 2's sly asymmetric square-tooth smile and blank oversized cards.
Primary request: create one landscape comparison board with exactly three columns. Every column uses the exact same gentle front-facing, slightly tilted mascot pose and the exact same two knowledge-review cards; only the mouth differs. Each column contains one large full mascot, one rounded-square macOS app-icon crop, and one small one-color graphite logo-mark extraction.
Shared cards: reduce and lower the cards so the mouth, arms and curled torso remain visible. The front card has one short terracotta title bar and two or three short graphite content strokes; the second card is subtly offset behind with one terracotta edge. Use language-neutral content lines, never readable text.
Left expression: one small centered shallow closed smile, symmetrical, relaxed and kind, with no teeth.
Center expression: one tiny centered rounded open smile with soft dark interior and no teeth; no surprise, laugh or shout.
Right expression: one tiny centered soft open smile with exactly two equal small upper front teeth, symmetrical and gentle, never rabbit-like, babyish or mischievous.
Material: extremely subtle matte paper tooth and fine fiber grain only on large full-mascot cards; app icons and logo marks simplify cards to flat cream with strong content strokes. No thick shadow, folded corner, gloss, bevel, depth, crumple or photorealism.
Style and palette: controlled 2D brand-development art, lively graphite contour, pale butter-cream mascot, muted terracotta card accents and app-icon field, quiet warm-ivory canvas, warm editorial macOS polish, no gradients, glow or 3D.
Constraints: preserve V4's asymmetric healthy head, short side-swept bangs, one comma ahoge, exactly two eyes, compact S/comma torso, exactly two rounded-nub arms and no legs. Exactly two cards per mascot and icon. No headphones. Keep all geometry identical across columns except the mouth.
Avoid: asymmetric smirk, crooked or single tooth, fang, open laugh, eyebrows, blush, missing eye, fingers, crossed arms, whistle, microphone, headphones, real text, logo on card, playing-card symbols, study clichés, heavy paper effects, long hair, baby, rabbit, generic smiley, existing character, watermark.
```

## V6 复习语义构图（待验证）

- Rex 已确认品牌核心动作采用“复习老师带着复习卡来找用户”，下一轮比较抱卡正视、递卡邀请与翻卡提问三种产品表达。
- 空手抱臂不作为主方向，因为容易显得封闭、审视或严格；吹哨与胸前常驻哨子不进入常驻吉祥物、App 图标和 Logo，因为它们更像体育教练、裁判与催促，也会削弱温柔对话和知识复习语义。
- 两张轻微错位的空白圆角卡表达问题与回忆，不在卡片上使用问号、对勾、文字、书本、奖章或学科符号。复习卡承担“来做什么”，角色承担“她是谁”，耳机及会话反馈承担“如何语音互动”。
- V6 关系板需要在相同 V4 角色、V5 暖色假设和相同画面尺度下，为三种构图分别给出完整角色、App 图标裁切和小尺寸单色 Logo 提炼；构图比较通过前均不视为最终品牌动作或 Logo。
- `mascot-review-card-logo-study-v6.png`：左、中、右依次比较抱卡正视、递卡邀请与翻卡提问，每组包含完整角色、App 图标和单色小 Logo。
- 当前结论：左侧抱卡构图最像带着今日内容来找用户的复习老师，并保留了温柔陪伴关系；该构图已在 V7 左侧优化后被 Rex 接受。中间递卡容易像递票或交付资料；右侧翻卡能表达问题／回忆的两面，但也可能像卡牌产品，均不作为当前静态品牌方向。

### V6 复习语义构图提示词

```text
Use case: logo-brand
Asset type: three-direction Review Today mascot, app-icon, and minimal-logo composition board focused on the meaning of REVIEW
Input images: Image 1 is the exact accepted V4 character identity, anatomy, personality, bangs, ahoge, facial placement, and lively graphite line reference. Image 2 is only the accepted working color-and-finish reference: pale warm butter-cream mascot, graphite-charcoal contours and face, muted earthy terracotta-coral accents, warm ivory background. Do not copy Image 2's old empty-handed app-icon composition.
Primary request: Create one clean landscape brand exploration board with THREE clearly separated vertical columns, showing three genuinely different ways the exact same mascot can communicate 'a caring review teacher bringing today's material to you.' Each column must contain one large full mascot pose at the top, one small rounded-square macOS app-icon crop derived from that exact pose in the middle, and one very small one-color logo-mark extraction at the bottom. No text labels.
LEFT direction: the mascot faces the user with a slight playful head tilt and gently cradles two blank rounded rectangular review cards against the upper torso; the second card is visibly offset behind the first. Both rounded nub arms wrap around the card edges in an open, caring way, not crossed arms.
CENTER direction: the mascot leans slightly forward and warmly offers one blank rounded review card toward the viewer with one rounded arm supporting it from below; the other rounded arm stays near the torso. The pose reads 'here is today's question' rather than sales, serving, or giving a gift.
RIGHT direction: the mascot holds two blank rounded cards at chest height, with the front card tilted halfway aside so the second card is revealed behind it, suggesting question then recall. One rounded nub arm rests against the tilted card edge.
App-icon extraction: a restrained terracotta-coral rounded-square field; each close crop retains the ahoge, asymmetrical head, two eyes, square-tooth mouth, both arms, and enough blank card geometry to preserve the review action. No headphones, microphone, sound waves, words, question marks, checkmarks, books, caps, trophies, clocks, or chat bubbles.
Minimal-logo extraction: one-color graphite mark simplified from the same ahoge, asymmetrical head, arms, and one unmistakable rounded card corner or offset card edge; never reduce it to a plain circular face, document, playing card, chat bubble, or generic flashcard logo.
Style and palette: controlled 2D brand exploration with lively graphite contour and restrained flat colored-pencil fills; pale warm butter-cream mascot clearly separated from warm ivory background; graphite face and outline; cream cards with one terracotta-coral edge or offset back card; quiet editorial macOS polish; no gradients, glow, gloss, or 3D.
Constraints: preserve the exact V4 softly irregular head, compact S/comma floating torso, exactly two rounded-nub arms without fingers, two visible bean eyes, one uneven square tooth, two or three short side-swept bang strokes, one off-center comma ahoge, and no legs. Cards are the only new object. No headphones anywhere.
Avoid: missing or extra eyes, crossed arms, stern teacher, scolding, whistle, lanyard, microphone, headphones, sound-wave symbol, text or study clichés, human hands, legs, long hair, generic smiley, generic chat/document/card logo, recognizable existing character, watermark.
```

## V5 配色关系板（待验证）

- 目的不是为角色套用通用“AI 色”，而是先确认角色自身的固有配色，再从同一角色提炼 App 图标、极简 Logo 与后续产品强调色。
- 第一组假设采用奶油黄角色、石墨轮廓与五官、陶土珊瑚耳机和图标底色；语义来自温暖纸面、铅笔与陪伴式复习，不使用蓝绿色、科技蓝紫、霓虹、渐变或发光材质。
- 关系板必须同时展示无耳机待机角色、佩戴正常双耳耳机的语音角色、同源 App 图标与极简 Logo，不能借换色改变 V4 的头身比例、刘海、呆毛、两颗豆豆眼、方牙或固定拓扑。
- 本组颜色尚未被 Rex 接受；色值、明暗模式、产品语义色和矢量规范必须在关系板通过后再定义。
- `mascot-logo-color-study-v5.png`：第一张奶油黄、石墨与陶土珊瑚关系稿，包含待机角色、语音耳机状态、App 图标和三枚小 Logo。
- 当前观察：陶土珊瑚用于耳机与 App 图标时能强化温暖、俏皮的角色气质；奶油色身体与暖白底的明度距离偏小，小尺寸纯色 Logo 也弱化了刘海识别点。两项都需 Rex 先判断整体气质，再决定是否进入针对性修正。

### V5 配色关系板提示词

```text
Use case: logo-brand
Asset type: first color relationship board for the Review Today mascot, app icon, and minimal logo
Input image: Image 1 is the exact accepted V4 mascot identity and anatomy reference. Preserve the same softly irregular large head, compact curled S/comma floating torso, exactly two tiny rounded arms ending in blunt nubs, exactly two bean-dot eyes in all front and three-quarter views, one small uneven square tooth, two or three short side-swept bang strokes, exactly one tiny off-center comma-shaped ahoge, and the normal lightweight two-ear headphones only in the voice state.
Primary request: Create one clean landscape brand color study that tests whether this exact mascot naturally belongs to a warm cream, graphite, and muted terracotta-coral palette. This is a color test, not a redesign. Show four coherent same-origin elements: (1) one large three-quarter full-body idle mascot without headphones, (2) one medium voice-session mascot wearing a complete thin headband and two small earcups, (3) one polished rounded-square macOS app icon derived from the same recognizable head and upper-body crop, and (4) three very small minimal logo-mark tests distilled from the exact same asymmetrical head, ahoge, eyes, and square-tooth expression, including at least one one-color graphite mark.
Color palette: mascot body filled with very light warm butter-cream, never bright yellow; lively graphite-charcoal contour, eyes, mouth, bangs, and ahoge; headphones in muted earthy terracotta-coral with cream inner pads and graphite structure; app icon uses a restrained terracotta-coral field with the cream mascot and graphite face; minimal marks use graphite or terracotta only. Background is quiet warm ivory paper.
Style/medium: controlled 2D brand exploration combining the accepted lively hand-drawn graphite line with restrained flat colored-pencil fills; warm editorial macOS polish; vector-friendly shapes but retain slight human irregularity; playful and mascot-like, not childish.
Composition: generous white space; large idle mascot on the left, active headphone state near center, app icon and three small logo marks on the right; no words, no labels, no arrows, no UI screens, no device mockups.
Mood: caring review teacher, quietly goofy at rest, attentive and clever in conversation, warm, safe, gently feminine, companionable rather than technological.
Constraints: change only the color treatment and brand extraction; preserve the exact V4 character identity, healthy head silhouette, proportions, facial spacing, bangs, ahoge, square tooth, S/comma torso, and no-leg floating anatomy. The idle mascot has no headphones at all. The active mascot has one complete thin headband and exactly two visible small earcups. Every visible front or three-quarter character and icon face has exactly two eyes. Arms have no fingers. Flat color only, no gradient, no glow, no glossy material, no 3D, no realistic fur or fabric.
Avoid: teal, blue-green, blue, purple, generic AI colors, neon, gradients, aura, light trails, translucent glass, saturated primary yellow, candy colors, peach skin tone, human skin, pink femininity stereotype, generic chat bubble, microphone logo, book logo, checkmark logo, generic smiley icon, perfect-circle head, missing eye, extra eye, one-eyed mascot, human ears, earring, antenna, multiple ahoge strands, full hairstyle, long hair, eyebrows, eyelashes, bow, hat, microphone boom, gaming headset, fingers, hands, legs, feet, baby, plush toy, bean character, snowman, ghost, animal, recognizable existing character, text, watermark.
```

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
- 第二轮只验证单色动画草图中的轮廓、表情与动作张力。方向被接受后，再通过生成模型制作正式位图母图与 16–1024 px 图标测试；Spine 拆件图仍需单独制作。

## 第二轮性格与动作方向稿

- `mascot-character-study-v2.png`：单色动画开发草图，验证方牙回归表情、S／逗号形头身重心、压缩与弹起，以及“平时呆萌、回应时机灵”。
- 当前成立：主姿态比第一轮更俏皮、更像角色；嘴不再像硬件；思考、理解、纠正和鼓励可以通过全身动作区分。
- 尚未解决：部分小稿出现手指，部分笑脸略偏儿童动画，各姿态的固定比例还不够严格。这张图只能作为性格与动作方向稿，不能直接作为 Spine 模型表。

## 回声线示范与结论

- `echo-line-motion-demo-v2.png`：左侧为补齐两眼的基础形象，中间为静止错位轮廓，右侧为说话时轮廓弹开的示意。
- Rex 确认回声线更像动作表现，不是角色自带特征。
- 当前有效结论：回声线只在说话、思考或理解时短暂出现；静止母形不得依赖回声线建立辨识度。
- `mascot-character-study-v2.png` 左侧主立绘少一只眼属于生成错误。正面与三分之二侧面必须保留两颗豆豆眼，只有完整侧面允许隐藏一只。

## 耳机方向

- 帽子只增加角色感但语音语义弱；口哨会带来体育教练、裁判和催促心智，不继续。
- 单侧 C 形耳扣与半环耳机方案未通过：静态示范更像耳朵、耳环或天线，不能清楚识别成耳机。
- 当前方向改为正常、轻量的双耳头戴耳机：完整纤细头梁、左右两个小耳罩，不加麦克风杆或游戏化装饰。
- 待机时完全不显示耳机；用户明确发起语音会话后直接戴上，聆听、思考和回应期间保持佩戴，会话结束或取消后消失。
- 耳机不是录音或隐私的唯一反馈；原生界面仍需明确文字、权限状态和录音控制。Reduce Motion 直接切换待机与佩戴状态。

## 刘海与小呆毛

- 固定头部特征采用两三笔短偏分刘海与一根偏离中心的逗号形小呆毛，轻微表达女性气质并补足圆头顶部留白。
- 刘海不覆盖豆豆眼，不发展成完整长发；呆毛不做长卷、弹簧或天线造型。
- 正常双耳耳机的头梁从刘海和呆毛后方经过，佩戴时仍应看见固定发型特征。
- 呆毛只做轻微状态反馈：待机微弯、进入会话稍立、思考轻偏、回应小幅回弹；Reduce Motion 下保持固定。

### 刘海与小呆毛角色稿

- `mascot-bangs-ahoge-study-v4.png`：保留既有头身、方牙和正常双耳耳机，只增加短偏分刘海、一根小呆毛及其轻微状态变化。
- Rex 已确认这版整体感觉与刘海／呆毛方向，可以作为下一阶段讨论与细化依据。
- 当前成立：顶部剪影不再空秃；刘海提供轻微女性气质；小呆毛在待机与会话状态中保持稳定辨识；耳机头梁仍清楚可见。
- 尚未解决：回应姿态仍出现了不符合固定拓扑的手指；最终模型表需要统一无手指的圆钝手臂，并验证刘海、呆毛与耳机头梁的前后遮挡。

### 刘海与小呆毛角色稿提示词

```text
Use case: stylized-concept
Asset type: updated animation character sheet for the original Review Today mascot, adding only subtle side-swept bangs and one tiny ahoge while preserving the accepted mascot and normal headphones
Input images: Image 1 is the accepted playful mascot personality and graphite sketch style. Image 2 is the accepted voice-session state logic and NORMAL lightweight two-ear headphones. Preserve the same compact S/comma torso, tiny arms, two bean-dot eyes, uneven single square tooth, and complete thin headphone headband with two small earcups. Correct all source defects: every front or three-quarter view must show exactly TWO visible bean-dot eyes, and arms must end in simple rounded nubs with no fingers.
Primary request: Add one restrained permanent hairstyle signature to the same mascot: TWO OR THREE short separate side-swept pencil bang strokes resting near the upper forehead, plus exactly ONE tiny comma-shaped ahoge emerging slightly off-center from the crown. The bangs and ahoge add a subtle feminine, playful identity while keeping the character abstract and gender-light.
Hair geometry: no solid hair mass and no filled hair cap. Bangs are only two or three clean curved graphite strokes, short enough not to cover the eyes. The single ahoge is a very small soft comma curve, clearly hair but not an antenna, spring, horn, flame, or question mark. It must remain attached to the crown and preserve the same placement in all poses. When headphones are worn, the complete thin headband passes BEHIND the bangs and ahoge, so both hair features remain visible and the headset still reads clearly.
Composition: one large hero three-quarter idle pose without headphones; beside it four smaller exact-same-character states: voice-session ready wearing normal two-ear headphones with ahoge slightly more upright, listening wearing headphones with attentive lean, thinking wearing headphones with ahoge gently leaning to one side, and responding wearing headphones with ahoge slightly rebounding plus one simple rounded-arm gesture. Add two clean head close-ups: idle without headphones and active with headphones. No labels, no text, no arrows, no UI, no app icon, no logo.
Style/medium: monochrome graphite animation character-development drawing on warm white paper; controlled lively pencil lines, varied pressure, subtle construction traces, professional mascot charm, not polished vector art and not 3D
Color palette: graphite black and soft gray only; no color, teal, glow, gradients, dark mode, or color variants
Mood: quietly goofy, attentive, warm, gently feminine, alert and clever when responding, playful but not childish or anime-like
Constraints: exact same identity, healthy head silhouette, proportions, two eyes, tooth, bangs and one ahoge in every pose; exactly one head, one compact torso, exactly two arms, no legs. Headphones appear only in the four active states and active close-up; whenever worn they have a full headband and two visible small earcups. Hair motion is extremely subtle and does not change topology.
Avoid: missing eye, one-eyed character, extra eyes, full hairstyle, long hair, bob haircut, blunt fringe, thick bangs, hair covering eyes, hair cap, wig, ponytail, pigtails, multiple ahoge strands, antenna, horn, sprout, flame, question mark, anime girl, eyelashes, eyebrows, bow, flower clip, human ears, earring, single-sided headset, C-shaped ear, microphone boom, gaming headset, fingers, human hands, hardware mouth, sad face, baby, plush toy, ghost, animal, Pixar or Soul replication, recognizable existing characters, text, watermark.
```

### 正常双耳耳机状态稿

- `headphones-session-storyboard-v3.png`：从左到右展示待机无耳机、会话准备、聆听／思考与回应状态，并提供无耳机／戴耳机头部近景。
- 当前成立：完整头梁与两个小耳罩可以被立即识别为耳机；待机和语音会话状态关系清楚，不再像耳朵、耳环或天线。
- 尚未解决：最后一格出现了不符合固定拓扑的手指；耳罩、头梁与角色头部的最终比例尚未通过小尺寸或 Spine 验证。

### 正常双耳耳机状态稿提示词

```text
Use case: stylized-concept
Asset type: corrected four-state voice-session accessory storyboard for the original Review Today mascot
Input image: Image 1 is the exact mascot personality and anatomy reference: warm graphite animation sketch, softly irregular large head, compact curled S/comma torso, two tiny arms, two bean-dot eyes, one cute uneven square tooth. Correct the source defect: every front and three-quarter view must show exactly TWO visible bean-dot eyes.
Primary request: Show the exact same mascot in four equally sized states from left to right, using a clearly recognizable NORMAL lightweight pair of over-ear headphones only during the voice session. Do not invent any storage mechanism or one-sided C-shaped device.
Headphone design shared by panels 2–4: one complete thin headband visibly arches over the top of the head and connects to TWO small matching round earcups, one on each side. The earcups are modest, soft, and simple. No microphone boom, no antenna, no gaming shapes, no cat ears, no light strips, no ear-like C shapes. The headset must be unmistakably a pair of headphones at first glance.
Panel 1 — idle: no headphones or headphone parts anywhere. Mascot rests in the quietly goofy tucked-arm pose, awake and attentive, two visible eyes, small square-tooth mouth.
Panel 2 — voice conversation ready: same mascot now wearing the complete lightweight headphones. She perks up slightly as if ready to talk. Both earcups and the full top headband are clearly visible.
Panel 3 — listening/thinking: same complete headphones remain. Character leans forward gently, eyes focused, mouth small and neutral, arms tucked. No sound waves.
Panel 4 — responding: same complete headphones remain. Character opens the little hand-drawn tooth mouth naturally and makes one simple rounded-arm welcoming gesture. Add only one very short soft pencil echo stroke behind the outer head contour as a temporary speaking effect.
Composition: clean horizontal four-state animation-development board on warm white paper, generous spacing, no text, no labels, no arrows, no borders, no UI, no app icon, no logo. Add two small matching head close-ups below: idle without headphones and active with complete headphones, useful only for comparing identity.
Style/medium: monochrome graphite animation preproduction drawing, controlled lively pencil line, varied pressure, subtle construction traces, professional mascot charm, no polished vector art or 3D
Color palette: graphite black and soft gray only; no teal, glow, gradients, dark mode, or color variants
Constraints: exact same character identity, healthy head silhouette, proportions and facial placement in all panels; exactly TWO visible eyes in every full-body and head close-up; exactly one head, one compact torso, two arms, no legs. Headphones appear only in panels 2–4 and active close-up. Both earcups and complete headband must be visible whenever headphones are worn.
Avoid: missing eye, one-eyed character, extra eyes, C-shaped ear, earring, earclip, single-sided headset, half headband, antenna, human ears, call-center headset, microphone boom, gaming headset, oversized DJ headphones, AirPods, hat, whistle, scarf, necklace, fingers, human hands, sad face, baby, plush toy, ghost, animal, Pixar or Soul replication, recognizable existing characters, text, watermark.
```

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
