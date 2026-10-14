# EVAL-01：状态覆盖与连续学习检查

2026-10-14，沿 TARGET-01 后的位置只读检查。**本轮十二阶段受控连续流程、55 项服务测试／10 子场景及三组原生合同通过，未复现新的确定性状态缺口。仍缺同一次真实教学到原生保存的贯通证据，以及教学／评分内容的独立审阅。** 没有修改生产行为、调用真实供应商或更新日常 App。

## 从 ZCode 参考什么

固定版 [`29628c9`](https://github.com/zai-org/ZCode/tree/29628c9acdb81b703bbd4080c207a0e7ce5e276e) 的 [formal-proof 说明](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/packages/formal-proof/README.md)将它定义为产品行为状态空间枚举器。[model.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/packages/formal-proof/src/model.ts)按运行、队列、目标等状态枚举操作，给出 guard、结果与后续状态；其中 E2E 字段是断言文字，不是实际 App 执行结果。

可以参考“当前状态 × 用户操作／系统事件 → 预期结果”的检查方法。[projection-state.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/bootstrap/src/zcode-protocol-v4/projection-state.ts)确有可执行的操作可用性和输入路由裁决，并引用模型中的规则标识。两处源码注释都提到 `formal-proof-consistency` 黄金测试；本次未在固定版公开树中找到这个名称的测试文件，也没有运行它，不能据注释宣称测试已通过，更不能把枚举结果当作 Review Today 教学质量证明。

本次只读上游源码与公开文件树；首次 Python 请求因本机证书链失败，随后使用正常 TLS 校验的 curl 成功，没有跳过证书校验。来源、散列和执行边界记在 [review.json](review.json)。

## 本项目已有覆盖与真正缺口

已有 [用例目录](../../../agent-service/tests/fixtures/agent_cases/catalog.json)、[用例规则](../../../agent-service/tests/case_library/schema.py)与[追加式回放记录](../../../agent-service/tests/case_library/recording.py)，支持真实固定上下文和真实生成前文两层，自动检查、语言审阅与 Rex 验收分别记录。目录的 17 条案例仍标记 `pending`，表示验收尚未关闭，不能据此认定 17 项都未实现；后续具体证据应与目录一起查。无需为这一轮新建评测框架。

| 需要检查的行为 | 已有证据 | 本轮补查 | 仍未证明什么 |
|---|---|---|---|
| 无卡学习，答题后出现未保存邀请 | [KT-01／KT-02](../2026-10-04-knowledge-invitation/README.md) 的真实生成流程 R5：7 轮、21 次真实调用；Mac 回执模拟 | 连续流程 1–2：无预生成，邀请仍无卡片 ID | 本次没有重新验证真实出题／评分的语义质量 |
| 补充、纠正、稍后、切换主题与旧版本保存 | R5 与现有邀请／范围回归 | 连续流程 3–8：同邀请更新、错误片段替换、另题不混入、旧版本不能生成 | 自然语言路由与纠正识别仍可能波动 |
| 小题不等于整节；综合检查需完整答案 | [SCOPE-01](../2026-10-13-conservative-check-scope/README.md) 的最终五阶段真实固定上下文回放与原生作答；[TARGET-01](../2026-10-14-target-verification/README.md) 的受控完成边界 | 当前流程全过程整步理解仍为 `unknown`，保存没有授予整步掌握 | SCOPE 前文来自既有教学对象；旧评分误判保留，通用评分稳定率未验 |
| 生成不等于保存；真实落盘后才回执 | R5 为真实生成＋模拟 ACK；[原生检查](../2026-10-04-knowledge-invitation/native/README.md)为模拟服务＋真实隔离落盘，两层分开 | 流程 9–10 验服务 ACK 边界；原生合同另验真实临时磁盘、失败回滚与独立读上下文 | 同一次新生成真实教学到真实原生卡片保存尚未贯通 |
| 重复回执、恢复与学习进度保持 | 既有保存恢复与目标连续性检查 | 流程 11–12、三组原生合同：不重复生成，不自动续讲，归属与恢复守卫保持 | 本轮没有真实窗口操作、日常关闭重开或完整模型恢复链 |
| 知识卡是否抓住要点、提示是否易懂 | 已实现标题／要点／一句总结和保存后查看入口；旧窗口证据须按版本看待 | 预览与完成提示的合同检查 | 当前最终视觉、完整 VoiceOver、教学自然度和 Rex 使用体验另验 |

## 本次实际执行

[continuous_trace.py](continuous_trace.py)复用既有邀请夹具，执行真实服务状态转移；路由、教学、评分、生成与 Mac ACK 受控，后台摘要关闭。使用临时 SQLite，不使用 `RunReport` 的 `live_*` 标签。

同一会话、同一邀请的十二阶段记录见 [continuous-trace.json](continuous-trace.json)：

1. 未有卡片时正常学习，不生成邀请或完整卡片。
2. 受控答题通过后出现 v1 邀请，仍未保存。
3. 同知识点补充更新原邀请为 v2。
4. 选择稍后后保持待录入，学习可继续。
5. 纠正替换候选来源；失效及替换各升版，记录为 v4，仍待录入。
6. 旧显示版本 v2 的保存请求不触发生成。
7. 另一知识点回答不进入原邀请。
8. 明确保存最新 v4，生成输入与被点击的纠正范围一致，仅调用一次生成替身。
9. 生成到 `committing` 时邀请仍是保存中，无已保存卡片 ID。
10. 匹配的模拟 Mac ACK 才确认服务 `saved`，原学习任务及步骤恢复。
11. 重复 ACK 不重复生成或自动续讲。
12. worker 恢复后保持已保存结果。

首轮十二阶段已通过，[初始记录](continuous-trace-initial.json)保持原内容。复核记录字段后，补充直接读取原学习步骤的理解状态，并逐阶段断言为 `unknown`；最终连续复跑十二阶段通过，不能把活动任务切换期间的默认字段当作整步理解证据。初始英文标签中的 `saved scope candidate` 指待保存候选，并非实际落盘，最终标签已明确为 `unsaved`。该流程没有真实原生写入，不把模拟 ACK 写成完整保存链。

服务四文件检查：**55 passed、10 subtests passed、5 条既有 warning**，见[服务日志](service-tests.log)。新编译支持模块后，`TopicCaptureContractTests`、`KnowledgeIngestionTests`、`LearningGoalContinuityTests` 三组通过，见[原生日志](native-contracts.log)。其中入库合同用临时磁盘 SwiftData，检查保存失败回滚、通知时独立读取完整卡片、归属、默认不参加复习、重复与 ACK 恢复；其余为受控页面／内存状态，不是原生 UI 验收。编译弃用、并发捕获、sourceLocation 和重复 rpath 警告保留，不扩入本轮修复。

两个日志仅清理行尾空白以通过仓库格式检查；原始副本路径和前后散列记录在 review.json，没有删改警告或测试结果。生产文件与供应商配置散列保持；工程既有修改未动，不提交日常数据库或原生二进制。

复跑受控连续流程：在 `agent-service` 中执行 `PYTHONPATH=. .venv/bin/python ../docs/evidence/2026-10-14-evaluation-coverage/continuous_trace.py`。服务测试须在导入前设置临时 `REVIEW_TODAY_HARNESS_DB` 和仅用于夹具的 `REVIEW_TODAY_LLM_PROVIDER=openai_compatible`，运行上述四文件。原生入口：`python3 tests/mac/run-contracts.py TopicCaptureContractTests KnowledgeIngestionTests LearningGoalContinuityTests`。这些入口不需要真实供应商调用。

## 下一步建议：只贯通一条真实学习流程

这是待对齐的验证范围，不新增产品规则，也未在本轮执行。沿 QA-01，使用现有模型配置、隔离服务库与独立原生存储，验证一个 RAG 知识点：

| 顺序 | 用户可见动作／内容 | 必须核对的结果 |
|---|---|---|
| 1 | 从无卡状态开始真实讲解并出题 | 前文由本次模型生成；题目和要求对应本知识点 |
| 2 | 先漏答一个明确必要条件，再完整作答 | 漏答不误判通过；完整答题只验证对应概念，不授予整节掌握 |
| 3 | 查看答题后知识卡预览 | 标题、少量要点、一句总结准确；无预生成或自动保存 |
| 4 | 同知识点补充／纠正，再询问另一主题 | 原邀请更新到真实最新范围，另题保持分开 |
| 5 | 在原生窗口点击当前版本的保存 | 进入已有生成／核验流程，保存内容对应当时范围 |
| 6 | 等待实际写入与完成反馈 | 独立读取真实卡片、来源、任务／会话归属；之后才确认服务回执，复习默认关闭 |
| 7 | 打开详情，并询问原范围是否保存 | 详情与实际卡片一致，查询依据真实保存事实 |
| 8 | 检查原学习进度 | 原目标和步骤保留，保存不自动升级理解或推进教学 |

建议这批实际模型请求合计最多 30 次（包括实际重试），到上限或遇失败即停止并留证，不扩入整改；此上限是待确认的隔离试跑预算，不改日常配置。执行前对齐预算与验收范围；执行时记录实际请求、用量、每阶段状态与失败原因。失败保留，未执行阶段明确列出；服务自动检查、教学／评分内容审阅、原生操作和 Rex 验收分别判断，单条成功不外推所有主题。既有记录器的知识写入阻断边界保持，真实原生保存另记录实证，不把受控回执冒充真实写入。

工作续接见 [EVAL-01](../../work-status.md#eval-01)，研究位置见[第 7 条第四小点](../../design-references/zcode-agent.md#topic-7-4)。
