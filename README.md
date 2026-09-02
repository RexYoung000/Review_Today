# Review Today

Review Today 是“个人学习教练”的项目仓库。它帮助用户理解资料、探索主题、攻克问题，并在确认后把成果转化成主动回忆训练。

## 当前阶段

```text
旧纯文字知识卡与评分基线
→ M1 Session Harness V2
→ 真实 Mac 体验验收
→ 知识与判断质量验证
→ 语音闭环
→ 真实自用 POC
→ 再评估 Agent 动画、UI 载体与产品化
```

- 当前用户：Rex 本人。
- 当前平台：原生 SwiftUI macOS 应用。
- 当前目标：完成可持续的学习 Session、即时反馈、服务恢复、可回放任务事件，以及记忆整理、资料学习、主题探索、问题攻克四种受控工作流。
- 当前边界：文字与公开链接的开发 Mac POC；语音、Realtime、通知、Spine、跨端、正式安装和部署不属于本轮 M1。
- 数据策略：Mac 本地持久化 Session、消息、任务、知识和复习历史；本机 Python 服务只执行当前任务并保留短期 checkpoint。

当前执行范围以 [Agent Harness V2 主规格](docs/agent-harness-v2.md) 与 [M1 验收契约](docs/m1-acceptance.md) 为准。

## 文档入口

| 文档 | 作用 |
|---|---|
| [Agent Harness V2 主规格](docs/agent-harness-v2.md) | 当前唯一跨产品、交互和技术实施基线 |
| [M1 Agent Harness V2 验收契约](docs/m1-acceptance.md) | Session、四模式、恢复、真实 Mac 验收及旧闭环回归 |
| [最小闭环与渐进式里程碑](docs/demo-plan.md) | 历史里程碑记录及 2026-09-02 顺序修订 |
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

- Harness V2 的领域模型、异步接口、四模式和学习工作区；
- App 自动托管本机服务、增量事件回放和 Session 恢复；
- 真实 Mac App 入口的 Harness V2 端到端验收；
- 服务级固定样本已有自动化测试和显式真实模型冒烟，但客户端端到端自动化仍未建立；
- 模型在部分正确、同义表达、遗漏限定和常见误解上的稳定性验证；
- 持久化 checkpoint、V2 ACK 事务、完整事件回放与恢复；
- OpenAI Realtime 语音复习闭环。

因此，当前工作重点是按主规格收口 Harness，并保留旧知识卡与评分兼容，不是继续扩大到语音或通用 Agent。
