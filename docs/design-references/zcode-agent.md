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
| 4. Skills、子任务与工作流 | 按需加载指令，隔离子任务上下文，显式任务结果 | 场景细则按需加载；子任务仅在有独立需求时考虑 | 本轮三小点分别落到 [PROMPT-01](../work-status.md#prompt-01)、[SCOPE-01](../work-status.md#scope-01)、[REPAIR-01](../work-status.md#repair-01)，按各自分项证据验收；失败和语义意见误判保留，不新增独立日常调用 |
| 5. 事件、恢复与用户补充 | 有序事件、选定持久化记录、恢复与引导输入 | 区分收到、执行、显示、可靠保存；恢复不重复副作用 | [第一小点](#topic-5-1)现有机制分项通过；[第二小点](#topic-5-2)按确认落地 STEER-01，分项自测与本机更新完成；不是全部事件框架或真实模型完整链验收 |
| 6. 模型重试与预算 | 自管重试、流恢复、上下文与目标预算分层 | 分清用量观测、恢复次数与整任务费用；不照搬无上限恢复 | [第一小点](#topic-6-1)既有机制分项通过；[第二小点](#topic-6-2)按确认完成 USAGE-01；[第三小点](#topic-6-3)按 230 实现 MAINT-01 及分项验证；下一研究项为项目记忆 |
| 7. 记忆、完成检查与评测 | 项目记忆、目标核验、行为状态枚举 | 记忆可追溯，核验失败不能冒充成功，连续教学要独立验收 | [第四小点](#topic-7-4)的 EVAL-02 原失败保持；CHECK-01、VERIFY-01、STATUS-01 各自已修并分项通过；STATUS 同句真实查询与原生磁盘核对通过，原预算 30／30 后停止，完整连续链与 Rex 体验仍未验 |

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
## 第 4 条：Skills、子任务与工作流（2026-10-13，本轮三小点已实现／分项验证）

### 第一小点：场景规则按需加载（已实现／分项验证通过）

先讨论场景规则按需加载。固定版 [Skill 工具](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/tool/handlers/skill.ts)按名称调用 `loadSkill`，将指定技能正文加入会话；工具说明要求依据会话中的可选技能列表选择，再加载指定正文。这是局部源码核对，没有运行 ZCode。

检查时，Review Today 已将意图、讲解、评价及知识整理分开；普通问答和分步教学选择不同输出结构，但仍使用同一份 `COACH_SYSTEM`，含教学计划、检查题与场景细则。Rex 随后回复「开始」，授权在现有流程中保留公共约束，按本轮任务加载相应场景细则，见决策 224 与 [PROMPT-01](../work-status.md#prompt-01)。契约在 [Harness](../agent-harness-v2.md#coach-rule-loading)维护；不引入新 Skill 框架或子 Agent，不从全量规则的存在直接推断模型必然答错，也不承诺拆分后质量提升。

本轮已实现四类规则选择，评分与知识邀请附加规则正确叠加；完整服务回归通过，真实组件样本与开放的检查范围疑点见 [本批证据](../evidence/2026-10-12-coach-rule-loading/README.md)。下一次从本条其余小点逐项对齐，不能把首点交付写成 Skills／子任务／工作流整体完成。

<a id="topic-4-2"></a>
### 第二小点：独立任务只完成自己的检查，主流程决定后续（已选择收紧范围／实现与分项验证）

以下核对与候选段落保留实施前快照，最终采用规则与验证见本节末尾及 SCOPE-01。

2026-10-13 继续核对固定版 [子任务 runner](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/subagent/runner.ts)：每个子任务有独立 `childSessionId`，运行请求带任务说明、prompt、profile、允许工具，结果返回 response／事件，并保留父工具调用关联。可参考的是局部职责、明确输入与结果回传；这里没有证明所有子任务只收到最少上下文或拥有独立文件沙箱。[Explore 工具](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/subagent/explore-tools.ts)仍允许 Bash，不能据“只读”提示推断强权限隔离。本次没有运行 ZCode 或引入子 Agent。

Review Today 已有分工基础：讲解、作答评价、卡片核验分别处理；隔离实验的[题目复核](../../agent-service/agent_service/judgment_quality.py)只接收题目、标准和参考，不接收用户答案或 Jev 判定。该实验不能表述为日常已经对每道题执行独立复核。保存和学习状态仍通过主流程及现有授权守卫处理。

**具体缺口：** [教学结构检查](../../agent-service/agent_service/schemas.py)与[检查范围绑定](../../agent-service/agent_service/learning_progress.py)校验步骤标题、概念和逐字依据；有有效完成条件时，`scope=step` 不会因缺少“完整覆盖条件”的独立语义证明而自动收窄。既有题目复核只检查题目／评分标准与参考，其输入没有 `check_binding.scope` 和该步 `completion_condition`；日常在作答评价时仍要求模型独立判断能否证明整步，不能从本缺口推断实际已经误记掌握。

内存回放上一批真实教学对象，经原 `TeachingConversationOutput.validate_request` → `set_plan` → `bind_check`，仍接受 `scope=step`；题目只问“RAG 引入外部资料主要解决哪类问题，有什么限制”，完成条件还包含训练时间边界、私有资料缺失、可能编造三个限制。这里只证明程序保留标记且没有出题前独立覆盖证明；当前理解仍 unknown，未调用模型、评价用户作答、访问数据库或更改知识卡。

**候选建议：** 先明确现有核验环节的输入／输出职责，再核对“本题实际能验证哪些知识点、是否完整覆盖本步条件”。检查只回传结论、缺失依据与不确定项，主流程按既有边界决定范围与进度；不让整理或检查结果自行授权保存。优先评估复用既有环节；若需新增模型调用，其适用范围、预算与耗时另行对齐。该建议尚未获实施授权，不新增日常检查调用、评分规则或子 Agent。当前停留见[工作状态](../work-status.md#cursor)。

**Rex 回复「ok」后的方案评估：** 现成独立题目复核只在隔离实验启用，不能零调用搬入日常。候选为仅在新题声明整步范围时核对题目／讲解／步骤条件，不看用户答案，结果由主流程使用。两次真实合成组件试跑各一次现有 DeepSeek 调用，耗时 1535／1802 ms；原模糊题仍被判 covered，最小答案被核验器从讲义补齐三个额外限制；明确逐项要求三项限制的对照正确。核验尚不适合接入日常，不能用一次对照成功代替原反例通过。证据见 [方案试跑](../evidence/2026-10-13-scope-review-planning/README.md)。

**已选择与实施：** Rex 明确回复「先收紧默认规则（推荐）」，见决策 226。普通教学／补充题的整步标记在程序侧收为概念；本节综合检查仅由明确当前对话请求触发，题面包含完整已有条件，独立答案逐项给出依据才允许验证该节，不提前保存或阻止继续／跳过。没有复用失败的独立核验器、增加独立日常调用或引入子 Agent。

**实际验证：** 最终完整服务 1146 passed／4 skipped／521 subtests；首次五轮真实固定上下文回放暴露宽松评分及引用失败，续修后同一短答案的小题通过、综合拒绝及完整独立答案仅验证当前节等五轮通过。设置中的讲义复用上一批实际模型输出，后续入口与评分为真实调用；不是完整真实教学到保存链或通用评分质量证明。原生交互结果与后续体验状态见 [SCOPE-01](../work-status.md#scope-01)，各批原始回放与限制见[实施证据](../evidence/2026-10-13-conservative-check-scope/README.md)。本次借鉴的是任务职责与主流程使用结果的边界，这些教学规则是 Review Today 的产品实现，不是 ZCode 自带功能。

<a id="topic-4-3"></a>
### 第三小点：修复收到具体问题，重新校验后才使用结果（已实现／分项验证通过）

固定版 [工作流提交处理](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/dynamic-workflow/src/engine/scheduler-submit.ts)先验证结构；不通过时回传 `violations` 并扣减修复预算，耗尽则失败。字符串载荷单次解析后仍不合格时，回传解析后对象的字段问题，避免反复修错对象。这里借鉴明确失败原因和有限修复，不采用其次数或宽松解析方式，也不把结构正确视为知识含义正确。只核对源码，没有运行 ZCode。

Review Today 已有一次结构修复、一次知识卡语义修复及修后重新核验。具体缺口在 [repair_node](../../agent-service/agent_service/capture/__init__.py)：日常核验把语义、语言和原文依据问题写入 `semantic_issues`，修复提示却只在存在 `quality_runner` 时附上问题列表；日常实验关闭时该回调为 `None`。原文、上一稿和通用整理规则仍在，不能表述为模型完全不知道规则。

三组合成离线流程已复现：正常卡不修复；泛分类被程序拒绝并修复一次，但日常修复输入未收到本次具体问题；相同校验在有回调但回落普通语义核验时会传递问题。两种失败卡都再次被拒，未进入提交。只证明输入差异及失败守卫，未证明真实模型重复犯错或修复成功率。

Rex 明确选择「按这个范围修改（推荐）」，已实施日常也传递本次问题，清单作为待修正数据，保留一次修复及完整重新核验。新增八项检查，完整服务 1154 passed／4 skipped／521 subtests；修改后离线复现及两组真实修复组件检查通过。第二组核验意见错误要求增加可选变体，修后确实多出一题；原输出保留，不能据此称核验意见或全部题目质量通过，也未验证完整真实生成到原生保存链。见决策 227、[Harness 契约](../agent-harness-v2.md#knowledge-repair-feedback)、[REPAIR-01](../work-status.md#repair-01)和 [本批证据](../evidence/2026-10-13-repair-feedback-inspection/README.md)。本轮选定三小点已落地，下一研究位置为第 5 条第一小点，仍按检查后逐项对齐；不代表已采用全部 Skills／子任务／工作流机制，未授权通用工作流、额外子 Agent 或新增日常核验。

<a id="topic-5"></a>
## 第 5 条：事件、恢复与用户补充（2026-10-13，本轮两小点分项通过）

<a id="topic-5-1"></a>
### 第一小点：先可靠保存事实，再按统一顺序回放（现有机制已有／本轮未新增实现）

固定版 [events.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/events.ts)让实时通知使用事件存储分配的顺序号，避免实时和重放出现两套编号；随后对选定业务记录尝试持久化。部分写入失败只记录 warning，不能概括为所有事件可靠落盘。[resume.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/resume.ts)恢复保存的会话事实；本次不运行 ZCode，也不移植其重启丢弃待处理引导输入规则。

Review Today 已有相应基础：服务事实、任务与有版本的恢复增量同事务写入；Mac 先保存正文、游标与检查点再 ACK；重复事件跳过，缺号拒绝，停止／归档与旧版本迟到结果有守卫；恢复不冒充模型完成或新的保存授权。事件页的恢复增量已能在后台完整快照尚未刷新时追平，不能继续把现有实现描述为只依赖后台快照。

本轮既有服务四文件检查 43 passed／4 subtests，两组原生同步合同及独立受控 SSE 传输通过，暂未复现额外生产缺口。不修改生产逻辑、不新增模型调用或扩展恢复产品规则。原生使用受控事件、SwiftData 内存容器与回环 HTTP，并非真实 App 关闭重开、磁盘故障或完整模型链验收；完整边界见[本批证据](../evidence/2026-10-13-event-recovery-inspection/README.md)。本段保留第一小点检查结果，随后第二小点的定位和修复见下。

<a id="topic-5-2"></a>
### 第二小点：输入被接收、实际消费与可见状态分开（STEER-01 已修复／分项通过）

固定版 [events.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/events.ts)集中记录补充／排队输入的进入、交付变化和取消／丢弃，已提升去处理的输入不能误记为取消；实际提升另由持久化路径处理。参考的是明确输入身份和阶段，不搬入其重启丢弃队列规则，也不从账本存在推断全部消费可靠。

Review Today 原本已有默认补充、显式排队和停止暂停队列。12 项既有控制检查及三组受控输入追踪通过：两条连续补充进入替换后的真实请求装配，排队未混入当前请求、之后单独处理，停止保留队列并拦住迟到旧回答。这里模型输出是替身，不是供应商语义质量验证。

实际缺口在原生投影：旧回复服务端已完成、本地仍以为活动，补充获接收至新轮后，旧轮的临时 adjusting 被持续保留；旧完整正文被拦住且留下一轮错误活动状态。受控原生复现保留，Rex 明确确认最小修复，见决策 228。已让临时保护依待接收补充结束，按真实完成状态投影；完成事件先到时可用可靠同版本、同生命周期、稳定消息记录补齐既有正文，停止／归档／失效引用仍优先。

10 个新增原生场景及原回放／控制、受控 SSE 通过，隔离真实窗口已操作并查看完整旧回答和正常新回复；签名 Debug 及本机三库备份核对通过。完整真实模型到原生的连续补充链与 Rex 体验未验。详见 [STEER-01](../work-status.md#steer-01)及[本批证据](../evidence/2026-10-13-steering-inspection/README.md)。本批当时推进至第 6 条第一小点，其后的检查见下，继续先检查再对齐。

<a id="topic-6"></a>
## 第 6 条：模型重试与预算（2026-10-13，三小点完成本轮分项处理）

<a id="topic-6-1"></a>
### 第一小点：单步有限恢复，整轮共用上限（既有机制已有／未新增实现）

固定版 [retry-policy.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/adapters/src/model/retry-policy.ts)默认十次重试加首次请求，为单模型请求最多十一尝试，不能解释为整个任务总额。参考的是按层区分恢复并核对统一上限，不采用它的次数；本轮只核对源码，没有运行 ZCode。

Review Today 已有单步骤最多两次实际发送，接口重发和一次格式修复共享；整轮默认十二次准入、180 秒和累计估算输入 512,000。语义修复是另一个已有节点，仍计入整轮，补充不重置，明确重试／恢复新开预算段而总账保留。本轮没有修改这些既有产品规则。

23 项兼容分支、13 项 DeepSeek／2 子场景与四组受控叠加路径通过；暂未复现生产重试绕过上限。首次四项兼容端点旧夹具继承日常 DeepSeek 配置而失败，原记录保留，两分支隔离测试通过并未修掉默认夹具维护问题。没有真实供应商调用、新原生验收或金额上限证明，后台维护与能力探测另有范围。见 [RETRY-01](../work-status.md#retry-01)及[本批证据](../evidence/2026-10-13-retry-budget-inspection/README.md)。随后第二小点的定位和修复见下；继续先检查再对齐。

<a id="topic-6-2"></a>
### 第二小点：用量有对应身份，缺失与补全不冒充完整（USAGE-01 已修复／分项验证通过）

前一轮已读固定版 [usage-observability.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/usage-observability.ts)区分逻辑请求身份、attemptIndex、状态与网络重试次数；记录层本身不能证明每个底层请求的用量都已知。本轮网页刷新返回 403，仅沿用已核对固定资料，不新增上游判断或运行 ZCode。

Review Today 已保存实际 usage、未知／部分与迟到账本，估算输入用于准入而不填账单。五项既有守卫通过；十个受控客户端／SQLite 场景进一步复现：无供应商 ID 的同一请求重复回报记两笔，相同 ID 先回报部分字段再补完整时，完整字段反被丢掉。供应商不返回用量与真实回报为零仍可区分；停止后仅补账不恢复正文，ACK／有版本恢复保留记录。核心字段仍缺失而标 reported 是相关状态观察，不证明用户已见错误费用。

Rex 明确选择最小范围修复，见决策 229：已在实际请求准入时记录稳定本地身份，回报归原请求并补全，缺失保持未知／部分；真实两笔请求即使数字或供应商 ID 相同也分开，旧匿名多请求不猜测。没有扩大重试、预算、模型、供应商或界面。

新增 16 场景，完整服务 1170 passed／4 skipped／521 subtests、DeepSeek 专项 29 passed／2 subtests、原生回放／控制及受控 SSE 通过；同十场景修复对照保留原基线。没有真实供应商费用核账、历史账单重算或新费用界面验收，原四项默认测试隔离问题继续开放。证据见 [USAGE-01](../work-status.md#usage-01)及[本批记录](../evidence/2026-10-13-usage-inspection/README.md)。下一研究位置第 6 条第三小点：前台之外的后台摘要／能力探测预算与用量，先检查再对齐。

<a id="topic-6-3"></a>
### 第三小点：后台工作也有对应预算与用量（MAINT-01 已实现／分项验证通过）

沿固定版研究的分层预算与用量参考核对 Review Today，没有安装或运行 ZCode。本轮网页取得固定文件元信息，但正文定位超时，沿用原已读材料，不新增上游调用边界结论。

后台摘要已有维护预算、对应 Run 用量与上下文版本守卫。40 项既有检查／4 子场景及十二个隔离基线场景完成：旧前台预算已到期仍可独立整理；维护调用／输入／时间上限拦住发送；整理跨批次共享两次实际请求；失败或归档失效保留原文与已完成回复，实际回报补原账目、缺失仍未知。没有据此通过真实供应商等待或费用验收。

原服务级模型能力探测沿旧规格持续退避：三个不同模型八轮合成连接失败后累计二十四次模拟请求，仍安排下一轮；兼容与 DeepSeek 分支成功探测各有四次带 usage 的合成回应，但没有账本回调。局部两次／默认 45 秒限制不等于整批探测有总轮数上限；401／403 与并发防重等保护已有。旧结果保持在原只读证据中，不作为当前实现状态。

Rex 明确确认最小范围（决策 230），契约先更新后已实现：每批首次＋三次重试，到限等待明确重检；保留现有单步等待、10／30／120 秒退避、临时失败角色重检及访问拒绝守卫。实际请求、回报及未知用量独立服务记账，重复／补全及迟到回报归原请求，新批次保留旧账；摘要、前台预算、模型、供应商和界面保持。

新增 23 场景，完整服务 1193／521 子场景、DeepSeek 专项 57／2 子场景、四组原生合同及受控 SSE 通过。八摘要＋三探测组合回放证明原保护保留、第四轮停止和成功回报入账；不是实际供应商费用、退出或完整原生链验收。原默认兼容夹具隔离问题开放。见 [MAINT-01](../work-status.md#maint-01)和[实施证据](../evidence/2026-10-13-maintenance-inspection/repair.md)。第 6 条完成本轮分项处理；下一研究项为下表“项目记忆”，先检查再对齐，不据此引入自动后台记忆。

<a id="topic-7-1"></a>
## 第 7 条第一小点：项目记忆的事实与检索身份

2026-10-13 增量读取固定版本 [extraction.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/memory/extraction.ts) 正文：抽取处理耐久消息范围，成功或无需更新后推进边界；提示参考已有记忆目录，优先更新适合的现有文件。其写入范围文字是提示约束，本次没有独立证明系统级限制或完整后台运行。原按空白计词的中文边界保留，不照搬为学习记录准入。

Review Today 已有正式知识卡、类型化学习记录和会话上下文，学习可以没有卡片；已有出处、版本、排除与失效守卫，不需要据此新建自动记忆流程。本轮检查真实原生检索复现同名双卡被标题去重，服务关联只能收到一张；这是本项目实现缺口，不是 ZCode 同类故障或其方案的运行证明。

Rex 确认 231 后，MEM-01 只改为知识卡按唯一身份去重。新增七组行为、四组原生合同、受控 SSE、九项服务守卫及七场景前后对照通过；签名 Debug 已备份更新，三库全表不变。真实模型选择、双卡回答与 Rex 使用验收未覆盖。见 [MEM-01](../work-status.md#mem-01)及[证据](../evidence/2026-10-13-memory-inspection/README.md)。下一点增量检查纠正／排除／删除后的旧记忆失效时机，不引入自动后台记忆或新调用。

<a id="topic-7-2"></a>
## 第 7 条第二小点：旧记忆失效时机

2026-10-14，最初 Rex 回复「继续」后增量检查本项目，当时不新增上游机制结论或实施范围。版本、排除、删除、迟到内容、重新允许使用与历史保留的原守卫分项正常；修复前复现的是失效依赖的恢复中回复没有立即显示中断，待后续服务新版本事件才恢复真实状态。

六个原生场景、生产服务格式修复事件到 Mac 的离线重放、十项服务记忆／纠正检查及五组既有原生合同完成；供应商受控、没有完整 HTTP 或真实窗口验收。失败的初始观察假设保留，不能把脚本成功复现当作修复通过；原检查见 [MEM-02](../work-status.md#mem-02)及[基线证据](../evidence/2026-10-14-memory-invalidation/README.md)。

Rex 随后明确确认 232，先更新契约后只改原生状态投影。新增三状态回归、五组原生合同与受控 SSE、十项服务守卫、六场景和同一事件／回执修复对照通过，正文／历史与原规则保持；签名 Debug 已备份更新，三库全表不变。解锁后隔离原生窗口的即时中断、停止同步、正文保留、浅深色及窄窗检查通过，历史锁屏记录保留。真实供应商、HTTP、完整 VoiceOver、语义识别质量与 Rex 日常体验未验，正常停止／归档、自动记忆与语义治理不扩大。见[实施与交付](../evidence/2026-10-14-memory-invalidation/repair.md)。该批续接的目标核验见[第三小点](#topic-7-3)。

<a id="topic-7-3"></a>
## 第 7 条第三小点：目标完成要有对应依据

2026-10-14，Rex 回复「继续」后增量读取固定版[核验契约](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/contracts/src/tools/target.ts)、[目标续跑](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/target.ts)与[核验运行](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/target-completion-verification.ts)正文。按目标类型及逐项要求取证值得参考，但其格式／非取消调用故障默认通过属于编码 Agent 的续跑取舍，不能照搬到掌握或保存。未运行 ZCode、安装依赖或新增独立日常核验器。

Review Today 已区分 Run、理解状态和保存回执。十一阶段受控检查及 56 项服务测试／38 子场景通过：评分异常不授掌握、停止不接收迟到结果、普通题不完成整节、综合当前节不代替其他节、跳过仅结束讲解、问题攻克保留独立与迁移门槛、草稿不当作已保存。没有复现新的确定性完成缺口，暂不新增生产实现；真实语义准确性与完整原生链仍未验，前序误判记录不改为通过。见 [TARGET-01](../work-status.md#target-01)与[本批证据](../evidence/2026-10-14-target-verification/README.md)。

该批之后的状态覆盖检查见[第四小点](#topic-7-4)；形式模型枚举不等于本项目实现或教学质量已验收。

<a id="topic-7-4"></a>
## 第 7 条第四小点：状态覆盖与连续教学评测

2026-10-14 增量读取固定版 [formal-proof 说明](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/packages/formal-proof/README.md)、[model.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/packages/formal-proof/src/model.ts)与[投影裁决](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/bootstrap/src/zcode-protocol-v4/projection-state.ts)。可参考按状态、操作和预期结果枚举，再检查实际执行守卫。投影确有可执行可用性／路由规则；两处注释提到一致性黄金测试，本次未在固定版公开树找到或运行该测试，不据此宣称机械验证通过。模型的 E2E 字段为断言文字，不是 App 实测；本次不运行 ZCode 或重复前序枚举以增加数字。

本项目已有用例库及真实固定／生成前文的追加记录，自动检查、语言审阅和 Rex 验收分开。十二阶段同会话／同邀请受控连续流程、55 项服务测试／10 子场景与三组原生合同通过，未复现新的确定性状态缺口。临时磁盘入库合同实际检查保存及回滚；服务连续流程使用模拟 Mac ACK，不把它与旧真实模型流程合成为同一次真实保存链。

最具体的缺口是同一次新生成教学到真实原生保存的贯通证据，以及教学／评分语义审阅。复用现有 QA-01，单条 RAG 讲解、漏答／完整作答、预览、纠正、原生保存、实际卡片／回执与查询的八步建议已记录，真实调用范围和预算待对齐；本轮没有新增生产实现、供应商调用或 App 更新。此前评分误判、失败与 Rex 体验边界保持，17 条案例目录仍 pending。见 [EVAL-01](../work-status.md#eval-01)与[完整证据](../evidence/2026-10-14-evaluation-coverage/README.md)。七条既定研究完成源码对照与本轮分项检查，不代表所有候选机制采用或全部产品验收。

之后 Rex 按 233 授权真实试跑，EVAL-02 在漏答阶段复现 passed 与 completeness 矛盾，四概念全部认证并形成未答全范围的邀请；整节仍 unknown、实际卡片为 0。十三次真实请求后按约定停止，未执行的真实知识保存链与体验保持未验。初始 QA 接线、计数漏记及其修订另保留，不替换实际教学／评分或篡改失败。本轮没有生产修复，下一步 [CHECK-01](../work-status.md#check-01) 最小普通题通过门槛待对齐，见[真实证据](../evidence/2026-10-14-live-learning-save/README.md)。这说明状态枚举与受控合同仍需结合真实内容、评分和原生结果逐层验收。

2026-10-15，Rex 要求开始修复，CHECK-01 已按 234 实现同次评分的题面必要项／答案依据守卫；15 项新增回归、1208 项全量受控与三组原生合同通过。真实固定上下文复验首个入口请求超时，未进入评分，失败停止；累计预算保守 14／30，余 16 次不重跑。原 EVAL-02 失败、真实评分效果及完整保存链未验分别保留，见[本批证据](../evidence/2026-10-15-ordinary-check-completeness/README.md)。本轮沿用前述源码研究，不新增 ZCode 机制结论或扩大 UI。

10-16，Rex 继续后，CHECK-01 的漏答、完整答、单点题三组真实固定上下文均通过，六次新增请求且均有真实用量，无生产修改／重试／探测；总预算保守 20／30，余 10。旧失败及超时保持，三组不是完整新教学到原生保存链；下一关是实际保存和回执、详情与查询，见[续接实证](../evidence/2026-10-16-ordinary-check-recheck/README.md)。不增加新上游研究结论或提升通用评分验收。

同日原生保存续接因缺少公开查询而在 23／30 停止。Rex 按决定 235 授权后，[VERIFY-01](../work-status.md#verify-01) 已补按需安全查询并恢复原核验调用，完整受控 1217／538 通过；真实搜索、读取、核验后原生保存四卡并有匹配回执、新进程磁盘和一张详情证据。随后状态查询把旧保存失败提示当成学习边界，误报未保存，累计 29／30 后停止。下一条 [STATUS-01](../work-status.md#status-01) 已只读定位、未实施；QA 接线修正、原失败及未覆盖层级各自保留，完整链和 Rex 体验仍未验。此项是本项目真实失败的补齐，不新增 ZCode 源码结论；详见[本批实证](../evidence/2026-10-16-native-save-continuation/README.md)。

随后 Rex 按决定 236 确认 STATUS-01，已修执行结果提示造成的查询对象丢失，完整受控 1229／549 和原真实数据的冻结路由回放通过；原生投影及磁盘核对保持四卡，正确回复保存数量，无新增入库／真实模型请求。旧查询误报和 29／30 计数不改；新真实查询、输入 outbox、完整连续链与 Rex 体验继续开放。见[本批结果](../evidence/2026-10-16-status-query-scope/README.md)，本次不扩大上游研究结论或 UI 范围。

继续后已补齐冻结模型判断下的原生输入交接：正式输入框发送一次，经真实本地服务和同步正确回答四卡，新进程磁盘确认输入／Run／回复一致、原四卡保持；新增真实请求 0。该分项不是新真实路由或全新连续链，原 29／30／STOP 保持；下一次真实同句查询是否使用原余 1 次已询问、待 Rex 确认，详见[原生输入证据](../evidence/2026-10-16-status-native-input/README.md)。

Rex 明确批准最后一次真实查询后，新模型准确选中原学习内容，程序依匹配回执报告四卡；正式原生输入／同步与新进程磁盘核对通过，无重复保存或旧数据变化。新增 1 请求／20,815 报告 token，原累计 30／30 后关闭；同句真实查询分项完成，完整全新连续教学链和 Rex 体验仍开放。见[本批证据](../evidence/2026-10-16-status-real-query/README.md)，不新增上游研究结论或 UI 范围，也不自动重置预算。

[EVAL-03](../work-status.md#eval-03) 已完成八步方案与实际 SDK 客户端的离线计数自检四组，并获决定 237 授权新批最多 30 次，含启动探测、重试及后台。实际执行停在托管运行环境初始化读取目录，原生默认启动最终失败；未进入模型探测，输入未发送，本批 0／30。空库与退出后独立磁盘核对通过，已 HOLD 并关闭窗口／进程，原因尚待排查，系统访问提示只是未确认假设。原 30／30、STOP、日常数据及配置保持；不把准备、空库检查或上一批各自分项当作同一完整链通过。见[执行证据](../evidence/2026-10-16-continuous-acceptance/live/README.md)，不新增上游研究结论或 UI 范围。

随后 Rex 确认没有弹窗，并明确允许隔离窗口访问本项目；零模型依赖检查通过后恢复同批原会话，旧失败保持。新默认探测、漏答拦截及完整答后的原生预览通过，第 4 步同点补充最终格式／来源校验失败，20／30 后停止、零卡保存，后续关卡未执行。KT-03 的留存数据复现确认「暂不保存」动作把可编辑邀请候选一并过滤，实际输出引文又不符合新解释来源。按决定 238 完成最小交接修复，四项／七子场景、全量 1233／556、DeepSeek 36／20 及留存数据受控回放通过，原错误引文仍拒绝；新增真实请求 0，余 10 次不自动使用。原[失败证据](../evidence/2026-10-16-continuous-acceptance/resumed/README.md)保持，当前[修复结果](../evidence/2026-10-16-preview-deferral/README.md)另记；未改日常数据、App 或新增 ZCode 研究结论，真实更新、完整链与 Rex 体验仍开放。

Rex 随后继续原余量，KT-03 的真实路由／候选／原生更新交接分项通过：同一邀请 v2 → v3，未保存且学习步骤保持。3 个新请求后发现下一处 KT-04：结构预览第 2 项两段引文不在当前选定片段，发布时整组要点／总结被撤下，只显示范围说明；本关仍未过，23／30 后停止、余 7 次冻结。已完成实际界面、新进程磁盘及留存数据定位，未新增生产修改或上游研究结论；下一条建议仅对齐预览引用错误与既有一次修复的交接，不跳研究条目或完整验收。见[真实续测与定位](../evidence/2026-10-16-preview-real-recheck/README.md)。

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
