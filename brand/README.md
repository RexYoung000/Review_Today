# Review Today 正式品牌资产 V8

> 当前阶段：已制作确定性矢量母版，等待 Rex 对实际渲染、Dock／Finder 小尺寸与单色标志进行视觉验收。

## 文件

- `review-today-app-icon.svg`：128–1024 px 彩色 App 图标母版。
- `review-today-app-icon-small.svg`：16–64 px 光学校正母版，轮廓更粗、五官更大、卡片信息更少。
- `review-today-mascot.svg`：透明背景完整抱卡吉祥物，卡片保留极浅纸纹。
- `review-today-mark.svg`：单色品牌标志，适合水印和较大的单色位置。
- `review-today-menu-bar-mark.svg`：菜单栏／极小尺寸简化标志。
- `palette.json`：V8 首轮渲染的精确色值。
- `exports/brand-acceptance-board.png`：角色、图标、单色标志、色板与实际尺寸检查板。
- `export_brand_assets.sh`：重新生成全部 PNG，并同步覆盖工程 AppIcon 资源。

## 重新导出

在项目根目录执行：

```shell
./brand/export_brand_assets.sh
```

脚本分别使用大尺寸和小尺寸 SVG 母版：128–1024 px 使用完整母版，16–64 px 使用光学校正母版。

## 使用边界

- App 图标默认表情是居中闭口微笑；两颗板牙只保留为未来互动表情候选。
- 卡片使用标题色块和内容线表达知识资料，不放真实文字、问号、对勾或产品 Logo。
- 陶土珊瑚是品牌／Agent 强调色，不取代产品中的掌握成功、提醒和错误语义色。
- 产品正式名称尚未确认，本包不包含 Wordmark。
- SVG 可以导入 Figma 继续维护；导入后必须保持 viewBox、颜色角色和小尺寸独立母版，不把大图机械缩小为 16 px。

## 验收要求

1. 检查 1024、128、64、32 和 16 px 是否仍能识别呆毛、闭口微笑与知识卡。
2. 在 Dock、Finder、启动台和应用切换器检查图标边缘、留白与背景对比。
3. 在浅色、深色桌面以及菜单栏模板渲染中检查单色标志。
4. 只有实际渲染通过并由 Rex 确认后，才能把精确色值与几何标为最终品牌规范。
