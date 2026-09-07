# 原版保留与黑白图标

**当前状态更新：** Rex 已进一步授权将确认版黑白 Logo 设为默认。图标与应用内品牌入口已接入，UI 玻璃不采用；下方试作期门槛保留为历史。当前验证与运行入口见 [品牌接入记录](../production.md)。

2026-09-07，Rex 授权保留所附绿色原版，并制作无点睛色的原版质感与玻璃质感各一份。Rex 随后以附图确认玻璃版本，并在工程中删除底座内侧玻璃边缘图层；已保存 [确认图](user-confirmed-appearance.png) 与 [确认工程快照](ReviewToday-Confirmed-BlackWhite.icon)。确认限于这份图标外观。当前为独立可编辑小样，不替换日常 App，不提交或推送待确认的正式接入。

## 查看

- [两版对照与实际小尺寸](comparison.png)。左为原版质感，右为玻璃质感，均为石墨底、银白 R。
- [原版质感工程](ReviewToday-Monochrome-Original.icon)：两层同形 R，渐变白色 0.96→0.76，88% 缎面覆层、12% R 阴影，图层比例 0.58；不加独立玻璃壳。按参考的克制渐变和轻微厚度重建，非截图逐像素去色。
- [玻璃质感工程](ReviewToday-Monochrome-Glass.icon)：最终沿用 0.68 比例、65% 缎面覆层和 R 的原生玻璃高光；Rex 已删除底座内侧的玻璃边缘图层，保留空组以忠实保存其工程状态；所有可见材质色均为中性灰，无绿色点睛。
- [原版质感 1024 PNG](original/default-1024.png)、[玻璃质感 1024 PNG](glass/default-1024.png)。两目录各含 Default / Dark / Mono 的 16、32、64、128、256、512、1024 px 原生导出。

## 原版保留

`original-preserved` 中的 [user-original.png](original-preserved/user-original.png) 是本轮用户附件原文件，92×92 px，未经裁切、放大或修改。另保存现有透明母版 `mark-alpha.png`、当前生产导出的 `current-app-icon-1024.png` 和已采用的 `accepted-a-reference.png`；当前生产图标是既有平面资产，不声称它包含附件的全部材质。原路径与绿色玻璃 v1–v3 均保留。`sha256.json` 记录每份归档的内容摘要。

## 验证与重建

两工程已在 Xcode 随附 Icon Composer 1.6 中打开、保存、关闭后重开，并实际查看默认外观。原生导出使用重存后的工程；42 张输出的尺寸及来源校验见 [validation.json](validation.json)，所有填充均验证 RGB 三通道参数相等，两份 R 资产与现有透明母版逐字节一致。Alpha 与四角透明检查记录在 `alpha-validation.txt`。对照板只排版原生 PNG，没有后期锐化或滤镜。

重建：项目根目录运行 `python3 brand/refresh-2026-09/monochrome-preview/export.py`，再运行 `swift brand/refresh-2026-09/monochrome-preview/render-board.swift "$PWD/brand/refresh-2026-09/monochrome-preview"`。

本机证据为 macOS 26.7；本张图标外观已由 Rex 附图确认；macOS 27、Dock/Finder 正式接入与发布尚未完成。未改变产品整体配色或吉祥物规则。
