# 分层重试与整轮上限（2026-10-13，只读检查／分项通过）

基线 `e529b7e8b7772442150a31d79d52301e1e7c3460`。本轮只检查 ZCode 第 6 条第一小点，记录现有边界和实际执行，不调整次数、时间、供应商、模型或任何产品规则。

固定版 [ZCode retry-policy.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/adapters/src/model/retry-policy.ts)第 12–26 行默认十次重试，加首次请求为十一尝试。这是适配层单次模型请求的策略，不代表整个 Agent 任务的请求总上限；本次不运行 ZCode，也不采用其次数。[用量记录](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/usage-observability.ts)另分模型请求与整轮统计，下一小点再核对对应记录的可信性。

## 既有规则与代码对照

现有意图在 [Harness §18.2](../../agent-harness-v2.md)、[有限恢复](../../agent-harness-v2.md#bounded-recovery-contract)与决策 222 维护。已存在的整轮限制是首次进入执行后默认 180 秒、12 次模型请求准入、累计估算输入 512,000 tokens；补充不重置，显式重试／恢复开启新预算段并保留账本。不是长期学习目标的累计十二次上限，也不是金额硬上限。

| 边界 | 实际代码 | 本轮结果 |
|---|---|---|
| 单步骤共享有限尝试 | [execution_policy](../../../agent-service/agent_service/execution_policy.py)第 12–14、65–85 行：默认最多两次，嵌套调用复用同一预算 | 既有预算／嵌套合同通过 |
| 接口重发和格式修复不会各多得两次 | [openai_client](../../../agent-service/agent_service/openai_client.py)第 22 行关闭 SDK 隐式重试，实际发送前 `take`；[conversation_model_call](../../../agent-service/agent_service/conversation_model_call.py)第 121–215 行的重发及一次格式修复共享步骤预算 | 两次端点请求后发生字段问题，不再发送第三次；实际 DeepSeek 格式修复两次通过 |
| 多步骤共用整轮准入 | [run_accounting](../../../agent-service/agent_service/run_accounting.py)第 7–79 行：每次预约检查总次数、累计输入与时间；同逻辑步骤第二次端点请求再次记入次数和输入 | 三种耗尽合同、备用端点计量及整轮不足时阻止格式修复通过 |
| 补充不重置、明确重试可新开一段 | [补充入口](../../../agent-service/agent_service/conversation.py)第 121–134 行保留现有预算；[控制入口](../../../agent-service/agent_service/conversation_controls.py)第 66–80 行仅明确恢复才清除当前预算段 | 预置十二次已用完后补充，预算 ID、起点及次数均保留，暂停且模型调用零；明确重试新开一段并保留旧账本 |
| 达到上限或中断后不自行恢复生成 | [会话执行](../../../agent-service/agent_service/conversation.py)第 416–476 行记录失败并暂停；第 320–332 行的服务恢复保留中断，等待明确操作 | 既有失败、停止、崩溃恢复与流式合同分项通过 |
| 首段／空闲时限与整轮时限分开 | 流式首段默认 90 秒、有效文字空闲 30 秒；持续输出可经过单步旧时限，但不会延长整轮 180 秒 | 既有受控时钟及 watchdog 合同通过 |

知识卡的语义修复是另一个已有节点，仍只修一次；会话保存入口通过同一 `_call`，计入整轮限制。本轮未把结构正确或次数受控等同于语义正确。

## 实际检查

- [首次运行](tests-initial.log)：默认日常 DeepSeek 配置下，19 passed、4 failed、42 deselected。四个旧兼容端点夹具只模拟 `responses.parse`，实际分支使用 `responses.create`，因此报 Mock 不可迭代；属于夹具缺少供应商隔离。没有改生产配置，也没有抹掉失败。
- [兼容分支](tests-compatible.log)：仅测试进程指定 `REVIEW_TODAY_LLM_PROVIDER=openai_compatible`，原四文件同一筛选 23 passed、42 deselected；五条既有弃用 warning 保留。检查预算、网络与格式失败、首段／空闲期限、停止／补充和受控崩溃恢复。
- [DeepSeek 分支](tests-deepseek.log)：仅测试进程指定 `REVIEW_TODAY_LLM_PROVIDER=deepseek`，13 passed、2 subtests；使用既有供应商合同，没有真实请求。
- [叠加场景脚本](probe.py)与[结果](probe-final.json)：实际会话执行和模型客户端，SDK I/O 使用替身、SQLite 临时隔离。四组通过：兼容端点重发两次后不再格式修复；DeepSeek 一次格式修复成功；整轮仅余一次时阻止第二次格式请求；预置预算已耗尽时补充不重置，明确重试保留总账。最后一组是预置耗尽状态，未实际发十二次供应商请求。
- [首次脚本说明](probe-initial.txt)：构造的作答场景漏掉当前检查题，未触发目标字段守卫，断言失败；补齐合成题目上下文后四组通过，仅调整验证夹具。

结论：限定范围内暂未复现层叠重试绕过整轮上限的生产缺口，保留现有次数和期限，不新增实现。普通默认跑法中的四项夹具环境问题仍未改；分支隔离通过不等于这个测试维护问题已解决。

没有真实供应商调用、日常数据写入、服务重启、App 更新或新原生验收。180 秒约束本地执行与请求准入，不能保证上游请求立即停止计费；后台摘要和能力探测使用独立范围，不受前台十二次上限直接概括。费用、缺失及迟到用量留到下一小点检查。当前源文件、配置文件摘要、失败记录与日志原本信息见 [review.json](review.json)。

复现：在 `agent-service` 下按日志中的供应商分支分别运行四文件预算筛选及 `tests/test_deepseek_provider.py`；叠加脚本使用 `PYTHONPATH=. ./.venv/bin/python ../docs/evidence/2026-10-13-retry-budget-inspection/probe.py`，脚本在内部限定两种替身分支，不联网。

下一位置：第 6 条第二小点，真实用量、缺失和迟到账本先检查再对齐；不得由本批结果推出供应商稳定、金额硬上限或新的费用产品已授权。
