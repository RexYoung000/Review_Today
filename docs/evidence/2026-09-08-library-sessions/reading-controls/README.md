# 知识卡展开区与管理图标

2026-09-08 已接入日常 App；只调整呈现与输入反馈，知识原文、选择范围、状态动作及删除保护保持。

- 常见误区整行点击，包括标题、数量和右侧空白；数量紧贴标题，有常态底、悬停/按下/展开反馈。Space、Return 可切换；减少动态直接切换。
- 三条误区按 1、2、3 展示，判断要点逐条圆点。长内容沿用正文滚动。
- 多选 checklist、全选方框、暂停、恢复、回收、永久删除及完成均使用 SF Symbols；计数为图标加数字，保留完整可访问名称、悬停说明和禁用反馈。归档页共用样式。
- 卡片显示时后方知识列表禁用；原生复测 Tab 不再进入后方小卡菜单。侧栏导航仍可使用。

## 可查看的证据

[标准浅色阅读](reading-standard-light.png) · [深色阅读](reading-dark.png) · [最小窗口键盘聚焦](reading-keyboard-minimum.png) · [标准浅色多选](selection-standard-light.png) · [深色多选](selection-dark.png) · [回收站图标](trash-actions-dark.png) · [归档管理图标](archive-icons.png)

[鼠标右侧空白点击与 Space/Return 展开，14 秒](disclosure-mouse-and-keyboard.mp4)；[全选、暂停与回收站图标，45 秒](selection-actions.mp4)。均为隔离内存样例原生录制，原始时间戳，无加速、无音频。逐文件尺寸、时长、哈希与完整解码结果见 [录制信息](recordings.json)。

macOS 26.7 原生检查标准/最小宽度、浅深、收起/展开、四条圆点与三条序号、键盘及减少动态环境覆盖；图标全选 24、取消全选、暂停到已暂停、移到回收站、恢复在用实际执行，归档全选 3。未在日常数据库执行状态或删除测试。日常 App 仅打开用户原有的 RAG 优势卡检查显示。

Debug/Release、Debug 严格签名通过；复用 `UIPolishContractTests`、`KnowledgeDeckNavigationTests`、`SessionListSelectionTests`，检查焦点/原文保留、正文/按钮与翻卡输入隔离、选择范围及失败重试状态，通过输出见 [验证摘录](validation.txt)。原生验收入口仍为 `tests/mac/run-library-session-preview.sh` 生成的独立 App，菜单“验收”可切窗口与主题；后续导出默认仍进入相邻 management 目录。

日常开发入口：`output/default-brand-build/Build/Products/Debug/Review_Today.app`。打开知识库 → RAG 的主要优势 → 常见误区，检查数字间距、整行点击和要点标记；关闭卡片后检查主题右侧的多选图标。完整 VoiceOver、系统级减少动态开关及实际多语言译文尚未验收，图标化不等于已完成翻译。最终视觉与手感待 Rex 确认。


## 增量：来源与误区展开框统一（2026-09-08）

来源证据复用整行展开按钮，两个区块均为文字靠左、误区数量紧跟标题、箭头在最右侧。共用轻量浅底，来源的无障碍提示使用自己的名称；保留原文选择和来源链接。

Debug/Release、隔离原生预览构建和严格签名检查通过；原生验证点击来源/误区框内中部空白可展开，来源 Space 收起、Return 展开，宽窗浅色及最小窗深色、预览减少动态效果。日常 App 已更新并打开 RAG 优势卡，两处展开正常。此次为共用组件布局修订，未新增镜像实现的单元测试；完整 VoiceOver、真实外部来源跳转未重验。

[原速操作录像](disclosures-unified.mp4)、[浅色展开效果](disclosures-light.png)、[深色来源](source-dark.png)、[深色收起效果](disclosures-collapsed-dark.png)。视频保持真实时间戳，无音频，完整解码通过；最终视觉仍由 Rex 验收。
