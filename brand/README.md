# Review Today 品牌资产 V8

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

该步骤只移除与画布相连的暖白背景，并对 12 px 外沿做底色去污染；角色内部像素、构图和五官不重画。

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
