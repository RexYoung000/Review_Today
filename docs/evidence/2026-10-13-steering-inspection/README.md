# 补充输入消费与旧轮状态（2026-10-13，STEER-01 已修复／分项通过／已更新本机）

基线 `de01a5c9d688a7b0aff769921138afa2fb8c3798`。Rex 已明确确认决策 228 的最小修复；契约先更新至 [Harness](../../agent-harness-v2.md#steering-acceptance-contract)、[DESIGN](../../../DESIGN.md)和[工作状态](../../work-status.md#steer-01)，再实施。

固定版 [ZCode events.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/events.ts)第 299–398 行集中记录补充／排队输入的进入、交付变化和取消／丢弃；从队列拿走的 promoted 输入不能被误记为取消，提升另由实际持久化处理。参考的是收到、归属和消费分开记录，不采用其重启丢弃引导输入规则。未运行 ZCode；本轮 GitHub 目录／树接口读取受限，改为核对已知官方固定版事件文件，没有尝试绕过限制。

## 原生基线复现

[AcceptanceProbe.swift](AcceptanceProbe.swift)使用上一批冻结源码编译的原生合同模块与 SwiftData 内存容器，运行实际 `recordAcceptance` 和 `persist`。受控条件为旧回复在服务端已完成、本地暂未知，用户补充触发临时 adjusting，服务将补充接收到新 Run。

[native-baseline.json](native-baseline.json)：补充确实绑定新 Run 并正常完成；重复投影后旧 Run 仍 adjusting，旧回答仍 interrupted／首段，本地有一个错误活动轮。知识卡和复习写入零。这里只证明受控原生路径，不是日常会话或真实供应商现场。

定位：[LearningWorkspace](../../../Review_Today/LearningWorkspace.swift)在保存补充时先冻结旧轮；[ConversationProcessor.recordAcceptance](../../../Review_Today/ConversationProcessor.swift)只清理返回 Run 的 adjusting；`persist` 又按所有 adjusting 持续冻结旧轮，服务返回新 Run 时旧标记无法解除。

## 服务基础检查

[service-tests.log](service-tests.log)：既有立即补充／排队／停止子集 12 passed，67 deselected，五条旧 warning；无真实模型调用。另用 [service_probe.py](service_probe.py)追踪实际回答输入，[最终结果](service-probe-final.json)三组通过：两条连续补充进入替换后的请求，排队不混入当前请求、之后单独执行，停止保持队列暂停且无迟到旧回答。这是实际编排与请求装配、替身输出的验证，不是供应商语义质量验证。

首轮追踪夹具在上游返回后过早清理临时 SQLite，仍有脱离的传输线程写账，导致临时目录清理失败；属于验证夹具生命周期，未据此改动生产实现。需要等待本场景所有传输退出后再清理，修正后单独记录最终结果。

## 已确认实现范围

未被服务接收的立即补充仍保持原临时冻结；接收后以服务完成状态投影。等待回执时已消费但未显示的旧完成正文，只凭可靠同会话、同生命周期、当前版本且稳定消息 ID 匹配的完成记录补齐；用户停止、归档、旧版本和失效引用不得恢复。立即补充、排队、停止、模型预算、评分和知识保存权限均不扩大。

## 实际实现与分层结果

生产修改只在 `ConversationProcessor.persist` 及其局部补齐函数：临时冻结只在会话仍有本地待接收立即补充时生效；解除后优先投影真实服务记录。被临时冻结且已消费完成事件的旧消息，只对稳定现有行补齐，不创建第二份回答或推断新授权。没有新模型、数据字段、控件、动画或服务调度。

- [10 个新增原生场景](../../../tests/mac/ConversationSteeringTests.swift)和[最终原生检查](native-tests-final.log)：接收与完成的两种顺序、重复回放、仍待接收的连续补充、停止、归档、版本、消息身份、失效引用和生命周期；原回放／控制合同、受控回环 HTTP SSE 同批通过。新增用例已进入默认原生检查入口。
- [同场景修复后结果](native-fixed.json)：两轮 completed，旧完整正文与新回复正确，错误活动轮从 1 到 0、知识和复习零；基线 JSON 未替换。
- [真实窗口包装](NativeSteeringQA.swift)、[启动信息](qa-launch.json)、[实际状态](native-window-state.json)：真实生产 LearningWorkspace 与投影、合成消息和内存容器，preview 模式不联网。通过 UI 操作模拟接收及服务同步，实际看到旧完整正文、新回复，残留 adjusting／中断提示消失；截图在本轮 CUA 观察中显示，未另导出图片文件。QA 已关闭。未成功输入验收草稿，因此不把草稿／输入焦点保留写为通过。
- [Debug 构建](build.log)：最终 `BUILD SUCCEEDED`，既有 Apple Development 签名保留，候选与安装包严格签名验证通过。未做 Release 构建或发布。
- [本机更新](local-install.json)：旧 App 和完整 Application Support 已独立备份，三库用 SQLite Backup API 保存一致性副本，更新前后全表计数／内容摘要相同、完整性 ok。日常 App 与 8742 服务未运行，未在日常库制造故障或写入新卡；下次打开使用本轮开发版。

初次原生检查包装把可抛出的读取放入 `precondition`，导致新增测试编译失败，保留 [原日志](native-tests.log)；修正调用后最终通过。QA 包装首次把 Dictionary 的 `values` 属性误写成方法，修正后编译和窗口操作通过。初次生产补丁上下文名称不匹配时整批未应用，更正后实施；这些是验证／编辑方法错误，不记为生产验证通过。服务夹具生命周期问题见上方。

没有真实模型到原生的连续补充完整链、断线重开链、完整 VoiceOver 或输入焦点／草稿验收；本轮分项结果不关闭这些项目或 Rex 最终体验。代码与签名构建冻结，源码、无关工程改动和原始日志副本信息见 [review.json](review.json)；日志仅清理行尾空白与末尾空行，JSON 结果保持原样。

体验入口：重开日常 Review Today → Agent 会话，在回复进行时补充一句要求；如果旧回复已先结束，新补充应正常另起一轮，旧完整回答保持可见，不持续显示“正在调整”。排队／停止继续走原规则。下一研究位置是第 6 条第一小点分层重试与整轮总上限，尚未对齐。
