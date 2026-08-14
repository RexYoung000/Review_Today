# Review Today

Review Today 是“个人记忆教练”的项目仓库。产品把每天零碎输入的学习内容整理成可复习的知识点，并通过主动发起的结构化语音问答帮助用户形成长期记忆。

## 当前阶段

```text
本机完整 Demo（设计完成，待实施）
→ 21 天自用 POC
→ 再评估部署、登录、iOS、同步与商业化
```

- 当前用户：Rex 本人。
- 当前平台：原生 SwiftUI macOS 应用。
- 当前目标：先完成一套能在本机跑通真实 AI 链路的整体 Demo，再决定是否开始连续 21 天验证。
- 数据策略：完整知识、来源、掌握状态、排期和复习历史以 Mac 本地数据为准。
- 服务策略：Demo 由手动启动的本机 Python 服务承载 LangGraph 与 OpenAI 调用；正式部署暂不讨论。

## 文档入口

| 文档 | 作用 |
|---|---|
| [产品需求与边界](docs/product-requirements.md) | 产品定位、知识模型、采集、复习、知识库和长期数据规则 |
| [本机 Demo 实施与验收](docs/demo-plan.md) | 当前 Demo 的范围、运行边界、真实链路和端到端验收 |
| [Agent 与系统架构](docs/architecture.md) | LangGraph、OpenAI、SwiftData、数据流、状态机和异常恢复机制 |
| [产品界面与体验方向](DESIGN.md) | “今日记忆跑道”、独立复习窗口和“安静的学习编辑台”方向 |
| [21 天 POC 验证方案](docs/poc-validation.md) | Demo 通过后的行为验证、指标口径与复盘要求 |
| [决策记录](docs/decision-log.md) | 第 1–77、79–82 项已确认决策、修订关系和第 78 项待确认内容 |

原始创意摘要保留在 [ideas 创意库](https://github.com/RexYoung000/ideas/blob/main/memory-coach.md)，项目内文档是后续设计与实施的事实来源。

## 当前实现状态

项目目前仍只有 Xcode 创建的基础 SwiftUI 工程和默认 `Hello, world!` 界面：

- 没有知识采集、Agent、语音复习、排期、通知或菜单栏功能；
- 没有 Python 服务、SwiftData 模型或 OpenAI 接入；
- 没有可验收的产品界面、交互录屏或真实使用结果。

本轮完成的是产品与技术意图的文档化。文档完成不代表代码完成、Demo 可运行或体验已经通过 Rex 验收。
