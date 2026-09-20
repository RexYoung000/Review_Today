# Jev 三类判断边界优化

## 最终结论：保留局部改进，不接管正式路由

本轮完成 **419 次真实 Jev 调用、2,933 项原始判断**，均有效且无重试；随后完成 **62 轮隔离 Harness 回放**。资源边界定义改写有局部收益，但真实分流仍出现错误，因此不把此版本接入日常 App，也不设置自动接管阈值。scope 与 progress 未满足回归门槛，没有组合或进入新验证。

| 保留验证，48 个新场景 | 七项整例命中 | 资源字段正确 | 潜在风险例 | 未拦截错误 |
| --- | --- | --- | --- | --- |
| v0 原始基线 | 38/48 | 46/48 | 8 | 9 |
| v1 整理上下文 | 35/48 | 45/48 | 10 | 11 |
| resource 收紧资源边界 | 38/48 | 48/48 | 8 | 9 |

resource 相对 v1 修正 B029 编程能力、B031 编程交付混合知识、B038 撤回旧承诺这三个整例，没有新增错例或潜在风险。它的整例表现与 v0 相同，不能宣称已胜过原版完整路由。v1 本轮在新情境比 v0 差，说明上下文整理同样有适用边界。未改写字段也有输出变化，不把所有差异直接归因于改写资源问题。

引用访谈/日志/JSON 中的控制词仍被误当实际暂停或恢复（B001、B027、B045、B046）；继续代办和明确提出新知识问题仍可能误触发学习转场（B020、B022）。这些是其他判断维度的遗留错误，资源字段满分并未消除它们。48 例仍是代理合成样例，不是外部人工盲测或中文领域可靠性证明。

### 隔离整轮结果与实际错答

整轮实验基于提交 `da5e07b`，两分支使用相同的原 31 场景、各自独立的临时数据库，轮换先后。Jev 采用已记录的 resource 标签；DeepSeek 仍提供完整意图和回复。资源字段在 29/31 轮允许实验替换，其中只有 2 轮实际改变字段；另外 2 轮被原有一致性检查回退。回退比例是 2/31，不能解释为已校准的自动处理覆盖率。

| 整轮分支 | 既有自动断言整例 | 既有断言 | 补充分流复核 | 两层均通过 | 真实语义/HTTP 请求 |
| --- | --- | --- | --- | --- | --- |
| 当前 DeepSeek | 30/31 | 314/317 | 完成的 30 轮均通过；1 轮未完成 | 30/31 | 62 / 62 |
| 只替换资源字段 | 30/31 | 316/317 | 30/31 | 29/31 | 63 / 63 |

- **A005 coding 能力问句：真实行为退步。** 用户问“你有 coding 的能力吗”。DeepSeek 回复自己能帮助理解 coding 知识；实验分支实际回复“不承接寻找下载资源或代为下载等事务”，走了资源拒绝分支。既有断言居然仍为 PASS，因为原断言没有区分这两条分流。补充检查实际 `resource_scope_reply` / `programming_scope_reply` 与早已冻结的资源/编程边界预期，捕获了此错答；并人工核对两份完整回复。
- **A015 资源能力咨询：标签契约退步，回复相同。** `capability_question` 被替换为 `resource_delivery`，既有断言失败。但两分支回复相同，均说明不代找或下载资源；不能夸大为两次可见错答。
- **A001 基线超时：执行失败。** 第一条 DeepSeek 意图请求在 90 秒后触发 `RT.MODEL.TIMEOUT`，没有重跑或抹去。候选对应轮完成，不计为 Jev 的语义修正。该轮没有返回用量，不能记为零费用。

以上分流复核是在发现旧断言缺口后增加，依据既有边界契约；原始记录和原自动断言没有修改。最初的 [机器摘要](resource-harness-01-summary.json) 保留为历史，最终以 [含分流复核的摘要](resource-harness-01-audited.json) 为准；后者将超时差异与语义变化分开。它只补查实际边界分支，不代表全部回复自然度已验收。

同时加固评测器的晚到响应记录：在发起网络调用前绑定本轮身份和结果容器，避免旧响应使用下一轮的分支信息。原始 62 轮的替换前后对象逐项重算验证通过，未发现串用；未为这项记录加固重新抽取模型答案。正式 Harness 源码未改动。

### 耗时、调用与费用

| 局部阶段/版本 | 调用 | 中位数〔最小–最大〕ms | 输入/输出 token | 估算 USD |
| --- | --- | --- | --- | --- |
| 回归 v0 | 55 | 374〔308–1010〕 | 116,173 / 20,134 | 0.004879 |
| 回归 v1 | 55 | 371〔316–780〕 | 115,290 / 20,140 | 0.004842 |
| 回归 scope | 55 | 394〔323–676〕 | 184,205 / 20,135 | 0.007737 |
| 回归 resource | 55 | 387〔305–613〕 | 123,650 / 20,137 | 0.005193 |
| 回归 progress | 55 | 370〔313–970〕 | 129,260 / 20,136 | 0.005429 |
| 验证 v0 | 48 | 371〔307–983〕 | 101,541 / 17,570 | 0.004265 |
| 验证 v1 | 48 | 367〔302–657〕 | 101,024 / 17,571 | 0.004243 |
| 验证 resource | 48 | 367〔298–1032〕 | 108,320 / 17,566 | 0.004549 |

Jev 合计输入 979,463 / 输出 153,389 token，估算 **USD 0.041137446**。整轮新增 125 次 DeepSeek 语义请求与 125 次登记的 HTTP 请求，不新增 Jev 网络调用；可调用性探测不属于此处语义请求。基线有 61/62 份用量，共输入 259,678 / 输出 15,632，已知费用范围 USD 0.012017–0.024033；实验分支有 63/63 份用量，共输入 274,003 / 输出 16,983，估算 USD 0.013339–0.026678。费用按 [DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/) 的闲时/高峰边界记录，未知部分保持未知，均不是账单。

整轮基线中位数 4,644 ms〔2,109–90,058〕，实验分支 5,136 ms〔2,017–24,480〕。这组时间不含新的 Jev 推理，基线还有一次超时，不能用于宣称 App 提速或速度退步；本次只有干预回放，没有部署后的速度证据。

### 采用建议与证据

- **资源边界局部定义：需要继续校准。** 改写保留在评测器中；尚未支持接管。下一轮必须覆盖简短能力问句和跨编程/资源类别，不能只继续增加显式措辞的易区分样例。
- **全局引用说明、知识/进度改写：本轮暂不采用。** scope 引入新错误；progress 目标字段改善但出现新增风险，按冻结门槛不选。仍需独立样例复验，不能回头利用本批验证调参后再称独立验证。
- **正式对话路由：继续保留 DeepSeek。** 首轮候选筛选和答案要点检查的研究优先顺序不受本批改变，本轮没有重测这些节点或改写掌握/复习状态。

证据：[回归原始记录](regression-01.jsonl) / [回归重算](regression-01-summary.md)、[验证原始记录](validation-01.jsonl) / [验证重算](validation-01-summary.md)、[完整整轮记录](resource-harness-01.jsonl) / [最终复核](resource-harness-01-audited.json)。选择记录与原始输入输出均保留。回归 SHA-256 `3435661c0fb091ee76200a92ec018db1f15c71a16c6a6b40dda1191c03d2eace`；验证 SHA-256 `4d652d0d26c3268c1137f6e685e2bc6a2e70b274b590a2cae3f04a0ff8135283`。

最终 [受控回归](controlled-tests-delivery.txt) **633 tests / 300 subtests 通过**，72.43 秒；仅两个既有 FastAPI 弃用提示。新增覆盖单项修改范围、旧验证转回归、引文与历史原文保留、预期不入模型、来源/家族隔离、候选冻结、缺失记录、认证失败、混合请求缺少独立知识片段、真实分流复核和晚到响应归属。既有适配器的超时、缺失字段、非法标签/概率、模型漂移检查一并通过。原始模型记录离线重算通过；整轮结果保持 FAIL，不把受控测试通过等同于真实模型或产品通过。没有运行原生 UI 验收，没有改变生产代码、配置或日常数据库。

## 验证前选择（历史检查点）

规则与样例冻结提交 `4710bc9`。全量受控检查 622 tests / 300 subtests 通过，81.93 秒，两个既有 FastAPI 弃用提示。首阶段 275 次真实请求均有效，没有重试。

| 变体 | 整例命中 | 标签错误 | 潜在风险例 | 新增潜在风险 | 入选 |
| --- | --- | --- | --- | --- | --- |
| v0 | 43/55 | 16 | 10 | 8 项，相对 v1 | 参照 |
| v1 | 43/55 | 13 | 10 | 参照 | 基线 |
| scope | 43/55 | 14 | 8 | 3 项 | 否 |
| resource | 45/55 | 11 | 8 | 0 项 | 是 |
| progress | 47/55 | 8 | 7 | 1 项 | 否 |

仅 resource 满足全部预定条件：修正 A017 内部资料与 V022 带 token 资料链接的资源误判，没有新增整例错误；本轮不运行组合版。progress 的知识与进度字段均命中，但 A017 凭证链接在未修改的资源字段出现新误判。此现象不能直接归因为进度提示词的因果影响，也可能有模型/批处理波动；本轮仍按预先门槛处理，不择优重跑。

[选择记录](selection-before-validation.json) 在验证前写入，保持 `validation_status=not_run` 作为历史状态；验证阶段将只比较 v0、v1 和 resource。回归集原始记录与逐项差异见 [regression-01.jsonl](regression-01.jsonl)、[重算摘要](regression-01-summary.md)。

## 执行前冻结

本批沿用 `jev-1.13.0` 与独立官方 HTTP 适配器。日常 App、DeepSeek 模型、MCP 配置和真实学习数据不变。旧 55 场景全部为回归开发样例，新增 48 个代理编写的合成验证场景，分属 12 组情境；未冒称外部人工盲测。规则与新样例在首个真实调用前冻结。

| 变体 | 相对 v1 的唯一改动 |
| --- | --- |
| v0 | 原始基线，用于观察上下文整理收益 |
| v1 | 沿用上一批上下文整理，七个问题不变 |
| scope | 七个问题增加同一条当前指令/引用/历史的作用范围说明 |
| resource | 只重写资源边界问题，分开资料理解、事实核验、编程和资源获取代办 |
| progress | 只重写知识请求与学习进度问题，明确当前计划、最近请求和旧课恢复的区别 |

所有变体仍输出原始七项判断，不拆成原子问题再组合，不把引号或控制关键词直接转换成答案。保留全部原话，其他会话目标不进入 v1 及候选的当前意图输入。

候选必须在目标字段错误、整例命中、总错误及新增潜在风险四方面满足 [执行前约定](../../jev-deepseek-evaluation.md)。多项合格时另跑组合回归，组合规则在首次运行前已定义；验证前记录选择，验证后不改选或重抽样。没有达到门槛就停止接管方向，不补做一个表面通过的结果。

“潜在风险”仅描述错误标签可能触发的错误分流，例如误暂停、错接学习目标、错误资源拒绝或漏掉混合请求。实际程序有额外保护，因此这些项目不是已经发生的 Harness 行为。知识请求标签与计划推进标签的细微差异仍计原始错误，但不自动计成已发生的教学故障。

只有验证集同时改善整例和潜在风险、没有新增高影响错误时，再进入隔离 Harness 有限整轮实验。自动接管阈值仍未校准，正式路由仍由 DeepSeek 处理。

## 入口

在 `agent-service` 下执行，默认入口只检查离线结构：

```bash
.venv/bin/python tests/run_jev_boundaries.py

# 五组回归开发对照；每个真实执行输出必须是新文件。
.venv/bin/python tests/run_jev_boundaries.py --live --stage regression \
  --jev-key-stdin --output ../docs/evidence/jev-boundaries-regression-next.jsonl

# 如有多个合格因子，先按它们的固定组合再跑回归。
.venv/bin/python tests/run_jev_boundaries.py --live --stage combination \
  --regression-report ../docs/evidence/jev-boundaries-regression-next.jsonl \
  --jev-key-stdin --output ../docs/evidence/jev-boundaries-combination-next.jsonl

# 选择文件写入后不可覆盖；只有一个合格因子时省略 combination-report。
.venv/bin/python tests/run_jev_boundaries.py \
  --regression-report ../docs/evidence/jev-boundaries-regression-next.jsonl \
  --combination-report ../docs/evidence/jev-boundaries-combination-next.jsonl \
  --freeze-selection ../docs/evidence/jev-boundaries-selection-next.json

.venv/bin/python tests/run_jev_boundaries.py --live --stage validation \
  --selection ../docs/evidence/jev-boundaries-selection-next.json \
  --jev-key-stdin --output ../docs/evidence/jev-boundaries-validation-next.jsonl

.venv/bin/python tests/run_jev_boundaries.py \
  --report ../docs/evidence/jev-boundaries-validation-next.jsonl \
  --markdown /tmp/jev-boundaries-validation-review.md

# 本轮满足局部门槛后进行的已知场景干预回放；默认不加 --live 只检查前提。
.venv/bin/python tests/run_jev_resource_harness.py --live \
  --selection ../docs/evidence/2026-09-20-jev-boundaries/selection-before-validation.json \
  --validation ../docs/evidence/2026-09-20-jev-boundaries/validation-01.jsonl \
  --output ../docs/evidence/jev-resource-harness-next.jsonl

# 本批返回 1：证据完整，但存在超时和契约差异；不把退出码改成成功。
.venv/bin/python tests/run_jev_resource_harness.py \
  --report ../docs/evidence/2026-09-20-jev-boundaries/resource-harness-01.jsonl
```

缺失行、非法结构、失败或不确定均保留；返回 0 只表示调用记录完整有效，不代表语义正确或产品通过。报告分别记录原始标签、潜在风险、复核与未拦截错误、请求数、耗时、用量和费用。费用按当日 [官方价格](https://docs.typesafe.ai/models) 的输入 $0.042 / 百万 token 估算，输出免费，不是账户账单。
