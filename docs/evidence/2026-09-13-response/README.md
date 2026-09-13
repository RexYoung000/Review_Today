# 侧栏反馈与切页响应优化

2026-09-13，macOS 26.7／Apple Silicon；基于原生 SwiftUI 主导航、会话列表和 MascotMotion 离线动画。Rex 已授权实施，最终指针手感待验收。

## 实现

- 主导航与会话共享高亮改为 80 ms，仅动画底板位置；主导航使用 7% 墨色悬停底板、12% 选中底板，悬停文字立即使用正文色，选中仍有粗体。首次进入、跨组和减少动态不移动过渡。
- 主导航将几何、悬停与焦点放到独立子视图，避免随指针换行重算父侧栏的会话查询和列表。全局输入方式不再对相同方式重复发布，关闭独立悬停反馈的控件也不重复写入本地悬停状态。
- 只复用已就绪的 ambient idle recall 离线动画，最多保留两个离屏实例。切走暂停并清除原页面回调；借出前检查已脱离视图树，重新应用主题、减少动态、片段与可见状态。失败、未就绪及超额实例释放；语音／任务状态与 Mr. B 入库演出不进入缓存。

## 验证

- `bash tests/mac/run-dictation-contracts.sh InteractionFocusTests FluidHoverContractTests` 通过：焦点与选中独立、浅深与禁用渲染、分组空隙、文件夹边界、稳定命中与刷新身份。结果见 `interaction-contracts.txt`。
- `bash tests/mac/run-mascot-native.sh` 原生动画回归与缓存生命周期检查通过，结果见 `native-animation.txt`。用实际 WKWebView 文档标记检查复用没有重新加载；覆盖暂停、更新配置、旧回调、未脱离窗口、加载中、进程终止、非待机排除和容量淘汰。
- 补充的真实 SwiftUI 条件页面检查通过：隐藏页面后已卸载载体进入缓存，重新显示页面时取得同一 WKWebView 与文档。补充回归曾两次在既有的固定 400 ms「Ambient idle did not breathe」检查失败；随后用同一可执行文件，通过原生窗口 Raise 明确保持前台，完整回归通过。未修改断言或放宽等待阈值；这些结果支持前台路径通过，不能据此把两次失败的原因唯一归结为失活，也不作为帧率保证。失败摘要见 `native-animation-retries.txt`。
- `bash tests/mac/run-library-session-preview.sh` 构建通过；内存数据下原生检查 Agent／知识库／待处理切换、学习方式菜单展开和 Escape 关闭、知识详情关闭和重新进入；Tab 聚焦今天 + Return 打开今天，再 Tab 到知识库 + Space 打开知识库。`keyboard-focus.png` 展示今天选中、知识库持有独立焦点。
- 隔离预览覆盖标准浅色窗口和 760×620 内容最小窗口，后者切换深色、手动展开侧栏并开启减少动态。`light-selection.png`、`dark-minimum.png` 记录实际选中反馈。原生自由悬停尚未验证，截图不证明预选动画。
- 签名 Debug 与未签名 Release 的 `xcodebuild ... -derivedDataPath /tmp/review-today-response-build build` 均通过；Debug 通过 `codesign --verify --deep --strict`。保留既有开发签名，将最终 Debug 构建更新到日常 Xcode DerivedData 路径后重启。原有 3 个会话和 8 张知识卡仍可见，Agent 菜单与待处理页面正常；8742 `/healthz` 返回 ok、conversation/response-stream protocol 1。未发真实模型消息、未改业务数据和服务配置。

`navigation-and-popover.mp4` 为隔离原生窗口的实际交互录像，1280×820、45.03 秒、1262 帧；保留源时间戳，完整解码通过。约 28 fps 的实际录制不能作为 UI 帧率或点击延迟指标，也不是自由悬停录像。

## 性能结论与边界

原生验证证明重新借出的动画载体仍是同一 WKWebView 与同一 HTML 文档，消除了这一条路径的重复初始化。日志中的 cold ready 包含就绪轮询，warm acquire 只记录借出调用，二者边界不同，不能直接计算提速比例。80 ms 是动画配置，不是端到端实测；未进行 Release 运行、逐帧点击到呈现计时、快速自由指针往返、VoiceOver 或长时间内存观察。

日常验收：在四个主导航间快速上下移动并点击，悬停应清楚、跟随利落，原选中项保留粗体和更深底色；点击行间空隙不切页。反复打开学习方式菜单、知识详情并往返待处理，内容操作应立即响应，角色返回不再重复冷加载。实际手感和视觉由 Rex 验收，已有采样未证明所有短促卡顿已消除。
