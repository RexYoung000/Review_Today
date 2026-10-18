# 搜索方案已在本机 App 启用

Rex 在 WEB-04 对照后确认「按这个来，落实到 APP」。本机正常 Debug App 已重新构建、通过签名验证并启动，实际由 App 托管的服务已加载以下顺序：

- 搜索：**DeepSeek → Exa → Tavily**。
- 正文：**Exa → Tavily → DeepSeek → Browser**。
- 模型、一次质量补查、调用预算、Context 关闭和 Jev 关闭均保持原方案。

现在可直接进入 App 的 **Agent** 页面使用。已实看正常身份窗口、原会话列表、11 条知识和可用的输入／发送入口，没有阻塞服务横幅；本批没有发送测试消息。完整结果见 [activation.json](activation.json)，实际健康响应见 [health.json](health.json)。

## 本机更新与实际加载

启动前默认 Xcode Debug 构建产物不存在，日常 App／服务均未运行。先对本机 SwiftData、服务 checkpoint 和复习服务三个数据库做 SQLite 一致性备份，完整性均正常；私有配置同时备份、权限 600。

沿用工程原 Apple Development 签名、Team `7NDKLL3UJK` 与 `Rex.Review-Today` 身份，在原 Xcode Debug 位置重新构建，构建成功、`codesign --verify --deep --strict` 通过。产物和运行进程均为：

`~/Library/Developer/Xcode/DerivedData/Review_Today-gkeqhkrlvxqhunchqjqzselqoapv/Build/Products/Debug/Review_Today.app`

本次实际 App PID 2333，服务 PID 2374、父进程为 2333；服务工作目录为当前项目的 `agent-service`。实际 HTTP 健康响应确认搜索三家及读取四级顺序，三个模型角色均 ready，教练 smart／deep 流式均 ready。配置现在已经由运行中的 App 使用，不再只是等待下次加载。源码与 `.env` 未改；本批 183 份生产源码／配置／工程文件校验保持，原 Xcode 工程未提交差异完整保留。

## 启动用量与数据核对

App 正常启动自带能力检查实际产生 **1 批、1 轮、8 次模型请求，8 份唯一用量回执**，随后 finished、无待自动重试。共 1,574 tokens：输入 1,244、输出 330、含缓存输入 256、推理输出 135。[启动账本](startup-probe.json)独立于会话和所有既有评测批次。

启动前已核对没有 accepted／queued／running 问答、待提交的本机用户消息、待发送动作或旧版未完成动作。启动前后所有既有服务会话／学习任务及复习服务表保持，原会话模型请求总数均为 **124**；本批新增普通问答请求 **0**、网页操作 **0**，未恢复 EVAL-03 或已关闭对照批次。

本机 **7 个会话、37 条聊天、11 条知识**保持；资料、问题、知识关联、复习会话、作答和排期的业务字段比较一致。正常启动同步更新了会话 checkpoint／学习记录投影／邀请版本，打开 Agent 生成了空草稿身份，另有任务更新时间和内部主键计数变化；具体表与变化字段保留在 activation，不将其描述为所有数据库字节不变。比较仅排除框架内部乐观锁字段 `Z_OPT`，未忽略知识或聊天正文。

## 证据与范围

- 已完成：签名 Debug 构建、真实 App 启动与原生页面观察、实际服务主备配置与父子进程核对、真实能力检查及用量归属、三库备份与业务数据对照、凭据及原工程差异保护。
- 本轮 `web_search`／`web_read` 健康状态仍为配置层 `unverified`，含义是当前问题仍须取得真实结果和正文；不把配置健康当成新一轮网站调用成功。本批没有额外发新问答或重跑搜索，真实内容质量及成本边界沿用 [WEB-04](../2026-10-18-web-ab/README.md)。
- 生产逻辑与界面没有新改动，没有新增全量服务回归或完整原生教学保存验收；不扩大先前 6/8 的质量结论，也没有据此认定真实账单节约。旧的漏答／引用覆盖问题仍在后续记录中。
- 这是本机开发 App 启用，没有合并、生产发布或分发。最终使用手感由 Rex 体验。

一致性备份、构建日志、原始校验与状态仅在忽略目录 `output/web-app-2026-10-18/` 留存，私钥和原始用户内容未写入 Git。
