# 今天入口：B 玻璃反光与边缘流光

2026-09-24。Rex 选择 B，并以 [React Bits Star Border](https://reactbits.dev/animations/star-border) 的上、下缘反向流动作为动效参考。本次在 SwiftUI 的系统玻璃上实现中性银白边缘流光；没有接入 React、CSS 或新的依赖。正式 App 的「开始学习」「模拟考」共用 `TodayGlassEntry`，仅在窗口有效且鼠标实际悬停时播放，离开即停止。键盘聚焦、减少动态和减少透明度使用静态反馈。

已将最终构建更新到原有 `Review Today · Jev 测试` 实例（`Rex.Review-Today.Jev.NativeQA`）；沿用原测试库、服务端口及凭证来源。替换前备份了 App 和 SQLite，签名严格校验通过。重启后 Jev 测试服务 `/healthz` 为 200，界面再次显示「Jev 测试已启用」；SQLite 完整性为 `ok`，知识 0、会话 3、消息 30、复习轮次与尝试 0，和替换前一致。点击两个入口分别进入现有 Agent 和模拟考模式选择页。

原生原型与 App 共用同一入口实现。对照原型的定点控制只预览静态反光位置，不会让未悬停的入口播放流光；左侧保留原版作为历史对照。原型与 Debug App 构建通过，`ReviewUIIntegrationContracts` 通过；实际浅深色、减少动态、窄窗口堆叠和点击反馈已检查。截图来自原型自身窗口的 ScreenCaptureKit 截屏，不含音频和用户数据：

| 状态 | 证据 |
| --- | --- |
| 浅色、无悬停、流光隐藏 | [idle-light.png](idle-light.png) |
| 浅色、定点静态反光、无流光 | [static-reflection-light.png](static-reflection-light.png) |
| 深色、定点静态反光、无流光 | [static-reflection-dark.png](static-reflection-dark.png) |

界面自动化能点击和拖动，却未产生 macOS SwiftUI 的真实 `onContinuousHover` 移动事件；因此以上截图只证明默认态与静态态，不能当作实际悬停动效验收。沿边缘运动和停止条件已接入并通过构建，**真实鼠标连续悬停的流光强度、节奏和帧率仍待 Rex 直接在 App 中体验**。入口位于「今天」的复习主区域下方；鼠标移到任一卡片，应只在该卡片边缘看到反向移动的流光，移开后立即消失。
