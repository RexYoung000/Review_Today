# 主导航连续悬停增量验证

2026-09-10；Review Today 原生 macOS，使用现有 LibrarySessionPreview 隔离 bundle 与内存样例，不连接模型或日常数据。仅改变展开侧栏的四个主导航入口；会话、知识卡和收起图标栏未采用连续高亮。

## 已实现

同组一个不可命中的浅色底板，按最近行定位，组内 120 ms 过渡，首次进入原位显示。选中填充和字重、按下反馈、独立键盘焦点保留。没有空隙点击代理。离开、窗口失活、布局改变和侧栏隐藏清除悬停；减少动态直接切换。另修复本次原生检查发现的聚焦入口 Return／Space 未切页，沿用同一导航动作。

## 已验证

- `bash tests/mac/run-dictation-contracts.sh InteractionFocusTests` 通过：共享样式的单行键盘焦点、选中独立、浅深色和禁用状态渲染。
- `bash tests/mac/run-library-session-preview.sh` 最终构建通过，已重启该构建复测键盘修复。
- `xcodebuild -project Review_Today.xcodeproj -scheme Review_Today -configuration Debug -derivedDataPath /tmp/review-today-hover-build CODE_SIGNING_ALLOWED=NO build` 最终通过；未签名发行验证。既有警告未在本轮处理。
- 原生操作确认：点击 Agent／今天／待处理正确切页；Tab 移到知识库时 Agent 仍选中；Return 打开知识库，下一次 Tab + Space 打开待处理。
- 浅色标准窗口、深色加减少动态、760×620 内容最小窗口及侧栏展开／收起可用。减少动态下已验证键盘导航，未证明指针滑动降级。
- `keyboard-navigation.mp4` 为最终修复版原生窗口录像，只证明键盘与页面状态，不是悬停动效证明。三个 PNG 对应浅色焦点独立、深色减少动态导航、最小窗口展开。

## 未验证与验收入口

当前 CUA 原生工具提供点击、键盘、滚动与拖动，没有独立自由移动指针操作。本轮尝试未触发可确认的连续悬停事件，因此不能声称滑动动画、快速往返、真实行间空隙命中、指针离开／失活清理和减少动态滑动降级已通过。未运行 VoiceOver。代码完成不等于悬停体验验证完成或 Rex 已验收。

运行 `bash tests/mac/run-library-session-preview.sh` 后打开 `output/library-session-preview/ReviewTodayLibrarySessionPreview.app`（已保留打开的标准尺寸窗口）。在展开侧栏的四项间缓慢／快速来回移动鼠标，应见浅色底板跟随而选中项不变；点击行间空隙应不切页，点击按钮立即切页。Tab／Shift-Tab + Return／Space 可导航。菜单“验收”可切换主题、最小窗口与减少动态；关闭减少动态再比较滑动。

本轮未改日常安装包、未发布，其他并行角色试演改动不属于本提交。
