# Review Today 品牌资产 V8

## 2026-09-06：更简洁、成熟的 Logo 与图标探索

Rex 认为当前设计过于幼态，要求重新设计更简洁、更独特、贴合产品的 logo 与图标。完成 A/B 与 A2/A3 比较后，Rex 附图并明确「还是这个吧」，最终选回原始 A；[用户选定图](refresh-2026-09/accepted-a-reference.png) 锁定紧凑 R、内部斜切及暖白/石墨/青绿的视觉关系，折返保留为含蓄寓意。详见 [选择与生成记录](refresh-2026-09/README.md)。生产母版与实际小尺寸仍待制作验证，App 内尚未替换 V8。下方 V8 与 OneWorks 记录保留原有适用范围。

## 当前 OneWorks 探索（不替换 V8）

用户已要求直接操作 https://oneworks.cloud/avatar/ 制作「抽象学习伙伴」，不是仅提供提示词。两版为纸页伙伴（柔和片状/层叠）及记忆伙伴（紧凑圆润不对称），奶白/石墨与青绿协调色，静态近景，无动物/机器人/毕业帽及符号堆叠。

文档独立推送后已实际制作两版，见 [作品与制作记录](oneworks/README.md)。网页复制 SVG 已核对，实际矢量几何已保存；网页 PNG/工程下载未取得文件，交付 PNG 来自矢量渲染，不称为原生 PNG 母版、不用截图放大。包含可复现参数、大图与16/32/64/128px及浅深检查。Rex选定并原生验收前不改AppIcon；V8及动态POC保留。下文模型位图-only规则仅适用于V8，不限制用户已批准的OneWorks新路线。

> 当前阶段：V8.3 App 图标人物取景已由 Rex 锁定；V8.4 透明吉祥物与透明单色标志已完成工程收口，等待 Rex 视觉验收。真实 Dock／Finder 仍需最终体验验收。

## 正式母图

- `raster/mascot-master-v8.png`：完整闭口抱卡吉祥物，统一暖白产品底。
- `raster/app-icon-master-v8.png`：陶土色 App 图标模型母图。
- `raster/mark-master-v8.png`：暖白底单色石墨标志母图。
- `raster/mascot-cutout-v8.png`：从已接受吉祥物母图确定性移除暖白画布后的真实 Alpha 版本。
- `raster/mark-cutout-v8.png`：ImageGen 从单色标志母图提取的真实 Alpha 石墨标志。
- `exports/brand-acceptance-board.png`：三项母图与实际 AppIcon 尺寸的集中验收板。
- `exports/mascot-cutout-1024.png`、`exports/mark-cutout-512.png`：可直接用于产品排版的透明导出。
- `exports/transparent-assets-acceptance-board.png`：暖白、陶土和深色叠底边缘验收板。
- `references/accepted-color-reference-v8.png`：Rex 提供的已接受草图颜色参考。
- `references/accepted-app-icon-crop-v8.png`：Rex 提供的 App 图标人物显示范围参考。
- `palette-sampled.json`：从颜色参考干净区域直接取得的 sRGB 色值。

## 生产原则

- 角色内容、线条、表情、卡片和材质均由生成模型产出，不使用 SVG 或代码重新描画。
- 工程脚本只负责按已取样色值校正现有像素、裁切、缩放、macOS 圆角蒙版和 PNG 打包，不描线、不补画也不修改角色内容。
- AppIcon 的 16–1024 px 版本均从选定的 `app-icon-master-v8.png` 导出。
- 产品正式名称尚未确认，本包不包含 Wordmark。
- V8.3 暖白底母图继续作为安全回退。V8.4 两项透明资产均已确认包含真实 Alpha；深色叠底只用于暴露边缘残色，不等于已经完成深色品牌版本。

## 重新打包

在项目根目录执行：

```shell
./brand/export_brand_assets.sh
```

该命令不会生成或重画角色，只会从已选定的模型母图重新导出工程资源和验收板。

如需从相同母图重做透明吉祥物，可执行：

```shell
swift brand/extract_alpha_cutout.swift brand/raster/mascot-master-v8.png brand/raster/mascot-cutout-v8.png 18 12
```

该步骤只移除与画布相连的暖白背景，并对 12 px 外沿做底色去污染；角色内部像素、构图和五官不重画。可选第 5 个参数使用 `largest`（默认，仅保留最大连通前景）或 `all`（保留所有非背景拆件）；第 6 个参数使用 `auto`（默认，暖色边缘保留陶土色）或 `graphite`（边缘统一按石墨去污染）。

如需从模型原始输出重做 V8.2 取样校色，可执行：

```shell
swift brand/apply_sampled_palette.swift mascot INPUT.png OUTPUT.png
swift brand/apply_sampled_palette.swift icon INPUT.png OUTPUT.png
swift brand/apply_sampled_palette.swift mark INPUT.png OUTPUT.png
```

校色器使用 `palette-sampled.json` 中记录的参考关系：产品底 `#FEF9F2`、头部 `#FFF7E8`、下半身 `#FCEFD6`、卡片 `#FEF8ED`、图标陶土底 `#E58E6D`、石墨 `#3B3A38`、卡片强调 `#E97C4D`。

## 验收要求

1. 对照三张母图检查是否仍是同一个角色，尤其是眼距、刘海、呆毛、闭口微笑、双臂和两张知识卡。
2. 检查 1024、128、64、32 和 16 px 的卡片语义与表情是否仍然可辨认。
3. 在 Dock、Finder、启动台和应用切换器检查图标裁切：角色轮廓约占图标宽度的 72%，呆毛接近上沿，身体和卡片在下沿自然裁掉；不要缩成完整立绘。
4. 检查 `transparent-assets-acceptance-board.png`：暖白与陶土底应保持原手绘质感且无假棋盘格；深色底仅用于放大检查浅色角色边缘，不作为正式使用面。石墨标志当前只定义用于浅色与暖色表面。
5. 视觉通过前，不把当前模型输出称为最终品牌定稿或 Spine 可用拆件。
