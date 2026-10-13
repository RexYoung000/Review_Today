# 事件回放与恢复检查（2026-10-13，分项检查通过／未新增实现）

ZCode 第 5 条第一小点：统一事件顺序、可靠保存后确认，以及恢复已有事实与重新执行的区别。本轮为只读检查与隔离验证，没有获批新恢复规则或生产代码修改。

固定研究版本为 `29628c9acdb81b703bbd4080c207a0e7ce5e276e`。其 [events.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/events.ts)第 75–102 行先从事件存储取得统一顺序号，再尝试选定业务记录的持久化并通知界面；第 248 行后的业务分支部分失败只记录 warning，因此不能概括为所有事件都可靠落盘、全部持久化失败都会阻断通知。[resume.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/resume.ts)恢复已有会话事实；本次没有运行 ZCode，不采用其重启丢弃待处理引导输入的规则。

Review Today 对照入口：[ConversationStore](../../../agent-service/agent_service/conversation_store.py)、[恢复增量](../../../agent-service/agent_service/checkpoint_delta.py)、[会话同步](../../../Review_Today/ConversationSync.swift)、[本机持久化](../../../Review_Today/ConversationProcessor.swift)、[检查点合并](../../../Review_Today/ConversationCheckpoint.swift)。既有意图在 [Harness §17](../../agent-harness-v2.md)维护，TOOL-01 的保存回执验证继续引用原记录，不重做或扩大其验收。

## 实现对照

| 既有边界 | 当前实现证据 | 本轮检查 |
|---|---|---|
| 状态与事件顺序使用同一依据 | `ConversationStore.transaction` 第 147–166 行把任务、状态与恢复增量同事务写入，`event` 分配会话递增序号 | 服务检查通过 |
| 保存成功后才确认收到 | `ConversationSync.consume` 第 139–166 行先合并检查点，原子保存内容／游标／检查点；失败回滚，成功后才安排 ACK | 代码路径核对，原生持久化／游标合同通过；未注入真实磁盘故障 |
| 最新状态不只依赖后台完整快照 | 事件页含 `recovery_page` 的有版本增量，`ConversationCheckpoint.merge` 拒绝缺失基版本或游标不一致；`ConversationProcessor.persist` 同次保存 | 后台快照未刷新时追平、32 版增量超窗回完整状态通过 |
| 重放不重复显示或执行 | 固定回答 ID、顺序／版本守卫；重复序号跳过、缺号拒绝；恢复已有事实不授予新保存权限 | 重复／乱序／缺号、停止／归档／跨会话隔离、恢复不调用模型的受控检查通过 |
| 执行丢失不伪装完成 | `ConversationHarness.recover` 保留未完成正文，标为 interrupted 并暂停；只等待用户明确重试，未开始消息仍按已有规则 | 服务中断受控检查通过，未杀真实 App／模型进程 |

## 实际结果与边界

- [服务检查](service-tests.log)：exit 0，43 passed、4 subtests passed，保留五条旧 FastAPI warning。运行既有四文件：`test_conversation_http`、`test_checkpoint_delta`、`test_response_stream`、`test_commit_recovery`，没有新增产品代码或测试用例。
- [两组原生合同](native-contracts.log)：`ConversationReplayTests` 和 `ConversationControlTests` exit 0；同批独立回环 HTTP 的真实 SSE 传输、Unicode 与批量恢复增量合并通过。使用现有源码编译、受控事件与 SwiftData 内存容器；重开 ModelContext 不等于关闭重开真实 App。编译原有 warning 保留，没有修订其他模块。
- 上一批 TOOL-01 的真实 SwiftData 到 HTTP 保存恢复链仍按[原证据](../2026-10-12-save-recovery/README.md)解释，本次不重复归属为新的验证。

这一小点暂未复现需要修改生产逻辑的缺口；保留现有机制，仅更新研究、状态和规格中的增量恢复说明。全部供应商调用、日常知识卡写入和日常服务重启均为零；不宣称任意崩溃窗口、实际磁盘写入失败、完整模型到 UI 的断线／关闭重开链已经验收。检查范围与源码哈希见 [review.json](review.json)，测试日志仅去掉行尾空白，原文件副本与哈希另存。

下一位置为第 5 条第二小点：运行中追加输入的接收、实际消费与停止／排队边界。尚未逐项检查或授权新增实现；此前已确认的控制与队列规则保留。
