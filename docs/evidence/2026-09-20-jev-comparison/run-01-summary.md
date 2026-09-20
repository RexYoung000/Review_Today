# Jev / DeepSeek 局部判断对照

本报告只衡量固定合成材料上的局部判断，不是完整会话、App 性能、权限执行或掌握状态验收。

执行完整：False；全部断言命中：False。
needs_review 仅统计 unsure 或调用失败；并未据此校准自动接管阈值。DeepSeek 自报概率不视为已校准。

| 模型 / 类别 | 有效 / 计划 | 整例命中 | 判断命中 | 待复核 | 耗时中位数 / 范围 ms | 已知费用 USD 范围 |
| --- | --- | --- | --- | --- | --- | --- |
| jev/dialogue | 31/31 | 23 | 206/217 | 1 | 391.982 / 318.491–980.107 | [0.00275285, 0.00275285] |
| jev/memory | 6/6 | 6 | 14/14 | 0 | 368.7795 / 343.108–510.049 | [0.00022781, 0.00022781] |
| jev/source | 6/6 | 4 | 12/14 | 0 | 373.7615 / 334.205–2527.12 | [0.00023785, 0.00023785] |
| jev/grading | 12/12 | 12 | 54/54 | 0 | 752.421 / 564.669–1385.651 | [0.00063113, 0.00063113] |
| deepseek/dialogue | 25/31 | 20 | 168/175 | 7 | 1916.746 / 1643.511–2151.077 | [0.01063046, 0.02126092] |
| deepseek/memory | 6/6 | 5 | 12/14 | 0 | 1027.4769999999999 / 783.403–1126.032 | [0.00095168, 0.00190337] |
| deepseek/source | 6/6 | 4 | 11/14 | 1 | 2418.897 / 2070.008–3440.285 | [0.0049768, 0.00995359] |
| deepseek/grading | 11/12 | 11 | 49/49 | 1 | 1220.844 / 939.367–1525.757 | [0.00264948, 0.00529896] |

## 所有差异与失败

- jev / A001-defer-active / conversation_kind：期望 ordinary，实际 companionship，confidence=0.39。
- deepseek / A001-defer-active / conversation_kind：期望 ordinary，实际 learning_support，confidence=0.85。
- deepseek / A006-repair-question：error / invalid_response
- jev / A006-repair-question / conversation_kind：期望 ordinary，实际 social，confidence=0.67。
- jev / A006-repair-question / knowledge_request：期望 yes，实际 no，confidence=0.45。
- deepseek / A007-resume-missing：error / invalid_response
- jev / A010-local-example / knowledge_request：期望 yes，实际 no，confidence=0.25。
- deepseek / A011-stable-concept：error / invalid_response
- deepseek / A012-rest：error / invalid_response
- deepseek / A012-learning-support / progress：期望 none，实际 defer，confidence=0.6。
- deepseek / A012-mixed-question：error / invalid_response
- jev / A013-local-transition / conversation_kind：期望 ordinary，实际 social，confidence=0.77。
- jev / A013-foreign-goal-transition / conversation_kind：期望 ordinary，实际 social，confidence=0.39。
- jev / A015-capability / resource_boundary：期望 capability_question，实际 resource_delivery，confidence=0.84。
- deepseek / A015-continue-errand / conversation_kind：期望 ordinary，实际 unsure，confidence=0.55。
- deepseek / A015-continue-errand / knowledge_request：期望 no，实际 unsure，confidence=0.4。
- deepseek / A015-continue-errand / progress：期望 none，实际 resume_prior，confidence=0.5。
- jev / A015-continue-errand / conversation_kind：期望 ordinary，实际 unsure，confidence=0.42。
- jev / A015-continue-errand / progress：期望 none，实际 clarify_next，confidence=0.56。
- jev / A015-continue-errand / resource_boundary：期望 resource_delivery，实际 none，confidence=0.6。
- deepseek / A015-quoted-request：error / invalid_response
- deepseek / A015-mixed-knowledge / resource_boundary：期望 mixed_learning，实际 resource_delivery，confidence=0.85。
- jev / A015-mode-and-errand / progress：期望 none，实际 clarify_next，confidence=0.47。
- deepseek / A017-internal-material / knowledge_request：期望 yes，实际 no，confidence=0.7。
- deepseek / memory-weak / m1：期望 weak，实际 irrelevant，confidence=0.9。
- deepseek / memory-weak / m2：期望 weak，实际 irrelevant，confidence=0.9。
- deepseek / source-direct / s2：期望 weak，实际 irrelevant，confidence=0.88。
- jev / source-direct / s2：期望 weak，实际 irrelevant，confidence=0.93。
- jev / source-weak / s2：期望 weak，实际 irrelevant，confidence=0.59。
- deepseek / source-official / s1：期望 relevant，实际 unsure，confidence=0.4。
- deepseek / source-official / s3：期望 relevant，实际 unsure，confidence=0.4。
- deepseek / grade-photosynthesis-mixed：error / invalid_response

## 计量边界

- 每个样例每方一次有效判断；瞬时错误最多额外一次，失败也保留。首个请求 cold_start 单列于原始记录。
- 候选只按明确 relevant 进入建议清单，同档保留输入顺序；去重、官方域名与数量限制由程序执行。未评测概率排序的长期收益。
- 判断总数仅分母 questions_scored 是有效请求；失败/缺失另计，不能当作正确。
- 费用是价格快照下的估算范围，不是账单；输出概率是模型结果，不是本业务正确率。
- 输入含合成前文和任务/其他目标状态；标准答案与来源注释没有发送给模型。
- 未运行完整 Harness 或原生 App；无法据此认定现有工作流可以被直接替换。

价格核对日：2026-09-20；[TypeSafe](https://docs.typesafe.ai/models)；[DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/)。
