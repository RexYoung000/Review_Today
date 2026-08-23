# Review Today 品牌资产 V8

> 当前阶段：GPT Image 生成的位图母版已选定，等待 Rex 对角色质感、App 图标裁切和小尺寸表现进行视觉验收。

## 正式母图

- `raster/mascot-master-v8.png`：完整闭口抱卡吉祥物，统一暖白产品底。
- `raster/app-icon-master-v8.png`：陶土色 App 图标模型母图。
- `raster/mark-master-v8.png`：暖白底单色石墨标志母图。
- `exports/brand-acceptance-board.png`：三项母图与实际 AppIcon 尺寸的集中验收板。

## 生产原则

- 角色内容、线条、表情、卡片和材质均由生成模型产出，不使用 SVG 或代码重新描画。
- 工程脚本只负责裁切、缩放、macOS 圆角蒙版和 PNG 打包，不添加或修改角色内容。
- AppIcon 的 16–1024 px 版本均从选定的 `app-icon-master-v8.png` 导出。
- 产品正式名称尚未确认，本包不包含 Wordmark。
- 当前完整吉祥物没有透明通道。模型把透明棋盘格画进 RGB 文件的失败稿已排除；只有文件真实包含 Alpha 时，才允许标记为透明 cutout。

## 重新打包

在项目根目录执行：

```shell
./brand/export_brand_assets.sh
```

该命令不会生成或重画角色，只会从已选定的模型母图重新导出工程资源和验收板。

## 验收要求

1. 对照三张母图检查是否仍是同一个角色，尤其是眼距、刘海、呆毛、闭口微笑、双臂和两张知识卡。
2. 检查 1024、128、64、32 和 16 px 的卡片语义与表情是否仍然可辨认。
3. 在 Dock、Finder、启动台和应用切换器检查图标裁切、圆角、留白和陶土底质感。
4. 视觉通过前，不把当前模型输出称为最终品牌定稿或 Spine 可用拆件。
