# Review Today

Review Today 是“个人学习教练”的项目仓库。它帮助用户理解资料、探索主题、攻克问题，并在确认后把成果转化成主动回忆训练。

## 当前阶段

2026-09-05：已按 Rex 授权接入 DeepSeek 官方，Flash 路由/教学、Pro 风险判断；智能非思考、深入 high，旧配置保留、不自动备用。179 项服务回归、Mac 契约、真实结构化/流式/搜索和隔离 Harness 首轮样本通过；正常 App 已自行托管新配置服务。记录见 [验收 §0.13](docs/m1-acceptance.md#013-deepseek-官方接入2026-09-05)。下方旧 Luna/Terra/Sol 与 HTTP 403 是前批记录，不代表 DeepSeek 失败，也不再是等待接入的理由。

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
- 当前目标：按 Harness §19 / §18 补学习记忆、输入区学习方式/思考强度、导航/动效和内部可靠性；§17 未完成的安全/闭环/恢复仍继续。Auto 与知识整理、资料学习、主题探索、问题攻克为五种学习方式，不是五个模型档位。
- 当前边界：文字与公开链接的开发 Mac POC；语音、Realtime、通知、Spine、跨端、正式安装和部署不属于本轮 M1。
- 数据策略：Mac 本地持久化 Session、消息、任务、知识和复习历史；本机 Python 服务只执行当前任务并保留短期 checkpoint。

当前执行范围以 [Agent Harness V2 主规格](docs/agent-harness-v2.md) 与 [M1 验收契约](docs/m1-acceptance.md) 为准。

既有代码基线 67e8760：第一批恢复/生命周期/目标完成与入库分离/来源保持/后台摘要和 ACK 修复已实施，新增固定学习清单、成果小结及 Today 续学表达。此前记录了 132 项隔离服务测试、Mac 构建/契约、旧磁盘模型迁移通过及四种 RAG 界面部分原生检查。**仍不是完整 M1**：原供应商 403 是当时测试结果，任意崩溃时点的增量快照合成及其余原生路径待完成。完整边界见验收 §0.10。

本轮已在独立文档检查点 `2a69931` 推送后实现：四入口/Agent 起始页、常驻会话区、首发原子建会话、双控制、原生环点/选择动效，以及类型化学习记忆、排除门禁、连续恢复、稳定步骤、来源版本和有限执行预算。构建、受控回归及旧库迁移有新证据，详见验收 §0.12。Mac 当前锁屏，新增原生交互未验；模型曾成功返回寒暄/RAG/资料讲解，但后续复测再次 HTTP 403。没有改供应商或启用未批准备用，听写/语音聊天仍只是后续方向。

[OneWorks 两版实际候选](brand/oneworks/README.md) 已保留原始矢量、参数及 16–1024 px 导出；Rex 选择前不替换 V8。执行回归入口：`bash agent-service/run-controlled.sh`、`bash tests/mac/run-contracts.sh`、`bash tests/mac/run-migration.sh`。所有脚本使用隔离数据，不运行真实供应商训练任务。

当前实施已获授权：先同步全局协作规则（本机备份、不随项目提交）及项目文档，再按 Harness §19 完成安全恢复、学习记忆、内部可靠性、Agent 起始页/双控制/动效。首次发送才建会话、快捷开始仅编辑草稿。全局规则不扩大危险操作、发布或品牌采用权限。OpenAI Docs Skill 仅记录审查建议，不在此修改。

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
- 已有 Agent 起始页与独立草稿，首次发送才建 Session；即时本地回显、常驻会话区、归档／恢复／交接、学习清单与纯数据 Today 继续保留；
- Debug App 会托管项目 `.venv` 服务，并在进程退出后恢复同一任务；模型角色启动检查会执行真实短生成探测，不进行静默降级；
- 已有语音采集、通知、FSRS、待处理和吉祥物动画等外围实现或 POC，但它们暂不属于最小闭环验收；
- 旧服务级真实模型冒烟曾验证稳定概念知识卡及 `good`／`again` 评分；当前 Harness 固定模型使用受控替身完成自动化验证。

尚未完成：

- 真实 Mac App 入口的 Harness V2 端到端验收；
- DeepSeek 当前已通过接入和首轮样本；完整五模式、多轮独立作答/入库及长期供应商稳定性仍未验收。原供应商 403 留作历史，新内部主备没有启用；
- 客户端端到端自动化仍未建立，Session 交接、四模式完成和完整记忆 ACK 仍需 Rex 在原生界面逐项确认；
- 模型在部分正确、同义表达、遗漏限定和常见误解上的稳定性验证；
- OpenAI Realtime 语音复习闭环。

因此，当前重点是使用已接入的 DeepSeek 按 [M1 验收契约](docs/m1-acceptance.md)继续完整原生/学习闭环验收，而不是继续等待旧供应商、扩大到语音或通用 Agent。#17 与 M2 继续暂停。

## 开发 Mac 的模型配置

- `agent-service/.env` 的 `REVIEW_TODAY_LLM_PROVIDER=deepseek` 选择 DeepSeek 官方；省略或 `openai_compatible` 保留旧兼容配置。
- DeepSeek 使用 `agent-service/providers/deepseek/.env` 中的 `DEEPSEEK_API_KEY` 及可选角色模型字段，模板见同目录 `.env.example`。该文件被 Git 忽略，权限应为 600；仓库不提供密钥。旧 `.env` 的 OPENAI 字段保留，选 DeepSeek 时不会继承旧端点、模型或密钥。
- 改配置后重启本地服务；Debug App 在无外部实例时自动托管。`GET /healthz` 的 `provider`、`model_roles` 和 `strengths` 为脱敏检查依据。失败的历史回复仍需手动重试，配置切换不自动恢复停止/归档。
- 无密钥回归：`bash agent-service/run-controlled.sh`（脚本主动清空两种凭证、使用隔离库）。真实模型检查：在 `agent-service` 运行 `.venv/bin/python -m tests.stream_real_smoke`，或加 `--case rag_answer --deep`；使用合成输入和临时数据库，会产生真实 API 用量。

当前目标主规格为 [Harness §19 / §18](docs/agent-harness-v2.md)，新门槛与旧实施证据分别见 [验收 §0.12 / §0.11 / §0.10](docs/m1-acceptance.md)。旧「已有」只说明基础存在，不保证新目标完成。先独立文档 commit/push，后续实现按契约分批验证与提交；本轮文档检查点推送成功后连续实施，不在文档完成处停止；各批实际证据另记。新图标候选按 [品牌记录](brand/README.md) 交 Rex 选择，正式 V8 保留至明确接受。
