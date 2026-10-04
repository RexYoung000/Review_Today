# 文档导航与功能索引

这里回答“去哪里找”；[当前工作与续接记录](work-status.md)回答“做到哪、下一步是什么”。返回[项目主页](../README.md)。

## 阅读顺序与职责

| 需要了解 | 首选文档 | 如何使用 |
|---|---|---|
| 当前待办和本轮执行位置 | [工作记录](work-status.md) | 已确认、待实施、待验证分开；续接先读这里 |
| Agent 应当怎样工作 | [Harness 主规格](agent-harness-v2.md) | 跨产品与技术行为契约；待实施条款是目标，不是现状 |
| 界面、交互与视觉规则 | [DESIGN](../DESIGN.md) | UI 修改依据；历史原型不自动成为新需求 |
| 当前系统由什么组成 | [架构](architecture.md) | 实现地图与边界；早期目标有历史标识 |
| 产品定位与长期需求 | [产品需求](product-requirements.md) | 解释产品含义，不以需求清单推定已经实现 |
| 为什么作出某个决定 | [决策记录](decision-log.md) | 决定与修订关系；本轮新规则也在这里备案 |
| 什么问题、怎么修过、结果如何 | [迭代记录](agent-iteration.md) | 错例、修复批次与证据入口；旧 PASS 不覆盖后来发现的失败 |
| 怎样验收 | [M1 验收契约](m1-acceptance.md) | 用例与历史证据分开；受控、真实模型、原生与用户验收分层 |

发生冲突时，先查同一功能最新的明确修订及其状态。产品目标以已确认的主规格／设计为准；“当前已实现”须有代码依据，“已验证”须有对应证据。工作记录只汇总状态，不另造规则。无法确认的冲突保留为待核对项，不用最新日期自动覆盖用户决定。

## 按功能查文档、实现和证据

本表提供检索入口，不宣称每行已经完整验收。

| 功能／关键词 | 规则入口 | 主要实现入口 | 证据或当前缺口 |
|---|---|---|---|
| 会话、发送、停止、恢复、同步 | [Harness](agent-harness-v2.md)、[架构](architecture.md) | [AgentComposerStore](../Review_Today/AgentComposerStore.swift)、[ConversationSync](../Review_Today/ConversationSync.swift)、[conversation](../agent-service/agent_service/conversation.py) | [M1 验收](m1-acceptance.md)；完整体验仍开放 |
| 分步教学、题意澄清、答题、掌握 | [Harness](agent-harness-v2.md)、[迭代](agent-iteration.md) | [learning_progress](../agent-service/agent_service/learning_progress.py)、[conversation_prompts](../agent-service/agent_service/conversation_prompts.py) | [教学对齐](evidence/2026-10-03-teaching-alignment/README.md)、[问答与知识闭环](evidence/2026-10-03-knowledge-closure/README.md) |
| 新增知识、答对后提示、稍后录入 | [DESIGN](../DESIGN.md#knowledge-save-invitation)、[KT-01](work-status.md#kt-01) | [TopicCapture](../Review_Today/TopicCapture.swift)、[knowledge_invitation](../agent-service/agent_service/knowledge_invitation.py)、[topic_capture](../agent-service/agent_service/topic_capture.py) | 已实现，分项自测通过；范围更新回放与简化后的原生体验见[本批证据](evidence/2026-10-04-knowledge-invitation/README.md)，不等于全链路通过 |
| 有没有生成卡片、旧卡／新卡、状态指代 | [KT-02](work-status.md#kt-02)、[迭代](agent-iteration.md) | [knowledge_capture_status](../agent-service/agent_service/knowledge_capture_status.py)、[schemas](../agent-service/agent_service/schemas.py) | 已修复并有定向／同句真实回放；当前边界见[本批证据](evidence/2026-10-04-knowledge-invitation/README.md)，保留[10 月 3 日历史证据](evidence/2026-10-03-knowledge-status-continuity/README.md) |
| 生成、核验、本机保存、重复提交 | [Harness](agent-harness-v2.md)、[M1 保存契约](m1-acceptance.md) | [KnowledgeIngestion](../Review_Today/KnowledgeIngestion.swift)、[topic_capture](../agent-service/agent_service/topic_capture.py) | [知识闭环](evidence/2026-10-03-knowledge-closure/README.md)；模拟回执不等于原生完整通过 |
| 上下文、摘要、学习记忆、旧卡引用 | [Harness](agent-harness-v2.md)、[研究第 2 项](design-references/zcode-agent.md#topic-2) | [conversation_context](../agent-service/agent_service/conversation_context.py)、[context_budget](../agent-service/agent_service/context_budget.py)、[source_projection](../agent-service/agent_service/source_projection.py)、[LearningMemory](../Review_Today/LearningMemory.swift) | [M1 长历史验收](m1-acceptance.md)；第 2 项公开证据选段已实施，状态见 [CTX-01](work-status.md#ctx-01)，[本批验证与限制](evidence/2026-10-05-source-selection/README.md) |
| 网页搜索、读取、来源、图片材料 | [网页工具说明](../agent-service/providers/web/README.md)、[架构](architecture.md) | [conditional_teaching](../agent-service/agent_service/conditional_teaching.py)、[source_projection](../agent-service/agent_service/source_projection.py) | [来源版本](evidence/2026-09-30-source-provenance/README.md)、[图片输入](evidence/2026-09-26-image-input/README.md) |
| 模型调用、结构恢复、用量、预算 | [Harness](agent-harness-v2.md)、[架构](architecture.md) | [conversation_model_call](../agent-service/agent_service/conversation_model_call.py)、[openai_client](../agent-service/agent_service/openai_client.py)、[run_accounting](../agent-service/agent_service/run_accounting.py) | 按批次查[迭代](agent-iteration.md)；不从库名推断供应商 |
| 今天、复习、评分、FSRS | [产品需求](product-requirements.md)、[DESIGN](../DESIGN.md) | [ReviewController](../Review_Today/ReviewController.swift)、[review_sessions](../agent-service/agent_service/review_sessions.py) | [复习语音](evidence/2026-09-23-review-voice/README.md)、[界面接入](evidence/2026-09-23-today-review-integration/README.md) |
| 听写、同一聊天连续语音 | [架构](architecture.md)、[ASR 说明](../agent-service/providers/asr/README.md) | [DictationController](../Review_Today/DictationController.swift)、[AgentVoiceConversation](../Review_Today/AgentVoiceConversation.swift) | [听写](evidence/2026-10-03-dictation-integration/README.md)、[连续语音 POC](evidence/2026-10-03-agent-voice-poc/README.md)；真人停顿／回声待体验 |
| 知识库、待处理、本地数据管理 | [DESIGN](../DESIGN.md)、[架构](architecture.md)、[工具说明](../tools/README.md) | [LibraryInboxSettings](../Review_Today/LibraryInboxSettings.swift)、[LocalDataReset](../Review_Today/LocalDataReset.swift) | [M1 验收](m1-acceptance.md)；迁移结论按当时日期读取 |

## 专项资料与历史记录

| 文档／目录 | 身份与使用边界 |
|---|---|
| [ZCode Agent 研究](design-references/zcode-agent.md) | 固定源码版本的研究与讨论位置；不等于采用全部能力 |
| [外部参考目录](design-references/README.md) | Opal、AirJelly、ZCode；参考与已确认产品决定分开 |
| [Jev 对照评测](jev-deepseek-evaluation.md) | 隔离评测和局部接入记录；不能推定日常启用 |
| [Apple 模型评估](apple-foundation-models-evaluation.md) | 当时模型能力与后续评测建议；采用前重新核实 |
| [里程碑计划](demo-plan.md) | 阶段演进与历史基线；早期“下一步”不是本轮任务 |
| [21 天 POC 方案](poc-validation.md) | 后续验证方法；不是已开始或完成 21 天的记录 |
| [分支审计](m1-branch-audit.md) | 2026-09-06 快照；当前分支用 Git 核实 |
| [吉祥物 POC](mascot-animation-poc.md)、[Spine 计划](mascot-spine-v1-plan.md) | 对应阶段记录；当前采用范围查 DESIGN 与[品牌记录](../brand/README.md) |
| [证据目录](evidence/) | 按日期／问题保存输入、输出、失败与边界；从迭代记录定位批次 |
| [工具说明](../tools/README.md) | 本地辅助工具与迁移边界，不是正常产品操作说明 |

## 查找与维护方式

1. 按表选功能，再读对应规则和实现；不先在全部历史记录中搜索“当前”。
2. 查错例从[迭代记录](agent-iteration.md)进入证据批次，确认日期、版本、受控／真实模型／原生／用户验收层级。
3. 搜索文件优先用 `rg`。将来若有 `.codegraph/`，代码导航按项目指令先用 CodeGraph；本轮未创建索引。
4. 新决定同步负责规则的主规格／设计，决策日志记录修订关系；只在[工作记录](work-status.md)维护本轮状态、执行位置和下一步。
5. 不因一次修复另建平行主规格。新证据挂回迭代记录；保留历史测试数字，并注明后续失败限制了哪些结论。

状态用语统一：**研究建议 → 已确认待实施 → 已实现待验证 → 分项验证通过 → 待 Rex 体验验收 → 已验收**。按证据使用；方向确认不代表相关功能全获实施授权，文档完成也不代表功能完成。
