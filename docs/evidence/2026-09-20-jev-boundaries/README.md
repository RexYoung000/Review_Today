# Jev 三类判断边界优化

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
