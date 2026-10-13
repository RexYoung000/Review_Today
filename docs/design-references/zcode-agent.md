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
| 1. 根据结果决定下一步 | 模型判断、工具执行、结果回传后继续或停止；轮次结束与持续目标完成分开 | 区分回答完成、等待用户、理解验证和知识保存；每次推进有对应依据 | 已逐条讨论；[KT-01](../work-status.md#kt-01) 已实现并分层自测，Rex 原生体验仍开放 |
| 2. 长对话与上下文 | 区分输入组成、工具结果压缩、会话摘要、压缩后恢复 | 先看每类内容占多少，再保留与当前问题相关的证据 | [CTX-01](../work-status.md#ctx-01) 公开选段已实现并分项验证，待本机重开体验；其他机制未授权实施 |
| 3. 工具执行与取消 | 验证、权限、执行、结果记录及恢复分层 | 分清未执行、执行失败、结果未知；保存失败不能直接假设没有写入 | 三小点已确认，Rex 已授权最小恢复修复；原生磁盘与受控 HTTP 故障链已通过，最终回归与本机交付见 [TOOL-01](../work-status.md#tool-01) |
| 4. Skills、子任务与工作流 | 按需加载指令，隔离子任务上下文，显式任务结果 | 场景细则按需加载；子任务仅在有独立需求时考虑 | 第一小点已实现并完成分项验证，见 [PROMPT-01](../work-status.md#prompt-01)；第二小点独立职责与输入／结果边界已检查，候选优化待对齐 |
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
## 第 2 条：长对话怎样保留重要信息（2026-10-05，公开选段已实现并分项验证）

已查清的机制：

- 系统指令、工具、历史消息与按需技能分开构建，并记录上下文组成与估算口径。
- 工具返回太长时，部分工具按配置保存完整结果，只给模型预览和路径；另一些仍直接截断，不能概括为所有结果都完整保留。
- 微压缩可清理旧工具输出，但需要配置启用；自动会话摘要是另一条机制。
- 自动／响应式压缩在有足够轮组时保留最近完整问答组，手动压缩不采用同样的保留策略；压缩后恢复计划和部分近期文件。重要含义是否保留仍需检验，源码不能证明语义永不丢失。

Review Today 已有上下文预算、整组问答摘要与独立学习状态。2026-10-05 已先做隔离输入体检：继续追问、刚纠正和切换主题三个请求装配场景正常；未发现最新纠正被旧摘要覆盖。另已复现公开来源首部截取使正文尾部相关事实未进入回答输入的缺口。该结果验证的是输入选择，尚不能据此断言实际模型答错或优化后的回答质量通过。

本轮采用方向是：公开来源在既有预算内按问题做本地词项相关选段，保留可回查原文，核验和回答共用，输入不变的重试／恢复复用；不增加模型调用或重建摘要系统。选段实现、重试漂移修复与最终受控回归已完成；单组合成资料中，两个真实模型节点共用正文尾部窗口并正确回答两项条件。该方法不是语义检索，不保证同义词／跨语言匹配，简洁度和完整原生链路未据此验收，本机重开体验仍待确认。

详细契约只在 [Harness 公开来源选段](../agent-harness-v2.md#public-evidence-selection)维护，实证见[选段证据](../evidence/2026-10-05-source-selection/README.md)，当前结果和续接见 [CTX-01](../work-status.md#ctx-01)。第 2 条其他机制未授权实施；第 3 条仅后述最小恢复修复获准，不扩大到整个工具框架。

源码入口：[上下文构建](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/context/builder.ts)、[组成统计](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/helpers/context-usage-breakdown.ts)、[压缩选择](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/helpers/compact-selection.ts)、[工具结果处理](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/tool/executor/result-serialization.ts)。

<a id="topic-3"></a>
## 第 3 条：工具执行与取消（2026-10-12，逐项对齐中）

前三小点已确认：停止保留已保存知识；同一内容重试只补仍未完成的部分；本轮内有限自动恢复，最终失败后由用户明确重试，主动停止优先。规则分别回到 Harness 的[停止边界](../agent-harness-v2.md#stop-knowledge-contract)、[重试范围](../agent-harness-v2.md#knowledge-retry-contract)与[自动恢复边界](../agent-harness-v2.md#bounded-recovery-contract)，确认见决策 220–222；Rex 回复「开始」后，223 授权最小恢复修复。已实现持久化回执直补、失效未落盘领取释放与同版本显式重试复用，并完成原生磁盘与受控 HTTP 故障验证；分项及交付状态见 [TOOL-01](../work-status.md#tool-01)，不宣称整个工具主题或 Rex 体验已完成。

<a id="topic-4"></a>
## 第 4 条：Skills、子任务与工作流（2026-10-13，第二小点检查与讨论）

### 第一小点：场景规则按需加载（已实现／分项验证通过）

先讨论场景规则按需加载。固定版 [Skill 工具](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/tool/handlers/skill.ts)按名称调用 `loadSkill`，将指定技能正文加入会话；工具说明要求依据会话中的可选技能列表选择，再加载指定正文。这是局部源码核对，没有运行 ZCode。

检查时，Review Today 已将意图、讲解、评价及知识整理分开；普通问答和分步教学选择不同输出结构，但仍使用同一份 `COACH_SYSTEM`，含教学计划、检查题与场景细则。Rex 随后回复「开始」，授权在现有流程中保留公共约束，按本轮任务加载相应场景细则，见决策 224 与 [PROMPT-01](../work-status.md#prompt-01)。契约在 [Harness](../agent-harness-v2.md#coach-rule-loading)维护；不引入新 Skill 框架或子 Agent，不从全量规则的存在直接推断模型必然答错，也不承诺拆分后质量提升。

本轮已实现四类规则选择，评分与知识邀请附加规则正确叠加；完整服务回归通过，真实组件样本与开放的检查范围疑点见 [本批证据](../evidence/2026-10-12-coach-rule-loading/README.md)。下一次从本条其余小点逐项对齐，不能把首点交付写成 Skills／子任务／工作流整体完成。

<a id="topic-4-2"></a>
### 第二小点：独立任务只完成自己的检查，主流程决定后续（评估方向已确认／落地方案待对齐）

2026-10-13 继续核对固定版 [子任务 runner](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/subagent/runner.ts)：每个子任务有独立 `childSessionId`，运行请求带任务说明、prompt、profile、允许工具，结果返回 response／事件，并保留父工具调用关联。可参考的是局部职责、明确输入与结果回传；这里没有证明所有子任务只收到最少上下文或拥有独立文件沙箱。[Explore 工具](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/subagent/explore-tools.ts)仍允许 Bash，不能据“只读”提示推断强权限隔离。本次没有运行 ZCode 或引入子 Agent。

Review Today 已有分工基础：讲解、作答评价、卡片核验分别处理；隔离实验的[题目复核](../../agent-service/agent_service/judgment_quality.py)只接收题目、标准和参考，不接收用户答案或 Jev 判定。该实验不能表述为日常已经对每道题执行独立复核。保存和学习状态仍通过主流程及现有授权守卫处理。

**具体缺口：** [教学结构检查](../../agent-service/agent_service/schemas.py)与[检查范围绑定](../../agent-service/agent_service/learning_progress.py)校验步骤标题、概念和逐字依据；有有效完成条件时，`scope=step` 不会因缺少“完整覆盖条件”的独立语义证明而自动收窄。既有题目复核只检查题目／评分标准与参考，其输入没有 `check_binding.scope` 和该步 `completion_condition`；日常在作答评价时仍要求模型独立判断能否证明整步，不能从本缺口推断实际已经误记掌握。

内存回放上一批真实教学对象，经原 `TeachingConversationOutput.validate_request` → `set_plan` → `bind_check`，仍接受 `scope=step`；题目只问“RAG 引入外部资料主要解决哪类问题，有什么限制”，完成条件还包含训练时间边界、私有资料缺失、可能编造三个限制。这里只证明程序保留标记且没有出题前独立覆盖证明；当前理解仍 unknown，未调用模型、评价用户作答、访问数据库或更改知识卡。

**候选建议：** 先明确现有核验环节的输入／输出职责，再核对“本题实际能验证哪些知识点、是否完整覆盖本步条件”。检查只回传结论、缺失依据与不确定项，主流程按既有边界决定范围与进度；不让整理或检查结果自行授权保存。优先评估复用既有环节；若需新增模型调用，其适用范围、预算与耗时另行对齐。该建议尚未获实施授权，不新增日常检查调用、评分规则或子 Agent。当前停留见[工作状态](../work-status.md#cursor)。

**Rex 回复「ok」后的方案评估：** 现成独立题目复核只在隔离实验启用，不能零调用搬入日常。候选为仅在新题声明整步范围时核对题目／讲解／步骤条件，不看用户答案，结果由主流程使用。两次真实合成组件试跑各一次现有 DeepSeek 调用，耗时 1535／1802 ms；原模糊题仍被判 covered，最小答案被核验器从讲义补齐三个额外限制；明确逐项要求三项限制的对照正确。核验尚不适合接入日常，不能用一次对照成功代替原反例通过。证据见 [方案试跑](../evidence/2026-10-13-scope-review-planning/README.md)。

当前待对齐：先收紧默认范围（普通小题只记对应知识点，整节由明确综合检查验证），或保持日常流程并继续验证核验器。本轮只确认评估方向与记录试跑，尚未采用任一新规则、增加综合检查入口或修改功能。

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

本轮未建议整体引入子 Agent、自动后台记忆或通用工作流。独立教学质量用例与整套上下文观测仍为后续研究建议；问题相关选段仅上述公开来源范围获准实施，不扩大到其他内容。第一方源码采用 Apache-2.0；如未来采用代码，还须逐项核对第三方声明，不以主仓库许可覆盖全部依赖。
