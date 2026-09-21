# Jev 原生 App 测试入口（2026-09-21）

用户要求现在在 App 中亲自测试。已接通独立 Debug 测试版，服务与 Mac 契约通过；本启动批次结束时原生窗口已打开，但自托管服务等待系统文件访问授权，尚未发送真实问题。不能把构建成功或开关存在当作本批真实调用已生效。

后续状态：本机授权已恢复，Rex 已实际发送；回复反馈修复后完成三轮原生验证，真实 Jev 调用及采用记录已核对，原会话未改写。见 [后续验证](../2026-09-21-reply-feedback/README.md)。下方零调用与阻塞诊断保留为首次启动的历史记录。

## 使用

双击仓库的 `tools/run-jev-app-test.command`。它使用现有 Apple Development 签名构建「Review Today · Jev 测试」，新建临时数据和非日常端口，并读取既有 Jev 凭证文件。Key 不写入命令行、日志或仓库，不修改任何供应商配置。

进入 Agent，底部出现「Jev 测试已启用」后可输入。此时内容会发给 Jev 和现有模型；Jev 失败或不确定仍回退，入口保留一次 LLM 判断。测试数据独立于日常知识库与正式复习，每次运行入口创建新测试库，退出测试 App 结束该实例。

首次启动若出现桌面文件夹访问提示，需用户授权读取桌面中的项目。授权后在 Agent 顶部点「重试连接」。测试界面未收到匹配的 Jev 状态时不会显示已启用；认证失败时明确显示已回退。

## 已验证

- 服务：[685 tests / 315 subtests](controlled-tests.txt) 通过。覆盖默认关闭不读取凭证、日常端口与非临时库拒绝、坏凭证不泄露、认证失败停用实例与健康状态。
- Mac：[运行模式、服务生命周期、会话回放](native-contracts.txt) 通过；补充旧规则版本拒绝后的 [最终运行模式检查](runtime-contracts-final.txt) 通过。兼容旧健康响应，测试开关不能在日常或预览身份启用，旧服务不能冒充 Jev 就绪。
- [Debug NativeQA 构建](native-build.txt) exit 0，`codesign --verify --deep --strict` 通过。保留原有 Swift 并发等警告；不是发布构建。
- 通过 Computer Use 打开实际测试 App、进入 Agent，观察到专属窗口标题和「学习服务尚未连接」状态。没有向日常 App 输入或写入数据。

## 首次启动的原生阻塞（后续已恢复）

应用身份 `Rex.Review-Today.Jev.NativeQA`，本次端口和临时库见 [runtime.json](runtime.json)。服务四次有限启动后停止；health 未响应，Python 采样停在初始化阶段的 `getpath_readlines → fopen → open`，尚未进入 Harness。系统日志同时记录此应用的桌面文件夹访问状态为 Unknown，见 [限定启动诊断](startup-diagnostic.txt)。没有证据表明 Jev API 或 DeepSeek 请求失败，也不能由 AllFiles 预检推断需要完整磁盘访问。

已向 Rex 请求这个新测试 App 的桌面访问授权。未修改系统权限、借用其他身份启动常驻服务或重置隐私设置。本批真实 App 请求数为 0，节点采用、实际整轮耗时和费用尚未取得；此前对照数据保留在 2026-09-20 报告，不冒充本次 App 验证。
