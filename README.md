# Review Today

Review Today 是原生 macOS 个人学习教练：帮助用户理解资料、探索主题、攻克问题，并按用户选择将学习内容整理为知识卡、参与复习。

## 从这里开始

| 想做什么 | 入口 |
|---|---|
| 查某个功能、规则、实现或证据 | [文档导航与功能索引](docs/README.md) |
| 看已确认待办、本轮做到哪、下次从哪里继续 | [当前工作与续接记录](docs/work-status.md) |
| 修改 Agent 行为 | [Harness 主规格](docs/agent-harness-v2.md) |
| 修改界面或交互 | [设计规范](DESIGN.md) |
| 判断是否已验证、能否验收 | [M1 验收契约](docs/m1-acceptance.md)与[迭代记录](docs/agent-iteration.md) |

## 项目状态

- 已有 SwiftUI App、SwiftData 长期数据、本机 Python Agent 服务及短期 SQLite checkpoint；学习、知识卡、复习和语音已有实现或已接入 POC，各自验证范围见功能索引。
- M1 总体验收仍开放。代码存在、单项测试通过、模型回放通过和 Rex 体验验收是不同状态。
- 开发分支为 `codex/jev-comparison-evaluation`。9 月 6 日的“已合入 main／分支清理”是[当时的快照](docs/m1-branch-audit.md)，不能代表之后的增量已合入。
- 本轮已整理文档入口与续接记录。已确认的“答题通过后出现新增知识提示”尚未实施；知识卡状态回复的主题过滤缺陷已复现待修。详情统一记录在[当前工作](docs/work-status.md)。
- GitHub 用于版本管理；验证在本地执行。普通提交推送不代表合并、最终发布或关闭验收。

历史批次的结果、失败与限制保留在[迭代记录](docs/agent-iteration.md)、[验收契约](docs/m1-acceptance.md)及它们链接的证据目录中，不在主页重复维护测试数字或旧“当前状态”。

## 开发与验证入口

日常使用正常 Debug App，由 App 托管本机服务。不要把预览或隔离验收实例当作日常运行证据。

| 用途 | 入口与边界 |
|---|---|
| 服务受控回归 | `bash agent-service/run-controlled.sh`；使用隔离数据和空供应商凭据 |
| 原生契约检查 | `bash tests/mac/run-contracts.sh` |
| 迁移检查 | `bash tests/mac/run-migration.sh`；不要用日常数据库作测试对象 |
| 真实模型冒烟 | 在 `agent-service` 运行 `.venv/bin/python -m tests.stream_real_smoke`；使用合成输入与临时库，会产生 API 用量 |
| 原生真实验收 | 独立 `.NativeQA` 实例与临时目录；见[M1 开发运行与真实链路记录](docs/m1-acceptance.md#015-紧凑顶部与真实运行入口2026-09-06) |
| Jev 隔离交互 | [启动脚本](tools/run-jev-app-test.command)与[验收记录](docs/evidence/2026-09-21-jev-app-test/README.md)；不代表日常默认启用 |

原生隔离运行使用 `REVIEW_TODAY_NATIVE_TEST_DIR` 指向临时 `review-today-` 目录，独立端口默认 18742，不使用日常 8742。`REVIEW_TODAY_M1_UI_FIXTURE=learning` 仅为内存界面预览。

Debug 日常构建沿用工程配置的 Apple Development 签名；其他开发者在 Xcode 选择自己的 Team。独立编译检查可用 `CODE_SIGNING_ALLOWED=NO`，不能将未验证签名的构建当作日常 App。不要为了普通运行自动扩大系统权限。

## 本机配置与数据

- Mac 本地数据是 Session、消息、学习任务、知识与复习历史的长期事实来源；服务 checkpoint 用于执行与恢复。存储与提交边界见[架构](docs/architecture.md)。
- 文本模型使用显式 provider 配置，当前开发基线为 DeepSeek；角色与恢复规则见[Harness 主规格](docs/agent-harness-v2.md)。历史 provider 名称不代表当前运行配置。
- `agent-service/.env` 选择 provider；DeepSeek 凭证位于被 Git 忽略的 `agent-service/providers/deepseek/.env`，权限应为 600。只查脱敏健康状态，不在文档或日志中复制密钥。配置变化后需核对真实服务生效情况。
- 网页检索／读取是独立工具，配置、服务顺序与预算见[网页工具说明](agent-service/providers/web/README.md)。语音配置见[ASR 说明](agent-service/providers/asr/README.md)。
- 历史数据迁移或清理须按[工具说明](tools/README.md)与对应验收记录执行，不从旧进展段落推断今天的数据情况。

## 文档怎么维护

先用[文档导航](docs/README.md)找到负责该规则的文件。产品规则变动同步主规格／设计，工作进度只更新[工作记录](docs/work-status.md)，实际验证写入迭代与验收证据；不把研究建议、方向确认或文档完成写成已实现。
