# M1 纯文字最小闭环验收契约

> 状态：M1 固定验收基线
> 对应 Issue：[#9 M1.1：冻结最小闭环验收契约与固定样本](https://github.com/RexYoung000/Review_Today/issues/9)
> 机器可读样本：`agent-service/tests/fixtures/m1_acceptance.json`

## 1. 唯一验收命题

M1 只验证：

> 用户提供一段稳定知识内容后，系统能否形成一张忠于原文、可以被提问和判断的知识卡，并正确区分用户的正确与明显错误文字回答？

M1 证明一条真实纵向链路可用，不证明模型已经能稳定处理所有知识类型和边界回答。

## 2. 固定样本

### 2.1 用户输入

```text
光合作用是植物利用光能，把二氧化碳和水转化为有机物，并释放氧气的过程。
```

选择这个样本的原因：

- 只包含一个稳定概念，正常情况下应生成一张知识卡；
- 原文同时包含能量来源、输入、产物和伴随释放物，适合检查知识卡是否遗漏关键点；
- 不涉及时效、精确数字、医学、法律或金融，不应触发联网核验；
- 正确与错误回答边界清晰，适合验证最小评分闭环。

### 2.2 正确回答

```text
植物借助光能，用二氧化碳和水合成有机物，同时释放氧气。
```

预期：未使用提示时返回 `good`。回答完整覆盖原文的四个语义要点，没有引入冲突信息。

### 2.3 明显错误回答

```text
光合作用就是植物从土壤里直接吸收有机物。
```

预期：返回 `again`。回答把“利用光能合成有机物”错误说成“直接吸收有机物”，且遗漏二氧化碳、水和氧气。

## 3. 知识卡最小契约

服务必须生成且 Mac 必须保存至少以下内容：

| 字段 | M1 要求 |
|---|---|
| 知识数量 | 固定样本生成且只生成 1 张知识卡 |
| `title` | 能独立识别为“光合作用”，不是说明句、半截标题或空分类 |
| `explanation` | 用简体中文覆盖光能、二氧化碳与水、有机物、氧气；允许不同分点和措辞 |
| `evidence_excerpt` | 必须是用户原文的连续子串，不得翻译或补写模型常识 |
| `knowledge_type` | `concept` |
| `theme` | 明确指向“光合作用”，不得使用“知识”“技术”“其他”等空主题 |
| 语言 | 内容、默认问题和预期回答均使用简体中文语境 |
| 主问题 | 存在 `variant_index = 0` 的开放式主动回忆问题，不是是非题 |
| `scoring_spec` | 语义上覆盖光能、二氧化碳与水、有机物、氧气，并保留原文证据 |

问题不要求逐字固定，但必须能通过上述评分关键点判断用户是否理解光合作用过程。

### 3.1 M1 capture 稳定字段

M1.4 Mac 客户端可以直接依赖以下服务字段：

- 任务层：`task_id`、`status`、`user_status`、`error_code`、`receipt`、`result`；
- 回执层：`understood_as`、`theme`、`knowledge_count`、`attribution`；
- 知识层：`id`、`learning_goal`、`knowledge_type`、`theme`、三类语言字段、`evidence_excerpt`、`evidence_locator`、`title`、`explanation`、`scoring_spec`、`questions`；
- 评分规格：`learning_goal`、`must_cover`、`acceptable_paraphrases`、`common_misconceptions`、`evidence`、`order_rules`；
- 问题层：`variant_index`、`prompt_text`。

服务端必须在进入 `committing` 前完成以下硬校验：

- 每个知识 `id` 是有效且批次内唯一的 UUID；
- 每张知识卡恰有一个 `variant_index = 0` 的主问题，问题序号不得重复；
- `evidence_excerpt` 与 `scoring_spec.evidence` 都是当前来源原文中的非空连续子串；
- 结构或来源忠实性不合格时不返回可提交结果，也不能进入 `completed`。

### 3.2 任务幂等与重试语义

- 同一 `task_id` 处于 `processing`、`committing` 或 `completed` 时，重复提交只返回同一任务，不生成第二份服务结果，也不重复入队；
- 同一 `task_id` 处于 `retryable_failed` 时，重复提交允许将原任务重新置为 `processing` 并入队，但仍复用同一任务记录；
- 用户主动 `reprocess` 同样复用原任务记录，不创建第二份知识结果；
- 没有 Mac ACK 时任务必须保持 `committing`；仅当 ACK 中的 knowledge IDs 与服务结果完整匹配时才能进入 `completed`。

### 3.3 Mac 本地提交语义

#12 的 Mac 端必须先建立可持久读取的 `Source` 与 `CaptureTask`，再异步提交服务：

- 本地任务使用稳定的 `task_id` 与 `source_id`，服务不可用时保留原始文字和队列记录；
- `processing`、`committing` 和 `completed` 按任务 ID 轮询，不能把提交响应的 `processing` 当作完成；
- 服务返回 `committing` 后，Mac 先按服务知识 ID 幂等写入 `Knowledge`、`Question`、评分规格和 `FsrsState`，本地保存成功后才发送知识 ID ACK；
- 本地写入或 ACK 失败时保留任务和原始输入，不显示为完成；下一次轮询可继续提交，不插入重复知识；
- `retryable_failed` 是可恢复状态，待处理入口和首页计数必须可见，并提供重新整理操作。

### 3.4 M1 review 评分契约

评分请求稳定包含 `attempt_id`、`prompt_text`、`scoring_spec`、`answer_text`、`hint_used` 与 `primary_language`。其中 `answer_text` 是用户原始自然语言回答：服务可以检查它是否为空，但不得先改写、提取关键点或增加独立预结构化模型调用；Mac 负责将原始回答保存在 `ReviewAttempt.answerText`。

服务端必须保证：

- 空白回答在调用模型前以 HTTP `422` 拒绝，不生成等级；
- 评分模型同时获得问题、学习目标、必答点、可接受同义表达、常见误解、原文证据、顺序规则、提示状态和原始回答；
- `agent_grade` 只能是 `again`、`hard` 或 `good`，模型输出 `easy` 或其他结构错误时必须失败，不能转换成有效等级；
- 使用提示后，即使模型返回 `good`，服务也必须程序化降为 `hard`；
- `brief_feedback` 必须非空、简短并使用用户主语言；
- 同一 `attempt_id` 首次评分成功后，重复评分返回同一缓存结果，不再次调用模型；评分失败不缓存伪结果，允许用同一 ID 重试；
- 只有已经产生有效评分结果的 `attempt_id` 可以 ACK；错误 ID 必须拒绝，重复 ACK 保持幂等；
- 模型、网络或结构化评分失败返回 `RT.REVIEW.GRADE_FAILED`，不能产生 ACK、有效等级或“已掌握”状态。

评分响应稳定包含 `attempt_id`、`agent_grade`、`brief_feedback` 与 `hint_used`。服务内评分结果与 ACK 仍是 M1 的内存状态，服务重启恢复不在本里程碑验证范围内。

### 3.5 M1 文字答题客户端契约

- 每道当前题先创建一个 `ReviewAttempt`，原始 `answerText` 在请求评分前写入 SwiftData；空白回答不得创建或提交有效评分。
- 答题页在 `grading` 期间锁住提交入口；评分失败保留当前题、原始回答和同一个 `attemptId`，允许修改原回答后重试，不推进下一题，也不写入 `agentGrade` 或 `effectiveGrade`。
- 评分成功只展示 `again`、`hard`、`good`；客户端不得把服务契约之外的等级当作有效结果。
- 采用判断或用户改判后，正式复习才更新对应 `FsrsState`；`preview` 只记录预览尝试和结果，不更新 FSRS、不进入今天正式复习结果。
- 同一题的重复点击不能在等待期间创建第二个 `ReviewAttempt`；评分失败重试复用原尝试记录。正式复习 ACK 失败后的保持、补偿和恢复已由 #15 收口。

### 3.6 M1 评分失败安全与重试契约

正式复习的完成顺序固定为：

1. 用户选择 `again`、`hard` 或 `good`，本地保存 `pendingGrade` 和 `ack_pending` 状态；
2. 服务 ACK 成功；
3. 本地更新 `FsrsState`、`effectiveGrade`、`acked` 和完成状态，并成功保存；
4. 保存成功后才进入下一题或总结页。

失败状态必须满足：

- 评分、网络或结构错误：`agentGrade` 与 `effectiveGrade` 为空或保持未完成，原始 `answerText` 和同一个 `attemptId` 可继续重试；
- ACK 失败：当前题停在可恢复状态，`pendingGrade` 保留，`effectiveGrade` 不写入，FSRS 不变化，不进入下一题；
- 本地保存失败：不显示已掌握或已计入，保留当前题和可重试的本地状态；
- 服务端错误码或本地归因码写入 `ReviewAttempt.reviewErrorCode`，用户看到的是“还没有计入复习”，不能误解为回答错误；
- ACK 重试使用同一个 `attemptId`，服务端重复 ACK 保持幂等，不重复产生业务结果。


## 4. 允许变化与失败边界

以下差异属于生成文风，不应单独判为失败：

- 标题使用“光合作用”或“植物的光合作用”；
- 解释采用 `1. 2. 3.`、短横线或其他清晰分点；
- 使用“制造／合成／转化为有机物”等不改变含义的同义表达；
- 问题使用“请解释……”“这个过程如何发生？”等不同问法；
- `must_cover` 将两个相关关键点合并在同一条中，只要整体语义覆盖完整。

以下情况必须判为失败：

- 生成 0 张或多张重复／拆碎知识卡；
- 遗漏光能、输入、产物或释放氧气中的任一核心语义；
- 证据不是原文子串；
- 用模型常识补充原文没有的事实并当作来源内容；
- 问题无法依据评分规格判断；
- 正确回答未得到 `good`，或明显错误回答未得到 `again`；
- 模型、结构、本地写入或 ACK 失败后仍显示完成或已掌握。

部分正确、隐含同义、长回答跑题、遗漏限定和常见误解属于 M2 质量评测，不作为 M1 通过门槛。

## 5. 三层验收证据

### 5.1 服务级证据

证明 Agent 契约本身可运行：

- 通过真实 FastAPI／TestClient 入口提交机器可读 fixture；
- 提交响应允许先返回 `processing`，测试需按任务 ID 轮询 `GET /v1/capture/tasks/{task_id}`；
- capture 在 ACK 前最终进入 `committing`，正确 ACK 后为 `completed`；
- 返回一张符合第 3 节的知识卡；
- 正确回答为 `good`，明显错误回答为 `again`；
- 结果记录模型与命令，但不得输出 API Key、Authorization 头或完整凭证。

无模型契约回归命令（仓库根目录执行）：

```bash
cd agent-service
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

服务级成功不能替代真实 App 验收。

显式真实模型冒烟（会产生模型调用费用）使用 `agent-service/tests/m1_real_smoke.py`。先在一个终端启动本机服务：

```bash
cd agent-service
PYTHONPATH=. .venv/bin/python -m agent_service.main
```

再在另一个终端执行：

```bash
agent-service/.venv/bin/python agent-service/tests/m1_real_smoke.py
```

脚本会使用临时 `task_id`、`source_id` 和 `attempt_id`，完成 capture 轮询与 ACK、知识卡结构/来源/主问题校验、正确与明显错误回答评分、重复评分和重复 ACK 检查。默认 `unittest discover` 不会加载该脚本，也不会调用真实模型；脚本输出只保留脱敏后的状态、ID、等级和反馈存在性，不输出 API Key 或 Authorization。

### 5.2 真实 Mac App 证据

证明产品纵向链路可运行：

1. 从真实文字入口粘贴第 2.1 节输入；
2. 重新读取 SwiftData，确认 Source、Knowledge、Question 与评分规格已经保存；
3. 打开真实知识卡，核对第 3 节字段；
4. 从当前知识卡进入“试一题”，不手工拼接 ID；
5. 分别完成正确与错误回答；
6. 确认 preview 不更新 FSRS 或正式复习指标；
7. 模拟至少一种失败，确认没有错误成功或重复写入。

应保存：操作路径、关键数据 ID、运行命令与结果、必要截图、失败现象和未覆盖项。

#12 本地恢复检查还应覆盖：

1. 关闭本机 Agent 服务后输入固定样本，确认原文仍留在本地 `Source` 和 `CaptureTask`，首页任务链路显示等待服务恢复；
2. 启动服务后等待任务依次经过 `processing`、`committing` 与本地写入，确认同一 `task_id` 只产生一张知识卡，问题、评分规格和 `FsrsState` 均已保存；
3. 在 `committing` 或已完成但本地未落库的补偿路径重复 tick 或重启 App，确认先完成本地幂等写入，再发送知识 ID ACK；
4. ACK 失败时确认任务保持 `committing`，原始输入保留，下一次确认不会产生重复知识；
5. 重新打开 App，确认已完成任务和原始 `Source` 仍可从 SwiftData 读取。

服务级契约和客户端构建命令仍以第 5 节为准；本地保存失败与 ACK 失败需要同时保留任务原文和可归因错误码。
### 5.3 Rex 体验验收

证明最小体验可以理解和使用：

- 输入入口清楚；
- 知识卡内容能对回原文；
- 问题自然且可以作答；
- 判断与反馈容易理解；
- 用户知道如何重试或继续；
- 页面没有明显裁切、重叠或关键操作不可用。

真实界面最终体验由 Rex 判断，自动化和构建成功不能替代。

## 6. 父 Issue #1 映射

| 父 Issue 完成标准 | 主要证据 |
|---|---|
| 真实 App 完成文字端到端链路 | 第 5.2、5.3 节 |
| 知识卡字段忠于原文 | 第 3、4、5.2 节 |
| 正确与错误回答判断符合预期 | 第 2、5.1、5.2 节 |
| 失败不会写入错误成功状态 | 第 4、5.1、5.2 节 |
| 用户可以重试或继续 | 第 5.2、5.3 节 |
| 测试范围和未覆盖项有记录 | 第 5 节 |
| Rex 完成真实界面验收 | 第 5.3 节 |

## 7. 明确不验证

- 部分正确和复杂语义边界；
- 语音输入、Realtime、VAD、打断和转写纠错；
- 网页、联网核验和冲突处理；
- FSRS、通知、菜单栏和正式五分钟复习；
- 持久化 Harness、服务重启恢复和完整事件回放；
- Apple Foundation Models／PCC 模型对比；
- 吉祥物、嘴型和 Spine 动画；
- iOS、同步、账户、部署和商业化。

## 8. 后续执行者的最小上下文

处理 M1 子 Issue 时，默认只需读取：

1. 本文；
2. `agent-service/tests/fixtures/m1_acceptance.json`；
3. 自己被分配 Issue 中列出的文件；
4. 上游子 Issue 的完成证据。

不要为了理解 M1 重新加载全部产品文档或外围模块。发现本文无法覆盖的真实阻塞时，先在对应 Issue 记录失败事实，再决定是否新增 M1 返工子 Issue。