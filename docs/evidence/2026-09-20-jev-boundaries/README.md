# Jev 三类判断边界优化

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
```

缺失行、非法结构、失败或不确定均保留；返回 0 只表示调用记录完整有效，不代表语义正确或产品通过。报告分别记录原始标签、潜在风险、复核与未拦截错误、请求数、耗时、用量和费用。费用按当日 [官方价格](https://docs.typesafe.ai/models) 的输入 $0.042 / 百万 token 估算，输出免费，不是账户账单。
