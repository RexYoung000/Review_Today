# 普通小题与本节综合检查 · 2026-10-13

Rex 明确选择「先收紧默认规则（推荐）」后实施。普通题只记录对应知识点；本节综合检查沿现有对话入口明确请求，独立答案完整通过后才可验证当前节。规则见[决策 226](../../decision-log.md)、[Harness](../../agent-harness-v2.md#conservative-check-scope)、[DESIGN](../../../DESIGN.md#comprehensive-check)，续接见 [SCOPE-01](../../work-status.md#scope-01)。

## 实际实现

- 普通教学／补充题的模型整步标签在程序侧固定为概念；评分声称整步完成也不升级。
- 请求绑定当前用户原话、现有已讲步骤、计划版本与讲义；引文、否定、条件句、错误对象及控制冲突不能授权综合检查。拒绝无效请求后保持原题，不因选中的学习方式误换题。
- 综合题原样包含完整步骤要求，发布题目与绑定在同一事务；出题前冻结完整条件及其中明确列举的必需子项，排除示例与可选项。同次评分逐项提供当前答案原文，缺项、否定、重复或虚构引文不允许整步通过。
- 保存历史绑定不回写；旧未授权整步绑定按概念投影使用，旧掌握／知识卡／聊天保留。提示、停止、源变更、继续／跳过与问题攻克原门槛保留；Jev 隔离实验仍受原质量检查与预算约束。
- 原文定位投影只修正给模型的展示引用，保留真实 Markdown 连续选段；保存引文校验未放宽。没有新增独立范围核验、供应商、按钮或子 Agent。

## 服务回归

最终标准 `bash run-controlled.sh` exit 0：[full-tests-proof-repair-final.log](full-tests-proof-repair-final.log) 为 **1146 passed、4 skipped、521 subtests passed**，包含新增 24 项，五条原弃用 warning 保留。四项跳过为原有 Chrome opt-in 场景。

历史过程按时间保留：

| 批次 | 结果 | 处理 |
|---|---|---|
| 初始小批次（工具输出） | 5 个子场景失败；48 项通过 | 继续／跳过夹具复用了同一节，修正为独立会话；生产缺陷为拒绝无效综合请求后仍误入教学、替换原题，收紧路由 |
| 扩大子集（工具输出） | 127 项与 39 子场景通过 | 当时实现的中间验证，未作为最终收口 |
| [targeted-tests.log](targeted-tests.log) | 1 failed、174 passed、47 subtests | 实验质量失败夹具把合法 `latest_run_id` 更新误当学习进度变化，改为分别核对；实测其余上下文不变 |
| [targeted-tests-final.log](targeted-tests-final.log) | 175 passed、47 subtests | 首轮范围实现的子集，不含后续证据守卫 |
| [full-tests.log](full-tests.log) | 1139 passed、4 skipped、514 subtests | 首轮完整服务通过，之后真实反例仍失败，未据此交付 |
| [targeted-tests-proof.log](targeted-tests-proof.log) | 1 failed、178 passed、54 subtests | 新负例不生成 `verified_concepts` 字段，夹具错误直接索引；改为允许字段不存在 |
| [full-tests-proof.log](full-tests-proof.log) | 1143 passed、4 skipped、521 subtests | 逐项证据首轮完整回归，包含上项夹具修正；后续仍有连续语义／衔接失败 |
| [followup-tests.log](followup-tests.log) | 46 passed、20 subtests | 补题反馈降级子集；夹具直接赋 dict 引起额外序列化 warning，已改为类型对象 |
| [full-tests-final.log](full-tests-final.log) | 1144 passed、4 skipped、521 subtests | 反馈降级后的中间回归 |
| [source-recovery-tests.log](source-recovery-tests.log) | 50 passed、31 subtests | 原文标记及反馈后重新请求的依据续接子集 |
| [full-tests-recovery-final.log](full-tests-recovery-final.log) | 1144 passed、4 skipped、521 subtests | 原文与依据续接中间回归，尚未加入作答意图冲突守卫 |
| [intent-recovery-tests.log](intent-recovery-tests.log) | 33 passed、18 subtests | 作答误标为材料的一次结构修复 |
| [full-tests-delivery.log](full-tests-delivery.log) | 1145 passed、4 skipped、521 subtests | 意图衔接中间回归，之后发现答案引文被改写 |
| [proof-repair-tests.log](proof-repair-tests.log) | 48 passed、20 subtests | 答案引文有界修复子集 |
| [full-tests-proof-repair-final.log](full-tests-proof-repair-final.log) | 1146 passed、4 skipped、521 subtests | 最终冻结服务源码的完整回归 |

停止／题目发布、版本漂移、提示作答、旧绑定、普通题越权、逐项证明缺失／重复／否定／伪造引文、引用和条件请求、继续／跳过、问题攻克与实验兼容均有覆盖。完整性守卫是结构和来源检查，不能证明模型语义永不误判。

## 真实固定上下文回放与保留的失败

使用临时 SQLite，受控设置阶段复用[上一批真实教学输出](../2026-10-12-coach-rule-loading/real-samples.json)；该对象原将模糊小题标为 `step`。后续五轮入口与评分均为真实现有 DeepSeek 调用，不修改供应商或密钥。`RunReport` 记录输入、输出、前后状态、事件、模型与用量，阻断网页读取／搜索及知识写入。脚本：[verify_live.py](verify_live.py)。不是完整真实模型出题流程。

| 回合 | 预先固定的输入 | 初批 | 续修后 |
|---|---|---|---|
| 普通小题 | 短答说明补知识缺口和可靠性边界 | 引用格式校验失败，无最终反馈 | 通过小题，当前节仍 unknown |
| 明确综合请求 | 检查一下我是否掌握这一节 | 通过 | 通过；仅一次原意图调用，完整要求可见，不提前掌握 |
| 综合题不完整答案 | 同一个短答案，未说明私有资料缺失与可能编造 | 错误通过并验证整节 | 拒绝完整通过，明确漏项；后续题恢复概念范围 |
| 再请求综合检查 | 同一显式请求 | 原误授掌握已存在，未满足无提前掌握检查 | 通过；仍不提前掌握 |
| 完整独立答案 | 明确说明三类限制、可追溯依据与边界 | 引用格式校验失败；前次误授已污染状态 | 通过，仅当前节 verified，其余节与整计划 unknown |

初批：[live-fixed-context.jsonl](live-fixed-context.jsonl)、[日志](live-fixed-context.log)、[原设置状态](seed.json)，自动结果 **1/5**。完整原始失败不被续修结果覆盖。评分在 `completeness` 承认缺项，却仍返回通过，说明只加完整题面不足；原讲义引用忽略 Markdown 标记，触发严格原文检查。

中间逐项证据批：[live-proof.jsonl](live-proof.jsonl)、[日志](live-proof.log)、[新设置状态](live-proof.seed.json)，自动结果 **5/5**。该结果未作为最终收口，后续连续复测仍暴露衔接问题：

| 批次 | 自动结果 | 实际发现与处理 |
|---|---|---|
| [live-final](live-final.jsonl) | 3/5 | 无效补题降级后丢掉当前题目依据，再次综合请求无法发布；只在原步骤／计划／讲义版本有效时复用刚才评分绑定，不继承旧授权 |
| [live-recovery-final](live-recovery-final.jsonl) | 4/5 | 入口原话和判断说明都认定是作答，却标为 goal/material，误入教学；加当前综合题作答字段一致性的一次结构修复 |
| [live-delivery](live-delivery.jsonl) | 4/5 | 完整答案被模型判对，但答案引文拼接／增删了连接词，程序正确拒绝证明；改走原一次结构修复，不能当用户漏答 |
| [live-proof-repair](live-proof-repair.jsonl) | 5/5 | 最终源码：普通小题通过、显式综合请求、不完整答案拒绝、再次请求、完整独立答案仅验证当前节全部通过 |

对应原始日志、各批 `.seed.json` 设置状态均保留在同目录，未重写旧失败。最终 [live-proof-repair.jsonl](live-proof-repair.jsonl) 共 **8 次语义调用、8 次运输请求**，该组无结构重试；两次综合请求各仅一次原入口调用，无教练出题或独立核验。最终完整答案各项都有当前答案原文；未说明的子要求不获证明，没有自动生成草稿、保存或推进后续步骤。所有批次的实际延迟、用量、源码哈希与人工复核见 [review.json](review.json)。结构修复仍服从原预算与一次上限，不从调用数不变推断性能或费用改善。

## 原生交互检查

隔离 QA 使用生产 `LearningWorkspace`、会话同步和 Markdown 组件，单独 App 身份、SwiftData、Harness 数据库与端口；讲义设置仍为上述受控实际输出，后续入口／评分真实。首次与最终编译见 [native-build.log](native-build.log)、[native-build-final.log](native-build-final.log)，QA 入口源码见 [NativeScopeQA.swift](NativeScopeQA.swift)。最终由 QA App 自身托管服务，未替换日常 App，未操作日常数据库。

已实际操作：普通小题通过后出现标题／要点／一句总结的未保存邀请，复习默认关闭；学习安排仍为已讲解。综合题在现有输入区请求后可见，已实看初始浅色普通题与深色 760×700、减少动态及换行；缩窗保留原滚动位置，需要下滚才能看到题面，初始和滚动后截图分别保留。漏答首试因补题绑定校验中断，负例见 [native-first-incomplete-failure.json](native-first-incomplete-failure.json)；续修后原按钮重试保留反馈、不授整步，再次明确请求和完整独立作答均实际发送完成。

最终学习安排第一节显示 **已验证**，后三节仍 **待学习**。服务读取确认当前节 verified、其余节与整计划 unknown，草稿／待保存均无，一个邀请仍 offered、没有 knowledge_ids，未点击保存。实证见 [native-final-state.json](native-final-state.json)、[native-complete.txt](native-complete.txt)、[native-complete.png](native-complete.png)。这是实际模型到原生回复和学习状态链，不包含真实出题或知识卡保存。

验证方法的失败另保留：重开 QA 夹具再次应用初始旧恢复增量，被 `RT.SESSION.INVALID_RECOVERY_DELTA` 拒绝并因夹具 `try!` 退出；入口改为只在新会话初始化时应用初始页，已有会话沿生产同步恢复。手动单独服务被隔离模式的自有托管守卫拒绝，改为关闭自建服务、由 QA App 托管，未修改该生产守卫。QA 夹具失败／启动日志和最终源码分别保留，不把它们写成日常 App 缺陷，也不以静态截图替代操作。

其他截图与 AX：[普通题](native-ordinary.png)、[普通题 AX](native-ordinary.txt)、[窄窗综合正文](native-comprehensive-dark-narrow.png)、[正文 AX](native-comprehensive-dark-narrow.txt)、[缩窗初始视口](native-comprehensive-dark-narrow-initial.png)。最后一次重开沿用 QA 身份的已保存外观，最终截图仍为深色；未据此声称再验了浅色或系统级减少动态。

## 验证边界与续接

- 默认范围与程序完整性守卫已验证；逐项语义仍由原评分模型负责，不承诺通用准确率。未显式枚举的复杂能力条件仍需模型整体判断，不能把字面提取称为语义拆解。
- 没有重跑或启用之前失败的独立核验器；新增字段会增加少量上下文与综合评分输出，不从调用数不变推断费用或延迟下降。
- 本批未验证完整真实出题、真实网页工具、综合通过到知识卡落盘、整计划最终完成、完整 VoiceOver 或全部题型／语言／长条件。既有完整保存链和 Rex 最终体验门槛保留。
- 工程文件原有未提交改动保留，不纳入本批；供应商配置不改；不包含发布、合并或验收关闭。
- 日常 App 进程与 8742 监听均已只读确认不存在，仓库服务源码已更新，下次打开由 App 启动新版。临时 QA 在记录完成后关闭，不将其身份／数据用于日常运行。日志归档仅去掉行尾空格以满足差异检查，原始／归档哈希及转换说明见 [review.json](review.json)；JSONL 原始内容不改。
