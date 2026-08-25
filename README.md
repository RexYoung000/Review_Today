# Review Today

Review Today 是“个人记忆教练”的项目仓库。长期方向是把日常学习内容转化成主动回忆训练；当前先做减法，只验证最小的知识解析与回答判断闭环。

## 当前阶段

```text
纯文字最小闭环
→ 知识与判断质量验证
→ Harness 收口
→ 语音闭环
→ 真实自用 POC
→ 再评估 Agent 动画、UI 载体与产品化
```

- 当前用户：Rex 本人。
- 当前平台：原生 SwiftUI macOS 应用。
- 当前目标：输入一段知识内容，形成知识卡和问题；用户用文字回答后，由独立评分调用判断是否正确并给出简短原因。
- 当前边界：语音、网页核验、FSRS、通知、完整 Harness、Spine 动画、跨端和部署均不作为里程碑一的验收项。
- 数据策略：Mac 本地 SwiftData 仍作为长期数据方向；本机 Python 服务负责当前 AI 调用。

当前执行范围与后续里程碑见[最小闭环与渐进式里程碑](docs/demo-plan.md)。

## 文档入口

| 文档 | 作用 |
|---|---|
| [最小闭环与渐进式里程碑](docs/demo-plan.md) | 当前唯一执行基线、减法边界、通过标准和后续阶段 |
| [M1 纯文字最小闭环验收契约](docs/m1-acceptance.md) | M1 固定输入、知识卡要求、正确／错误回答和三层验收证据 |
| [产品需求与边界](docs/product-requirements.md) | 长期产品方向与需求池，不代表当前全部实施 |
| [Agent 与系统架构](docs/architecture.md) | 现有实现、目标架构、LangGraph 与 Harness 边界 |
| [Apple Foundation Models 与 PCC 评估](docs/apple-foundation-models-evaluation.md) | Apple 设备端模型、PCC、适用场景、限制与里程碑二评测决定 |
| [产品界面与体验方向](DESIGN.md) | 长期界面和体验方向 |
| [21 天 POC 验证方案](docs/poc-validation.md) | 核心闭环稳定后的持续行为验证方案 |
| [决策记录](docs/decision-log.md) | 历史决策及修订关系 |

## 当前实现状态

项目已经有一套可构建的 macOS App 和本机 Agent 服务，不再是默认空工程：

- 已有 SwiftData 领域模型、采集入口、知识卡／知识库、文字答题与评分界面；
- 已有 FastAPI 服务、OpenAI 接入、LangGraph 采集整理图和独立回答评分调用；
- 已有语音采集、通知、FSRS、待处理和吉祥物动画等外围实现或 POC，但它们暂不属于最小闭环验收；
- macOS Debug 构建通过，本机服务健康检查通过；
- 服务级真实模型冒烟已验证：稳定概念可生成知识卡，正确回答判为 `good`，明显错误回答判为 `again`。

尚未完成：

- 真实 Mac App 入口的完整端到端验收；
- 固定评测集和自动化测试；
- 模型在部分正确、同义表达、遗漏限定和常见误解上的稳定性验证；
- 持久化 checkpoint、严格 ACK 事务、完整事件回放与恢复；
- OpenAI Realtime 语音复习闭环。

因此，当前工作重点是收口和验证，不是继续扩大功能面。
