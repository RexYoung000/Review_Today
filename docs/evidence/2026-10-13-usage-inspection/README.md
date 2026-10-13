# 用量重复与后续补全（2026-10-13，已修复／分项验证通过）

基线 `f6c639118c7dfff5781db2a7f36e19c04945457f`，初次只读记录提交 `b36f6f4`。Rex 对具体最小范围明确选择「按这个范围修复（推荐）」，见决策 229；先更新 Harness 契约，再修复两个服务文件的记账。模型配置、预算和界面维持现状。

固定版 [ZCode usage-observability.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/usage-observability.ts)在前一轮已读取，按逻辑请求身份、尝试序号和结果状态记录用量，另统计网络重试。可参考的是身份、尝试与状态分开；该层记录不证明每个底层请求都返回了可计费用量。本轮刷新网页返回 HTTP 403，没有绕过限制或追加上游结论，也未运行 ZCode。

## 既有意图与两个已复现原因

[Harness §18.2](../../agent-harness-v2.md)要求保存实际 usage，缺失标未知、部分回报不充当全量、停止后的迟到用量可以补账，ACK／恢复不丢失或重复累加，不用上下文估算补账单。

[run_accounting.record](../../../agent-service/agent_service/run_accounting.py)第 95–99 行只按供应商 `response_id` 去重：没有 ID 一律追加；相同 ID 一律丢掉后续记录，没有合并缺失字段。由此受控复现：

1. **同一次真实请求重复回报、没有供应商 ID：** 实际模型客户端只调用一次 SDK 发送，回放两条相同 completed 回执，账本却留下两条 `input=100 / output=20`，把已回报输入相加得到 200。这里是账目重复，不代表供应商实际扣费两次。
2. **先回报部分用量、后回报完整用量、同一个 ID：** 初次仅 input=100，后来补 output=20／total=120，最终账本仍保留 output=null。实际客户端流式回执和独立记账入口均复现，后续字段被去重条件丢掉。

另观察到 `usage_state=reported` 仅依据回执数量，即使核心字段仍为空；字段本身仍为 null，未被补成零。这个状态不能直接当作完整输入／输出已知的证明，也不能据此声称用户已看到错误费用。缺失全部用量时仍为 unavailable，供应商明确回报的零则正确保留。

## 修复前检查结果与边界

- [服务子集](service-tests.log)：五项既有测试通过，覆盖无 usage／无效输出前记账、已标识回执去重、ACK 保留、删除不复活、备用端点计量、补充／停止后的迟到回报；五条旧弃用 warning 保留。
- [复现脚本](probe.py)和[基线 JSON](baseline.json)：十个受控场景，六个既有边界正常，四个缺口相关观察对应上述两个原因及状态标记。脚本 exit 0 表示基线观察符合断言，**不表示缺口已修复**。
- 正常边界还包括真实回报为零、两次请求只有一份 usage 为 partial、停止后补账不恢复回复，以及 ACK／有版本恢复增量保留账目。两次实际端点请求恰好回报相同匿名数字时，仍应记两笔；修复不能仅按内容相等去重。
- 使用实际会话执行、模型客户端和 SQLite 事务，SDK I/O 与回应均为替身，临时数据库独立。没有真实供应商调用或费用核账，也不是实际供应商事故的证据；没有新原生构建或 UI 验收。

## 已确认的最小修复范围

每次实际请求有稳定的本地记账身份，重复回报只记一次；后续补全更新原账目，缺失字段继续明确未知／部分，供应商明确零不变。保护两笔真实请求即使数字相同也分别记账，保留停止后的迟到补账、删除守卫和 ACK／恢复。沿用现有总账、预算、供应商、模型与界面，不新增价格表、费用面板或重试。

Rex 已明确确认这一范围。契约见 [Harness](../../agent-harness-v2.md#usage-receipt-contract)，实施、验证和未覆盖边界见下。旧 [baseline.json](baseline.json)、[service-tests.log](service-tests.log)与[基线核对](review.json)保留原内容，不以修复结果替换。

## 实际实现和修复验证

生产改动仅 [run_accounting.py](../../../agent-service/agent_service/run_accounting.py)与[模型客户端](../../../agent-service/agent_service/openai_client.py)：实际请求准入同事务生成／保存本地 request_id，调用者沿用这个 ID 回传 usage；旧的 void 请求回调仍可使用。按本地请求身份更新同一账目，后续已知值补全／更新而空值不抹掉旧值。唯一实际请求可给旧回报确定归属，匿名多请求旧记录不按数字猜测；真实输入／输出缺失标部分，全缺标未知，明确零保留，选填明细仍各自可未知。没有新增模型、请求次数、价格表、界面或数据库表迁移。

- [新增 16 个行为场景](../../../agent-service/tests/test_usage_receipts.py)：重复匿名回报、字段补全／空值不擦除、供应商重用 ID、真实相同数字的两笔请求、缺失与零、可选明细、已知值更正、迟到顺序、旧账本、停止／ACK／恢复；实际 SDK 发送路径为替身 I/O。
- [定向检查](repair-focused.log)：197 passed／19 subtests，包含初次直接导入的既有 unittest 夹具被 pytest 再收集；在全量前改为模块别名，避免重复收集，不将这部分计为新增测试。
- [最终完整服务](repair-full.log)：测试进程限定兼容分支，1170 passed／4 原 opt-in skipped／521 subtests，五条既有 warning。上一批默认日常配置下的四项旧兼容端点夹具隔离问题未在本次修复，也不由该完整分支通过关闭。
- [DeepSeek 专项](repair-deepseek.log)：日常供应商分支下新记账与供应商合同 29 passed／2 subtests，没有真实模型调用。
- [原生回放／控制与受控 SSE](native-contracts.log)：既有两个合同、Unicode 流和批量恢复增量合并通过；不是新费用 UI 或真实供应商到原生完整链验收。
- [同场景修复后回放](fixed.json)：十个场景，匿名重复回执从两笔到一笔，完整输出字段从 null 补为 20，缺失核心字段为 partial，两个真实请求仍两笔；原基线不变。

复测入口：在 `agent-service` 下运行 `PYTHONPATH=. ./.venv/bin/python ../docs/evidence/2026-10-13-usage-inspection/probe.py --expect-fixed`；默认模式用于原基线源码，不用当前修复后的源码冒充旧行为。新增场景已由默认 pytest 全量入口覆盖。

原生界面、供应商配置及无关工程改动未改。本机 8742 未监听，未启动日常服务或重新安装 App；已核对 App 启动器从当前工程加载服务源码，下次打开后启动新版服务。没有真实供应商费用核账、历史账单回填或原生费用展示验收；本地停止仍不保证上游撤销计费。当前冻结源码、配置、原基线完整性和日志原本见 [修复核对](repair-review.json)。下一研究位置：第 6 条第三小点，前台回答之外的后台摘要／能力探测的预算和用量边界，先检查再对齐。
