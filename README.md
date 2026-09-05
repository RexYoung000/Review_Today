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
- 当前目标：按 Harness §18 补学习记忆、输入区学习方式/思考强度、导航/动效和内部可靠性；§17 未完成的安全/闭环/恢复仍继续。Auto 与知识整理、资料学习、主题探索、问题攻克为五种学习方式，不是五个模型档位。
- 当前边界：文字与公开链接的开发 Mac POC；语音、Realtime、通知、Spine、跨端、正式安装和部署不属于本轮 M1。
- 数据策略：Mac 本地持久化 Session、消息、任务、知识和复习历史；本机 Python 服务只执行当前任务并保留短期 checkpoint。

当前执行范围以 [Agent Harness V2 主规格](docs/agent-harness-v2.md) 与 [M1 验收契约](docs/m1-acceptance.md) 为准。

既有代码基线 67e8760：第一批恢复/生命周期/目标完成与入库分离/来源保持/后台摘要和 ACK 修复已实施，新增固定学习清单、成果小结及 Today 续学表达。此前记录了 132 项隔离服务测试、Mac 构建/契约、旧磁盘模型迁移通过及四种 RAG 界面部分原生检查。**仍不是完整 M1**：原供应商 403 是当时测试结果，任意崩溃时点的增量快照合成及其余原生路径待完成。完整边界见验收 §0.10。

最新对齐仅完成文档同步：三入口及常驻会话区、浅色首用、双控制持久化、证据化跨会话记忆/排除、内部主备与质量规则、环点/选择动效尚未实施；新测试门槛见验收 §0.11。本次未调用模型、未改配置或用户数据，不把历史 403 当作当前探测，也不把备用策略写好等同于已恢复。听写/语音聊天只记录后续方向。

[OneWorks 两版实际候选](brand/oneworks/README.md) 已保留原始矢量、参数及 16–1024 px 导出；Rex 选择前不替换 V8。执行回归入口：`bash agent-service/run-controlled.sh`、`bash tests/mac/run-contracts.sh`、`bash tests/mac/run-migration.sh`。所有脚本使用隔离数据，不运行真实供应商训练任务。

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

- 已有 SwiftData Session、消息、学习任务、增量事件、来源／知识关联，以及原知识卡、复习和评分模型；
- 已有 V2 异步 Harness API、SQLite checkpoint、四种受控学习工作流和 v1 capture/review 兼容接口；
- 已有独立“学习”工作区、即时本地回显、Session 归档／恢复／结构化交接、运行详情和纯数据 Today；新目标将移除独立学习导航按钮而保留工作区，当前代码尚未调整；
- Debug App 会托管项目 `.venv` 服务，并在进程退出后恢复同一任务；模型角色启动检查会执行真实短生成探测，不进行静默降级；
- 已有语音采集、通知、FSRS、待处理和吉祥物动画等外围实现或 POC，但它们暂不属于最小闭环验收；
- 旧服务级真实模型冒烟曾验证稳定概念知识卡及 `good`／`again` 评分；当前 Harness 固定模型使用受控替身完成自动化验证。

尚未完成：

- 真实 Mac App 入口的 Harness V2 端到端验收；
- 原供应商此前出现上游 HTTP 403；真实模型能力必须重新验证。新的内部主备只有在范围、强度、结构和流式能力验证后才能启用，本次未配置任何备用供应商；
- 客户端端到端自动化仍未建立，Session 交接、四模式完成和完整记忆 ACK 仍需 Rex 在原生界面逐项确认；
- 模型在部分正确、同义表达、遗漏限定和常见误解上的稳定性验证；
- OpenAI Realtime 语音复习闭环。

因此，当前工作重点是按 [M1 验收契约](docs/m1-acceptance.md)完成真实体验验收并恢复模型服务，不是继续扩大到语音或通用 Agent。#17 与 M2 继续暂停。

当前目标主规格为 [Harness §18](docs/agent-harness-v2.md)，新门槛与旧实施证据分别见 [验收 §0.11 / §0.10](docs/m1-acceptance.md)。旧「已有」只说明基础存在，不保证新目标完成。先独立文档 commit/push，后续实现按契约分批验证与提交；本次文档回合不开始功能实现。新图标候选按 [品牌记录](brand/README.md) 交 Rex 选择，正式 V8 保留至明确接受。
