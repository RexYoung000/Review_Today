# 会话列表悬停扩展验证

2026-09-10。最终范围仅会话列表；Rex 实际体验后撤回知识库与快捷开始扩展。代码核对确认 KnowledgeLibrary.swift、LearningWorkspace.swift 和 QuickStartCard 全部恢复到此前提交。主导航保留上一轮实现。

## 实现

会话列表保留既有 LazyVStack、滚动目标、顺序和菜单。按未分类／文件夹测量行边界，只在组内小间隙寻找最近行；悬停底板只绘制、不接受点击。选中填充、字重、焦点与菜单入口独立。列表滚动、尺寸／数据改变、窗口失活、减少动态切换或菜单打开时清除旧高亮；组内 120 ms 过渡，跨组／首次进入原位出现。聚焦行后 Return／Space 打开会话。

## 验证结果

- 最终 `FluidHoverContractTests` 通过：行间小间隙、文件夹标题分隔和缩进、组外区域、空／无效目标、顺序变化下稳定并列选择、刷新后的真实 ID。测试验证目标选择，不证明真实指针事件、点击区域或滑动手感。
- 最终 `SessionOrganizationContractTests` 通过：分组创建／移动／失败回滚、归档范围、文件夹保留、磁盘重开和删除文件夹时保留会话。
- 共享焦点与 LearningInputContractTests 在前段通过；被撤回的卡片扩展不再作为交付或验证收益。
- 最终 LibrarySessionPreview 构建与 Debug Xcode 构建通过（CODE_SIGNING_ALLOWED=NO；不是发行签名或发布验证）。
- 在最终原生隔离 App 中：点击 RAG 会话打开对应历史；Tab 移到向量数据库时 RAG 仍选中；Return 打开向量数据库；该行更多菜单独立展开、Escape 关闭并回到该行。浅色／减少动态下 Shift-Tab 聚焦检索质量评估，Space 打开正确会话。正常动态已恢复。
- `session-keyboard-and-menu.mp4` 是原生窗口录像，覆盖上述深色键盘／菜单操作；两个截图分别为焦点独立和浅色减少动态导航。只使用内存 fixture，不连接模型或日常数据库。

复跑：`bash tests/mac/run-dictation-contracts.sh FluidHoverContractTests SessionOrganizationContractTests`；`bash tests/mac/run-library-session-preview.sh`；`xcodebuild -project Review_Today.xcodeproj -scheme Review_Today -configuration Debug -derivedDataPath /tmp/review-today-hover-build CODE_SIGNING_ALLOWED=NO build`。

## 仍待体验检查

沿用上一轮工具限制：当前原生自动化没有独立自由移动指针操作，未将滚动或点击冒充连续悬停验证。会话滑动节奏、快速往返、实际跨文件夹／滚动清理、空隙点击不触发和系统减少动态下指针切换仍未完整实测；未运行 VoiceOver，不声称用户接受。

入口：`output/library-session-preview/ReviewTodayLibrarySessionPreview.app` 已重新打开最终版本。展开侧栏，在会话之间移动鼠标；底板应跟随但不切换当前会话，不跨文件夹标题；点击省略号只打开菜单。菜单“验收”可切换主题和减少动态。知识库和快捷开始应保持此前单卡行为。
