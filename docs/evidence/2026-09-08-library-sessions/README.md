# 知识卡与会话交互验证 · 2026-09-08

已按批准方案实现，Debug / Release 构建及定向回归通过，日常开发 App 已更新。最终尺寸、动效节奏和使用手感仍待 Rex 验收。本轮先更新 DESIGN.md 再实施，未修改分类、自动标题、数据模型、服务接口或模型配置。

## 实际变化

- 已暂停、已删除及共用知识库空态复用待处理的 `MascotMotion(phase: .idle, ambient: true)`，画布为 150×170，保留状态文案与共用暂停/减少动态生命周期。
- 卡片宽度为内容区减 96 pt、最多 880；高度减 112 pt、最多 560；不足 640 pt 改为单栏。标题通栏，宽窗正文左右为解释/来源与问题/判断要点，只有一个正文滚动区，底部更多/试一题固定。
- 鼠标从标题区左拖下一张、右拖上一张；标题有抓手光标和提示。后两张居中向下露出；短拖回弹，循环、单卡、反向与连续输入有独立状态处理。右侧竖向定位可滚动、点击跳转、悬停读标题；键盘左上一张/右下一张，Escape 关闭。
- 来源文本拖选和原生文本方向键不触发翻卡，正文纵向滚动、按钮和后层卡不会成为鼠标翻卡入口。横向触控板只从卡内接管，捕获后在卡外结束/取消也会收尾；失焦、隐藏、卸载取消手势。
- 会话第一行保留会话、归档范围入口、新建；第二行放当前范围、搜索、多选。多选原位替换为数量/全选/归档或恢复/永久删除/完成，保留已展开搜索框。范围切换和新建重置搜索与选择；搜索改变清空勾选但保留多选，数据变化排除不可见目标，失败项保留重试。

## 原生检查与证据

环境为 macOS 26.7 / Apple Silicon。独立预览直接编译产品 SwiftUI/AppKit 视图，使用 `M1DebugFixture` 内存模型，预览发送能力关闭。会话恢复和删除确认只操作此隔离数据；永久删除与保存失败由现有隔离契约测试验证，没有在日常数据上执行破坏性测试。

| 场景 | 实际结果 |
| --- | --- |
| 标准窗口 1280×820、浅深主题 | 宽卡两栏、标题与固定底部完整；两张后层居中露出。 |
| 最小内容窗口 760×620（导出整窗 760×652） | 自动单栏；长标题折为两行，长正文可滚动；展开 250 pt 侧栏时最完整的归档多选工具栏仍可用。 |
| 左拖/右拖、连续方向键、未完成拖动 | 双向浏览正确；短拖回弹及反向取消另有状态测试。原生连续 Right/Right/Left 保留最后选择。 |
| 正文、来源、定位 | 长正文滚动保持卡号；来源展开、拖选及方向键保持当前卡；定位点击有效，24 张样例可滚动定位条而不翻卡。 |
| 单张与关闭 | 光合作用筛选只剩 1 张，左右键不改变卡片；Escape 关闭详情。 |
| 归档搜索与多选 | RAG 搜到 2 张归档会话，全选显示 2；搜索改为向量后显示 0、批量按钮禁用，多选模式保留。 |
| 范围、新建、恢复与删除确认 | 切换范围清空/收起搜索并退出多选；新建返回进行中与原草稿，不新增空会话；隔离恢复成功移出归档列表。删除确认只列当前可见所选会话，取消后无删除。 |
| 减少动态与吉祥物 | 使用预览的同一 `brandReduceMotion` 环境覆盖检查直接切卡；深浅空态角色比例一致、随机待机可见。共用 WK 原生回归覆盖隐藏暂停、恢复与减少动态。 |

以下为本机实际原生窗口、正常呈现时间戳的 H.264 录屏，无加速、无离线动画替代、无音频。只录制验收进程自己的窗口；未申请其他应用或整个桌面的访问。目标 30 fps，ScreenCaptureKit 按内容变化提供可变帧率，不宣称稳定 30 fps。全部文件完整解码通过；尺寸、帧数和时长见 [录屏元数据](recording-metadata.json)。

| 文件 | 内容 |
| --- | --- |
| [标准窗口翻卡](native-deck-standard.mp4) | 25.07 秒，1280×820，12 张样例；左右拖动、键盘和定位。 |
| [最终输入版本翻卡](native-deck-final.mp4) | 25.25 秒，1190×690，24 张样例；正文拖动不翻、标题双向拖动、连续键盘。 |
| [归档搜索、多选与新建](native-session-selection.mp4) | 23.72 秒，760×652；搜索 RAG、全选、改搜索清空勾选、新建重置。 |
| [减少动态切卡](native-deck-reduced.mp4) | 2.14 秒，直接切换及卡号反馈；使用预览覆盖，不代表本轮操作过系统设置。 |
| [暂停/删除空态待机](native-empty-mascot.mp4) | 43.49 秒，实际 Spine 待机与状态切换。 |

标准翻卡、减少动态和空态录像录于失焦/触控板边界补修前；这些画面对应的布局与动效未再变化。最终输入录像和归档录像来自最后版本，全部输入边界测试在最后修改后再次通过。

截图：[浅色宽卡](wide-light-stack.png)、[深色来源](wide-dark-source.png)、[深色长正文](wide-dark-long-content.png)、[窄窗长卡](minimum-long-card.png)、[来源文本操作](source-text-interaction.png)、[窄窗归档多选](minimum-archived-selection.png)、[暂停深色](paused-dark-mascot.png)、[删除深色](deleted-dark-mascot.png)、[删除浅色](deleted-light-mascot.png)。

## 自动化验证

- `KnowledgeDeckNavigationTests`：真实导航状态与原生 AppKit 事件，覆盖双向/循环/跟手、反向/短拖/甩动、连续操作和过期完成回调、单卡/空集、删除或重排后的身份、宽窄尺寸/实际露出层；标题/正文/控件/文本/键盘范围，滚轮动量，触控板持指停顿，卡外结束/取消，失焦、后台、卸载和后续手势。
- `SessionListSelectionTests`：标题/标签检索范围、切换与新建重置、搜索清空勾选、Shift 范围选择、同数量不同身份、不可见项排除、外部恢复与部分失败重试。
- `InteractionFocusTests`、`UIPolishContractTests`：焦点来源、祖先焦点保护、原生文本选择、既有标题与 UI/角色配置契约。
- `SessionDeletionContractTests`：删除预览、保存失败回滚、执行前重新核对范围、共享/未知关联知识保护、批量清理、离线 tombstone 与防复活。
- `node --test tools/mascot-motion/test/*.test.mjs`：31/31 通过；`bash tests/mac/run-mascot-native.sh`：资源源/包一致，WK 实际运行、暂停/恢复、减少动态及既有思考/语音回归通过。
- Debug Apple Development 签名构建、`codesign --verify --deep --strict`、Release 未签名编译全部通过；最终输入改动后重跑翻卡全源测试与两个构建。没有运行服务端全量套件或新增真实模型/听写请求。

两个新增契约已加入 `tests/mac/run-contracts.sh`。定向复跑可执行：

```sh
bash tests/mac/run-dictation-contracts.sh InteractionFocusTests UIPolishContractTests SessionDeletionContractTests SessionListSelectionTests KnowledgeDeckNavigationTests
node --test tools/mascot-motion/test/*.test.mjs
bash tests/mac/run-mascot-native.sh
```

## 复现与待验收

日常入口：`output/default-brand-build/Build/Products/Debug/Review_Today.app` → 知识库 → 打开知识卡，或侧栏归档入口。已重启新版并确认两层工具栏与原有 8 张知识卡入口。

隔离复现：运行 `bash tests/mac/run-library-session-preview.sh`，打开输出的 `ReviewTodayLibrarySessionPreview.app`。菜单“验收”可切换标准/最小窗口、深浅主题、减少动态、保存本窗口截图及最多 45 秒录屏。包含长正文、24 张卡、3 张已归档会话；重新启动恢复内存样例，不连接模型。

仍未完成的体验项：实体触控板手感、完整 VoiceOver、非中文排版。本轮未再次切换 macOS 系统减少动态设置；原生录屏使用与该设置汇合的环境覆盖，底层静止/恢复由共用运行时测试确认。批量保存失败的 UI 提示未在原生窗口注入，恢复状态由选择/删除契约覆盖。以上不伪报为人工体验通过；卡片初稿尺寸和动效观感交 Rex 验收，不关闭 M1/#17 或执行正式发布。
