# ZCode Agent 源码研究与参考清单

研究来源：[智谱 ZCode 官方仓库](https://github.com/zai-org/ZCode)。本轮分析固定在提交 [`29628c9acdb81b703bbd4080c207a0e7ce5e276e`](https://github.com/zai-org/ZCode/tree/29628c9acdb81b703bbd4080c207a0e7ce5e276e)，对应公开源码 v3.14.3；不宣称与之后的桌面发行版完全一致。

研究发生于 2026-10-03，后续讨论与问题定位见[工作记录](../work-status.md)。这是参考资料，不是第二份 Review Today 主规格。已确认采用的产品规则回到 [DESIGN](../../DESIGN.md#knowledge-save-invitation)和 [Harness](../agent-harness-v2.md#knowledge-save-invitation-contract)。

## 结论与验证边界

ZCode 的参考价值在于把模型判断、工具执行、结果回传、停止／继续和恢复放进明确流程。Review Today 已有自己的运行框架、上下文、来源缓存和本机保存回执；应基于实际学习失败补齐检查，不直接搬入整套通用编码 Agent。

本轮主要是固定版本的源码追踪，没有安装依赖、运行 ZCode 桌面端、调用其模型或跑完整测试。有限离线检查包括：默认重试策略的次数计算、抽取原 `countWords` 函数对中文做最小验证，以及形式化行为模型六个场景的两层枚举。前两项未运行完整重试或记忆提取流程；这些检查不能证明整体运行可靠或真实教学有效。

<a id="research-map"></a>
## 研究覆盖与逐条讨论位置

| 条目 | 源码中看到的做法 | Review Today 的参考方向 | 本轮状态 |
|---|---|---|---|
| 1. 根据结果决定下一步 | 模型判断、工具执行、结果回传后继续或停止；轮次结束与持续目标完成分开 | 区分回答完成、等待用户、理解验证和知识保存；每次推进有对应依据 | 已逐条讨论；新增知识提示已确认，尚未实施 |
| 2. 长对话与上下文 | 区分输入组成、工具结果压缩、会话摘要、压缩后恢复 | 先看每类内容占多少，再保留与当前问题相关的证据 | 已研究；下一条待讲 |
| 3. 工具执行与取消 | 验证、权限、执行、结果记录及恢复分层 | 分清未执行、执行失败、结果未知；保存失败不能直接假设没有写入 | 已研究，尚未逐条对齐 |
| 4. Skills、子任务与工作流 | 按需加载指令，隔离子任务上下文，显式任务结果 | 仅在有独立子任务需求时考虑；先改善单条教学链路 | 已研究，未批准引入 |
| 5. 事件、恢复与用户补充 | 有序事件、选定持久化记录、恢复与引导输入 | 区分收到、执行、显示、可靠保存；恢复不重复副作用 | 已研究，尚未逐条对齐 |
| 6. 模型重试与预算 | 自管重试、流恢复、上下文与目标预算分层 | 分清用量观测、恢复次数与整任务费用；不照搬无上限恢复 | 已研究，尚未逐条对齐 |
| 7. 记忆、完成检查与评测 | 项目记忆、目标核验、行为状态枚举 | 记忆可追溯，核验失败不能冒充成功，连续教学要独立验收 | 已研究，尚未逐条对齐 |

<a id="topic-1"></a>
## 第 1 条：根据结果决定下一步

基本流程：接收请求 → 确定当前目标与上下文 → 模型判断 → 执行 → 读取实际结果 → 继续、等待或结束。

放到学习场景，应区分四种事实：

| 事实 | 能说明什么 | 不能直接推导什么 |
|---|---|---|
| Agent 解释完 | 这轮回答结束 | 用户已经理解 |
| 用户要求继续／跳过 | 用户希望推进 | 上一节已经掌握 |
| 有效独立作答通过 | 对应题目覆盖的知识点有理解证据 | 整节／整门课程全部通过 |
| Mac 返回保存成功 | 对应知识卡已可靠写入 | 该知识已掌握或自动加入正式复习 |

没有知识卡时，教学依靠当前讲解、问题、作答和学习记录继续。知识卡是之后的整理成果，不能成为教学开始或继续的前提。旧卡可作为参考，但不是本次新生成的成果。

本轮实际问题显示：仅保证状态格式合法和存在保存回执还不够，必须保证回答始终对准用户所问的学习内容。模型选中的最近主题被过滤后，程序不能悄悄改答更旧的主题。见 [KT-02](../work-status.md#kt-02)。

Rex 进一步确认了可见的保存时机：知识点首次通过有效检查后出现对话内“新增知识”提示，点击才生成与保存，可稍后、不阻断学习。见 [KT-01](../work-status.md#kt-01)。这是针对 Review Today 的产品决定，不是 ZCode 自带的教学能力。

源码入口：[主循环](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/turn-loop.ts)、[停止条件](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/turn-stop.ts)、[持续目标](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/target.ts)。

<a id="topic-2"></a>
## 第 2 条：长对话怎样保留重要信息（下次从这里讲）

已查清的机制：

- 系统指令、工具、历史消息与按需技能分开构建，并记录上下文组成与估算口径。
- 工具返回太长时，部分工具按配置保存完整结果，只给模型预览和路径；另一些仍直接截断，不能概括为所有结果都完整保留。
- 微压缩可清理旧工具输出，但需要配置启用；自动会话摘要是另一条机制。
- 自动／响应式压缩在有足够轮组时保留最近完整问答组，手动压缩不采用同样的保留策略；压缩后恢复计划和部分近期文件。重要含义是否保留仍需检验，源码不能证明语义永不丢失。

Review Today 已有上下文预算、整组问答摘要与独立学习状态。下一步应讨论是否先补“输入由哪些内容组成”的观测，再验证当前问题相关选段；不是重新建设整套摘要系统。公开来源现有首部选段限制是否造成实际漏证据，需要独立样本验证，尚未认定为真实产品缺陷。

源码入口：[上下文构建](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/context/builder.ts)、[组成统计](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/helpers/context-usage-breakdown.ts)、[压缩选择](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/helpers/compact-selection.ts)、[工具结果处理](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/tool/executor/result-serialization.ts)。

## 其余研究结论备查

| 主题 | 可参考的机制 | 必须保留的边界 | 固定版本源码 |
|---|---|---|---|
| 工具调用 | 结构校验、审批、执行、输出校验、事件记录统一编排 | 外部写入成功后，结果记录仍可能失败；取消等待不等于外部动作回滚 | [call-runner](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/tool/executor/call-runner.ts) |
| 并发与子任务 | 工具元数据参与调度；子任务独立上下文与身份 | 不等于按业务对象加锁；Explore 保留 Bash，源码说明只读语义靠提示约束 | [scheduler](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/tool/scheduler.ts)、[Explore 工具](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/subagent/explore-tools.ts) |
| 技能与工作流 | 技能按需读取，工作流有结构结果与有限修复 | 工具启用依宿主／配置；控制子进程不等于完整 OS 沙箱 | [Skill](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/tool/handlers/skill.ts)、[工作流提交](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/dynamic-workflow/src/engine/scheduler-submit.ts) |
| 恢复 | 已知工具结果与执行未知状态分开恢复 | 默认事件存储含内存层，只有部分事件落盘；重启不保留所有待处理引导输入 | [events](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/events.ts)、[resume](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/resume.ts) |
| 模型与预算 | 统一模型接口、自管重试与用量观测 | 适配层默认 11 次尝试不是整个任务的请求上限；部分工作流重试无上限；目标预算轮后结算不等于金额硬上限 | [retry-policy](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/adapters/src/model/retry-policy.ts)、[usage](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/usage-observability.ts) |
| 项目记忆 | Markdown 索引与受限记忆维护 | 按空白计词使连续中文可能不达提取门槛；可参考事实不应被提升为指令 | [extraction](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/memory/extraction.ts) |
| 目标核验与形式模型 | 区分轮次与目标，枚举产品状态 | 核验异常存在按通过处理的路径，不能照搬到掌握／保存判断；状态枚举不等于真实运行已证明正确 | [核验契约](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/contracts/src/tools/target.ts)、[形式模型](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/packages/formal-proof/src/model.ts) |

本轮未建议整体引入子 Agent、自动后台记忆或通用工作流。独立教学质量用例、上下文观测、问题相关选段只是后续研究建议，尚未成为已批准实现项。第一方源码采用 Apache-2.0；如未来采用代码，还须逐项核对第三方声明，不以主仓库许可覆盖全部依赖。
