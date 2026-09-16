# A006 / A007 验证记录

## A006

2026-09-17，使用合成输入与临时数据库；未向正常用户会话写入测试消息。

- 服务：`PYTHONPATH=/tmp/review-today-topic-test-deps-20260915 bash agent-service/run-controlled.sh`：324 passed，34 subtests passed。
- 原生：`bash tests/mac/run-contracts.sh`：20 套执行契约及真实本地 SSE 通过；通用问句词不误召回知识卡片。
- 模型：`cd agent-service && .venv/bin/python -m tests.dialogue_routing_real_smoke --live`：2 轮通过，输出见 live-a006.jsonl。首问直接回答；第二轮模拟历史错误后正确修复。
- A006 原生分词回归通过；错误对话的真实模型修复已复测。原生与真实模型连通的完整对话验收、Rex 体验验收仍开放。

## A007

2026-09-17 实现完成，分层自测通过，待 Rex 验收。

| 验证层次 | 实际结果 |
|---|---|
| 服务完整回归 | 342 项、34 子场景通过；随后批量写入只更新变化记录的微调及新增原子失败用例，26 项定向回归通过。见 service-tests.txt |
| 原生契约 | 21 套独立可执行测试与本地真实 SSE 通过；唯一进度计数、旧数据默认身份、历史导航、陈旧投影与恢复保护。见 native-checks.txt |
| 持久化/构建 | 旧磁盘 schema 自动迁移通过，旧会话/来源/知识/复习/草稿保留；普通 Debug Apple Development 签名构建成功 |
| 真实模型 | 5 轮隔离会话：唯一匹配直接续学、多目标只问具体对象、选择后接续、不相关目标与无记录均不新建课程；见 live-a007.jsonl |
| 原生窗口 | 正式 LearningWorkspace 与持久化模型，合成进度、隔离数据库。历史入口→当前进度→旧步骤回看；1040×820 浅色、720×680 深色/减少动态；可访问性树中按钮名称与禁用步骤正确 |
| 日常开发版 | 确认无执行中任务/入库后重启；原会话与旧回复保留；8742 healthz 正常，router/coach/risk ready，新 continuation/sources 接口返回 200 |

### 真实回放发现并修正

- 初版“继续上次没学完的光合作用”被模型归为 continue_goal，却漏填续学证据，落入旧分支后创建课程并编造上次内容。保留脱敏结果于 live-a007-regression.json。
- 修复：无当前目标的 continue 不得直接创建课程；缺失字段时再核对本轮续学意愿，随后必须匹配实际记录。无记录/不匹配只说明事实。复测未创建任务。
- 多目标候选按稳定顺序展示，用户选择后按同一顺序匹配；编号与名称矛盾不得自行选取。
- 旧会话里的普通“继续”引导到当前进度，不另建同名目标；失败重试不重复创建/推进；旧快照无论先后恢复都不能抢回归属。
- 补测跨会话写入中途失败：两侧同时回滚，旧目标仍有当前归属；未变化的历史任务不刷新更新时间。
- A006 追加覆盖：历史已经错误反问两次后，纠错仍定位到原始问题，而非上一条抱怨；模型给出的原问题 ID 必须能在当前会话核实。

### 原生窗口证据

- [历史会话入口](native-history-light.png)、[当前进度](native-current-light.png)
- [深色窄窗历史](native-history-dark-narrow.png)、[深色窄窗续学](native-current-dark-narrow.png)

截图的隔离标识与“不连接学习服务”是 QA 外壳刻意设置。它验证实际窗口与跳转，不代表真实模型到原生同步的全链路。真实模型、服务原子性和原生投影分别验证；尚未执行大规模长会话性能、完整 VoiceOver 朗读及所有自然语言变体验收。

### 复跑与 Rex 验收

- 服务：`bash agent-service/run-controlled.sh`；本机临时 pytest 依赖路径仍按 A006 命令设置。
- 原生：`bash tests/mac/run-contracts.sh`；`bash tests/mac/run-migration.sh`。
- 模型：在 agent-service 运行 `.venv/bin/python -m tests.goal_continuation_real_smoke --live`。
- 窗口：`bash tests/mac/run-goal-continuity-native.sh`，独立 bundle 和临时 SwiftData 库。
- Rex：新会话问“什么叫 harness”，应直接解释；明确继续一个实际未完成的主题，应显示上次进度并续学；存在多个同主题目标时只选择具体目标。旧会话显示“已在另一会话继续”，点击进入当前进度。
- 历史错误回复保留原文；修复对后续输入生效。最终体验验收由 Rex 完成。
