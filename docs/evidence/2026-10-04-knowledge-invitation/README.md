# 答题后新增知识邀请与状态指代修复 · 2026-10-04

KT-01 / KT-02 已实现并更新到本机日常 App；服务回归、真实模型定向回放和原生隔离交互已分项通过。**真实模型＋原生写入的单次端到端链路、完整 VoiceOver 及 Rex 体验验收仍开放**。规则见 [DESIGN](../../../DESIGN.md#knowledge-save-invitation)、[决定 212–215](../../decision-log.md)，执行位置统一见 [工作状态](../../work-status.md)。历史错例与修订关系见 [迭代记录](../../agent-iteration.md)。

本批保留用户点击前不生成或写入、本题知识范围、同范围去重、追问／纠正更新范围、其他新知识不自动合并及保存与复习分离。KT-02 将自然主题概括与精确来源证据分开；无效首要引用不能静默退回旧泛主题，保存状态须对应被问来源与真实回执，多个范围保守说明，纠错不重贴长旧引文。

## 证据层级与当前结果

| 层级 | 证据 | 本次能证明的结论与限制 |
|---|---|---|
| 初次受控全量 | [controlled.txt](controlled.txt) | 1035 passed、4 skipped、470 subtests passed；临时数据库、空供应商凭据。属于后续修订前的初次结果，不能代替最终回归。 |
| 最终受控全量 | [controlled-final.txt](controlled-final.txt) | 1053 passed、4 skipped、475 subtests passed；406.15 秒。包含最终后端规则、精简反馈、保存失败纠正和重试中断恢复。5 条既有弃用告警未作为错误忽略。 |
| KT-02 受控联调 | [迭代中的定向记录](../../agent-iteration.md) | 六组定向 96 passed、35 subtests passed，覆盖自然概括、混合有效／无效引用、一次恢复上限、已保存旧邀请、部分覆盖及多邀请；同样不是本批最终全量。 |
| KT-02 真实固定历史 | [status-history-r1.jsonl](status-history-r1.jsonl)、[日志](status-history-r1.log)、[复核](status-history-r1-review.json) | 两轮完全相同问句通过，各一次 DeepSeek Flash 入口调用；主题不退回旧切块，首轮简短纠错、次轮不重复，学习／邀请／草稿／旧历史不变。共 30,459 tokens。仅两轮合成历史，网页和知识写入被阻断，未测原生保存。 |
| 邀请真实生成流程 R1 | [live-synthetic.json](live-synthetic.json)、[日志](live-synthetic.log) | 邀请、范围更新、新主题不混入、生成及模拟 Mac ACK 有记录，但保存后查询仍误报未整理。原脚本虽打印 PASS，当时缺保存查询断言，不能据此认定整链通过；该失败保留。 |
| 邀请真实生成流程 R2 | [live-synthetic-r2.json](live-synthetic-r2.json)、[日志](live-synthetic-r2.log) | 答题后邀请成立；同知识点追问后范围未更新，断言失败并停止，后续保存／查询未完成。 |
| 邀请真实生成流程 R3 | [live-synthetic-r3.json](live-synthetic-r3.json)、[日志](live-synthetic-r3.log) | 作答评估阶段出现 `RT.MODEL.SCHEMA`，未生成该轮回复；当时未保留字段诊断，无法追溯具体失败字段，不推断原因。 |
| 邀请真实生成流程 R4 | [live-synthetic-r4.json](live-synthetic-r4.json)、[日志](live-synthetic-r4.log) | 邀请、同点追问、纠正范围替换、新主题不混入均通过。第 6 轮生成后的核验未通过，系统暂停写入并提供重试；未收到 ACK，未宣称保存成功。此轮没有完成后续已保存查询。 |
| 邀请真实生成流程 R5 | [live-synthetic-r5.json](live-synthetic-r5.json)、[日志](live-synthetic-r5.log)、[用量与检查](live-review.json) | 最终 7 轮通过：无预生成、同邀请补充／纠正、不同知识不合并、真实生成核验到 committing、模拟 ACK 后 saved，切换主题后询问原范围仍答已保存。生成 2 张卡；模拟 ACK 不是原生写入。 |
| 最终原生隔离交互 | [原生最终记录](native/README.md) | 两组原生合同通过；紧凑呈现、AX 最新范围、中文草稿／焦点／滚动保持、点击 v2、默认不复习、真实隔离 SwiftData 保存及查看、深色窄窗／减少动态验证。原生使用合成后端和保存载荷，未连真实模型。 |
| 原生隔离交互 v1 | [原生记录与录像](native/README.md) | 模拟后端邀请／答题，使用真实隔离 SwiftData 保存、失败重试及查看入口，无模型调用。v1 录像和截图为简化呈现前证据；最终紧凑版与范围刷新复验须单独记录。 |

R1–R3 的早期邀请记录未正确保留完整调用用量和结构诊断；其中 `model_calls=0` 不能解释为没有模型调用，也不能据此估算费用。R4 的补充记录不倒填旧批次。

## 失败与修复的关系

R1 的保存后查询误报由状态按被问范围匹配邀请／回执修复；R5 真实回放覆盖保存后先聊另一主题再回查。R2 的路由没有任务漂移，隔离模拟表明返回 null 就会维持旧范围；增强同知识点的条件／限制／时效边界更新要求后，R4、R5 均实际更新。R3 具体字段未保留，不能把后续一次通过说成已定位并修好该次所有原因。R4 的知识核验拦截保留为真实失败，不降低门槛追求通过。模型表达、选段和知识质量仍有波动，少量通过不证明所有主题稳定。

额外受控回归发现并修复：四个邀请后的最早范围仍可更新、重叠概念不重复邀请、同一步多个邀请纠正互不误伤、保存失败后仍更新原邀请、首次及重试在生成前中断后不会卡在保存中；已取得本机写入许可的任务继续等待真实回执。

## 本机生效与数据保护

[Debug 构建](build-debug.log)和严格签名验证通过；保留 `Rex.Review-Today`／`7NDKLL3UJK` 身份。无活跃轮次或待提交任务后，正常退出，先备份原 App、SQLite 和听写文件，再替换本地 Debug 构建并重启。未改变供应商、Jev 开关或生产发布状态。

[安装与核对](local-install.json)：服务 healthz 正常，router／coach／risk ready，Jev off。Mac 的 5 会话、24 消息、8 知识、11 题、4 复习轮次、3 作答保持；消息、知识、题目与复习业务字段逐字段不变。会话的保存邀请版本与 checkpoint／recovery 同步元数据刷新，未将其写成完全零变更。服务 33 会话和 13 任务逐行与备份相同，数据库完整性为 ok。真实窗口打开正常，“今天”显示原来的 8 条知识。

备份在项目忽略目录 `output/knowledge-invitation-backup-20261004-211308`，不提交私人数据库或完整聊天。工程文件 `project.pbxproj` 在本轮前已有 24 行新增／10 行删除，差异摘要保持，未纳入本轮提交。

## Rex 体验路径与剩余边界

Agent → 继续学习并完成一次新的有效独立作答 → 查看反馈下的知识名、具体范围和“新增知识／稍后”。继续追问同一点时范围应更新；点击新增知识后才整理保存，成功后可查看。已有旧气泡不重写，也不为旧答题补播邀请。精简截图见[最终浅色](native/invitation-compact-final.png)；顶部预览／隔离标记与连接提示属于 QA 夹具，不是日常邀请文案。

受控、模型和原生三个层级分别通过，不合并声称同一次真实模型到原生落盘全链路已验收。完整 VoiceOver、长期教学质量、真实模型失败频率和 Rex 最终视觉／使用体验仍开放；M1 总体验收不关闭。

复跑：`bash agent-service/run-controlled.sh`；原生 `bash tests/mac/run-topic-capture-native.sh`。真实模型脚本 `agent-service/tests/knowledge_invitation_real_smoke.py` 需要 `--live --output <全新文件>`，使用隔离库和现有供应商，会产生用量。R5 共 21 次调用、179068 个已报告 token；历史不完整记录不外推费用。最后仅改进诊断记录的 smoke 字段，不计为另一次在线执行。

日志归档仅清理行末空白；未删改失败、告警或测试结果。
