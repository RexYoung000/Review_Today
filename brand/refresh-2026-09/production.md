# 图标接入与吉祥物重新设计

## 当前默认：黑白 Logo，原有 UI（2026-09-07）

Rex 已授权直接采用确认版黑色底座／银白 R。默认导出入口改为 `brand/package_confirmed_assets.py`，从保存的 `ReviewToday-Confirmed-BlackWhite.icon` 原生导出 7 个 AppIcon 尺寸；应用内 `BrandDefaultLogo` 使用同版原色图标，菜单栏保留单色 R 模板。绿色原版、两套黑白材质及玻璃探索历史均归档保留。

标题与运行摘要使用中性色；框体、选中和焦点反馈沿用品牌青绿浅深变体，吉祥物保持原有素材和动效。日常共享视图已撤下玻璃界面挂接，保持既有布局、实底与交互；不再按下方历史计划接入玻璃 UI，除非 Rex 另行明确要求。

验证：签名 Debug 构建及 `codesign --verify --deep --strict` 通过；7 尺寸原生导出与来源摘要见 `brand/exports/default-logo-validation.json`。既有焦点／选中分离检查及预览配色／禁止发送契约通过。实际签名构建使用内存 fixture 查看了浅深起始页、会话页、侧栏展开／收起与 Logo，检查原有会话菜单开合及 Escape 恢复输入焦点；Finder 大图预览已看到新黑白图标。Dock 专项检查遇到 CUA 获取 Dock 超时，未宣称通过；macOS 27 尚未验证。没有访问日常数据库、发送模型请求或执行发布。

查看构建：`output/default-brand-build/Build/Products/Debug/Review_Today.app`。本次实看的运行窗口标记「界面预览（不可发送）」；正常启动该构建才进入日常运行。下方“仅小样、待接入”是历史记录，以本节当前状态为准。

2026-09-06。Rex 已明确要求替换已选 A，并据此重新设计吉祥物。

2026-09-07 补充：Rex 已授权先制作「中性浅深玻璃底＋青绿 R」的 Icon Composer 小样，保留本页已接入资产作为日常版本。小样查看并确认后才进行正式替换。新材质与原生界面试作见 [玻璃小样记录](glass-preview/README.md)，本页下方的平面配色约束继续适用于现有日常资产，不限制已授权的独立玻璃小样。

同日材质修订：Rex 确认图标内部改为带柔和渐变的哑光金属 R，外部玻璃包壳的边缘厚度和转角高光更明显；颜色仍为中性底＋青绿 R，原始轮廓不变。v2 先作为独立小样制作和查看，不代表正式资产已替换。

同日清晰度修复：针对 v2 深色底座发灰、发糊，v3 将整面玻璃收敛为中央透明的窄玻璃边缘，取消外壳叠加阴影；R 的渐变、缎面覆层与轮廓保持。最新工程和原生前后对照见 [玻璃小样记录](glass-preview/README.md)，仍等待小样视觉确认。

## 接入规则

2026-09-07 原版保留与黑白补充：Rex 再次提供的原版截图已逐字节归档，现有透明 R 母版、已采用参考板和当前高清 App 图标也单独备份。新增无青绿的原版质感、玻璃质感两套可编辑 Icon Composer 工程；原版质感按附图重建高清材质，不把 92 px 截图放大冒充母版。两工程已完成打开、保存和重开，详细导出与验收见 [黑白版本记录](monochrome-preview/README.md)。绿色版本保留，正式接入仍待视觉确认。

吉祥物更新：Rex 已选择「换一种吉祥物造型」，首轮 `mascot-returning-page-v1.png` 不采用。最新改为参考 Grok Bot 的几何轮廓与眼神，设计独立的「回望伙伴」，不直接把 R 字母立体化；已选图标的接入继续，不受吉祥物选择影响。

- 默认 App 图标采用选定板右下的深青绿底、暖白 R；保持原始 A 的内收斜切，不采用 A2/A3。侧栏展开/收起与 Agent 品牌标题采用相同 R 标志，单色适配浅深主题。
- 新母版通过内置 ImageGen 从已选图提取，保持形状。工程只打包、缩放和应用一次 macOS 外轮廓，不沿用 V8 人物裁切。旧 V8 母版与 POC 保留，默认导出入口改为新品牌，避免重新运行脚本还原旧图标。
- 吉祥物改为深青色的独立几何角色，轮廓圆润并保留局部斜切，以克制眼神表达注意、回想与完成；V2 直立切角被否定后，V3 已改为横向卵石轮廓。首轮回页方案已否定，未进入 App。新造型未选定前不替换整套 POC 的表情和语音素材，不启动动画工程。
- 本轮不改变产品配色规则、数据、模型、学习流程或正式发布。日常开发构建保持既有签名和数据库；只做与资产替换对应的构建和原生显示检查。

## 原始提示词（内置 ImageGen）

首轮 Logo 输出把棋盘格画入 RGB，`hasAlpha: no`，不能作为透明母版。继续以同形内容执行下列透明修订：

Remove ONLY the fake gray/white checkerboard background from this R logo, including the open counter and diagonal cut. Return the same logo with TRUE TRANSPARENT ALPHA, NOT a picture of transparency. Preserve the exact glyph silhouette, proportions, placement and flat dark fill. Keep all antialiased edges intact. One square PNG, no new text, no shadows, no border, no grid, no background color. Every checkerboard square must disappear into zero alpha. Do not draw checkerboard, do not make background white or black. Actual transparency is required for use as an app template image. Do not redesign the R.

### 透明 Logo 母版

Use case: logo-brand / identity-preserve asset extraction.
Use the attached ACCEPTED logo sheet as strict identity reference. Extract and reproduce ONLY its LARGE GRAPHITE R SYMBOL from the UPPER LEFT, as one production raster master. The user explicitly selected this original version, NOT a plain R, NOT an arrow version, NOT a flat left terminal version. Preserve EXACT silhouette, proportions, curved shoulder, distinctive inward angled terminal, open counter and diagonal gap, lower-right leg, tiny corner softness. Do not redesign, regularize or "improve" any of these. Front view, no tilt, no perspective.
Output one 1024x1024 PNG with genuinely transparent alpha background, no checkerboard printed into RGB. The R has solid uniform graphite #272B2A fill. Center the mark optically and geometrically, occupying approximately 80% of the square width and 82% height. Keep all outer contours inside canvas. ONLY ONE R symbol, no square app-icon background, no wordmark, no option labels, no miniatures. Crisp clean antialiasing, absolutely no texture, color mottling, shading, gradient, stroke outlines, shadow, glow, reflection or lighting. Background fully transparent including counter and diagonal gap. This is transparent master extraction of an approved logo, not a new design.

### App 图标母版

Use case: logo-brand / identity-preserve production app-icon master.
The attached ACCEPTED sheet is the strict visual reference. Reproduce ONLY the BOTTOM RIGHT app icon design as one 1024x1024 production square image. Preserve the exact original R silhouette: curved upper bowl, inward angled terminal, diagonal negative cut, right diagonal leg, not an arrow and not a flat horizontal inward terminal. The user chose THIS version. The R must match the sheet, not a similar font R.
Output: a flat, OPAQUE SQUARE filled edge-to-edge with deep teal #246C63, WITHOUT rounded corners (macOS export packaging will apply the outer shape once). Place the original R centered in warm white #F7F6F2, occupying 58% of the canvas width and 58% height, with ample equally balanced padding like the accepted reference. The R is front-facing, no perspective, no rotation. All corners of canvas solid teal.
Uniform solid colors. No mottling, paper texture, noise, gradients, shadows, glow, bevel, gloss, lighting or 3D. NO text, wordmark, labels, multiple icons, border, or presentation board. Deliver only the single square teal master with the approved white symbol.

### 吉祥物方案

Use case: logo-brand / stylized-concept.
Create one mature, quietly expressive mascot concept for Review Today, an adult personal learning coach that helps understanding, connecting previous knowledge, and active recall. The supplied approved logo sheet is a shape-and-palette reference ONLY: preserve its R logo if showing the logo, but design a NEW independent mascot in the same family.
Character direction: a "returning page companion". One graceful upright broad strip of matte paper bends around a softly squared upper shoulder and curls inward, with a clean diagonal folded lower tail, distantly echoing the open R silhouette and its diagonal incision. A tangible, economical little folded-paper companion rather than a literal alphabet letter with a face stuck on. No separate head or torso; one continuous abstract page-body. The open internal curve is an important distinctive negative space. Warm white front face, deep teal #246C63 reverse visible along the inside return and diagonal lower fold; a small graphite underside. Controlled subtle material depth, softly rounded paper edges, NOT glossy clay or inflated toy. Flat broad surfaces and elegant disciplined contours.
Exactly two tiny calm graphite short dash eyes integrated into a SMALL facing plane at the inner return, no eyebrows, no mouth, no blush, no baby cheeks. Eyes should read as attentive, neutral, adult. A gentle lean gives presence without posing like a child. No arms, hands, feet, hair, ears, antenna, headphones, cape, graduation cap, whistle, scarf, book prop, cards, badges or decorative logo attached. Avoid ghost, robot, animal, letter toy, smiling marshmallow, cartoon toddler. No anthropomorphic big round head. No shiny plastic or plush fur. The subtle eyes are the only facial features.
Make a carefully art-directed identity concept plate on an OPAQUE near-white #F7F6F2 1536x1024 landscape canvas. LEFT 65%: one large 3/4-front view of this mascot, comfortably framed with full silhouette and negative space visible, softly lit with minimal soft grounding shadow. RIGHT 35%: smaller nearly front-facing view of THE EXACT SAME mascot above, and a small original approved deep-teal R app icon with exact text "Review Today" below, for family resemblance. Same character geometry and palette in both views. Tiny top-left label "REVIEW TODAY / COMPANION". No other text or alternative characters. Adult editorial craft, quiet confidence, low detail, immediately memorable silhouette. This is a new mascot proposal, NOT an image of the previous round human mascot.

## Grok Bot 参考范围

参考 [官方设计说明](https://x.ai/news/designing-grok-bot#who-is-this)，已查看官方静止状态角色：白色圆形、两枚倾斜黑色短眼。借鉴简单轮廓与眼神承担性格/状态的方式；新角色采用品牌深青色、不对称轮廓与斜切，保持独立身份。本次只制作静态提案，不据此引入常驻动画、多 Bot 或其他产品机制。

### 回望伙伴提示词（内置 ImageGen）

Use case: logo-brand / stylized-concept. Design a new mascot identity concept board for Review Today, a calm adult personal learning and active-recall companion. User likes Grok Bot's simple flat geometric avatars with just expressive eyes; use that economy and maturity as inspiration, not its exact circular silhouette. Attached approved R logo sheet is a palette and edge-language reference only.
Create ONE distinctive character called the "Recall companion": a compact upright asymmetrical rounded pebble/soft lozenge body, deep teal #246C63, approximately 1.12 times taller than wide. The top and left shoulder have a calm generous rounded curve. A small clean diagonal bevel at the lower right gives it a proprietary silhouette, subtly related to the R logo's diagonal incision. No holes, no R-letter body, no folded paper, no arms, feet or accessories. It is a very simple lively flat abstract being. Face: two small warm-white horizontal almond/capsule eye shapes, slightly turned together toward the upper left, with tiny teal pupils giving a composed attentive sideways glance. No mouth, nose, eyebrows or cheeks. Eyes occupy only a small part of the face, not enormous baby eyes. A slight asymmetric lean creates the idea of looking back/recollecting. Personality: quietly intelligent, curious, steady adult companion, not toy or baby. Flat two-color vector-like raster, immaculate clean silhouette, no texture, no outlines, no glow, no 3D, no gradients, no shadows.
Landscape 1536x1024 board on warm off-white #F7F6F2. Spacious editorial arrangement. One large hero character at left, occupying ~45% of board width. At right three smaller renderings of the SAME character in a vertical sequence: calm attentive forward gaze; recollecting upward sideways gaze with slightly narrowed eyes; a subtle content expression with short curved closed eyes. Body silhouette remains identical in every view. Include very small grayscale reduction at bottom right showing the same character's legibility. Header top left exact "REVIEW TODAY / COMPANION". No other text, no R logo repeated, no mock devices. Cohesive restrained premium identity sheet. This is a truly new independent creature based on simple shape + expressive eyes, not a robot, not a ghost, not a marshmallow.

### 轮廓修订

Rex 否定 V2 的直立切角轮廓，要求换一种。V3 改为横向卵石轮廓，去掉平底、直立侧边和明显切角，保留克制眼神与品牌深青色；仍为静态提案。

Use case: logo-brand / stylized-concept. Create a new silhouette revision of the Review Today companion. Reference 1 is the latest mascot board: preserve its restrained eye language and deep teal color, but the user REJECTED the upright tall slab/rounded rectangle silhouette. Change the silhouette radically. Reference 2 is the brand palette only.
NEW SILHOUETTE: a low, horizontally oriented, broad organic river pebble / smooth bean, width-to-height ratio 1.35:1. It is nearly round but gently asymmetrical, with a smooth domed back and a subtly tucked convex underside, slightly tilted to its left. Fully curved continuous contour, NO flat bottom, NO vertical straight sides, NO corner chamfer, NO page shape, NO tail, NO leaf, NO crescent, NO arms or legs. Think a quiet minimal abstract living stone, with buoyancy and soft poise. It should immediately read as one simple organic being with almost no detail, as economical as Grok Bot's geometric avatars but an independent silhouette. Mature and composed, not babyish.
Deep teal #246C63 body, two small off-white capsule eyes with tiny teal pupils, concentrated close together in the upper-middle area. Eyes look attentively slightly to the left. No mouth, eyebrows, blush, ears, accessories, clothing, hair, props, logo badges. Eye area small and understated, not huge cartoon eyes. The entire personality comes from gaze and a slight lean. Flat solid clean vector-like raster aesthetic with no outlines, shading, 3D, grain or gradients.
One cohesive concept board in 1536x1024 landscape, warm off-white #F7F6F2 background. Large hero at left, clear generous negative space. Three smaller instances of exactly this SAME broad pebble silhouette at right in vertical arrangement: attentive neutral gaze, thinking upward glance, calm pleased closed eyes. Keep every body visibly wider than tall. Tiny header top left: "REVIEW TODAY / COMPANION". No other text, no extra symbols, no UI mockups, no comparison against old shape. NOT a tall body, not a speech bubble, not a slab, not paper. The major requested change is the silhouette.

## 实施结果与验证（2026-09-06）

- **原始 A 已接入**：`AppIcon.appiconset` 七种 16–1024 px PNG；`BrandRecallMark` 用于展开/收起侧栏和 Agent 起始页；`BrandMenuMark` 用于菜单栏。文字仍是原生字标，模板图片按当前 RunwayPalette 的 ink 适配浅深主题。角色场景与品牌身份分开。
- 唯一轮廓来源为 `masters/mark-alpha.png`。工程裁去透明留白、保留抗锯齿，以 Alpha 统一石墨/暖白色；图标使用深青 `#246C63`。同一透明母版同时生成图标与模板，避免两次模型生成造成轮廓差异。明确标记 sRGB，外轮廓只打包一次；默认导出不再使用 V8 裁切。
- 首轮假棋盘格母版保存在 `iterations/production/mark-checkerboard-rejected.png`；独立图标生成稿保存在 `iterations/production/icon-independent-unused.png`，均不进入导出。V1 回页和 V2 直立切角吉祥物已否定，`mascot-recall-companion-v3.png` 是最新横向卵石静态提案，尚未采用或接入。提示词见上方；全部使用内置 ImageGen。
- **资产检查通过**：实际导出 16/32/64/128/256/512/1024 px 尺寸、四角零 Alpha、经 CoreGraphics sRGB 解码的深青色值均符合；两套模板 1x/2x 尺寸与透明背景符合。已人工查看 [实际像素验收板](../exports/brand-acceptance-board.png)，包括 16 px 图标与 16/24/32/48/64 px 单色标志。检查中发现 `NSBitmapImageRep.colorAt` 会返回 Generic RGB 表示，验证已改用显式 sRGB 解码，未将错误转换结果当成颜色通过证据。
- **签名构建通过**：Debug `xcodebuild`，使用既有 Apple Development、团队 `7NDKLL3UJK` 与 `Rex.Review-Today`；`codesign --verify --deep --strict` 通过。没有改为 ad-hoc，也没有更改签名配置。构建仍有既有 NSSpeechSynthesizer 弃用提示和无 AppIntents 依赖的元数据提示。
- **原生检查通过**：正常退出/重启原日常 DerivedData 构建，Today 仍显示 8 张知识卡和 4 个学习任务；真实 Agent 起始页的标题与展开侧栏为新 R，浅深主题反白正常；收起后图标清晰，点击 R 恢复原侧栏。新品牌图标不加入动画，也不重复朗读装饰图片，按钮保留「Review Today，展开侧栏」可访问名称。恢复浅色与展开侧栏，保留真实库/历史，未发送模型消息。
- **尚未验证/采用**：Dock/Finder 和菜单栏最终显示、其他显示缩放与 VoiceOver 实际朗读仍待体验检查；Dock 的 CUA 读取超时，没有伪称系统外观已验证。吉祥物新轮廓仍由 Rex 选择，旧语音 POC 不混入提案。此次为视觉资源接入，不重跑与资产无关的服务/学习契约全套测试，不代表 M1 整体验收或正式发布。

验收入口：打开日常 Review Today → Agent，看顶部组合与侧栏；切换浅深主题并收起/展开侧栏；Dock/Finder 查看青绿底白 R。吉祥物先看本目录 V3 提案，尚未替换角色场景。
