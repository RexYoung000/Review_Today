# A008：DeepSeek 搜索协议适配（2026-09-17）

> 历史记录：下述托管搜索已由 [Harness 独立工具修复](../2026-09-17-independent-web/README.md) 替换；本页实测结果只对应原提交，不表示当前线路。

## 交付与边界

Rex 核对 DeepSeek 的搜索支持后授权实施。此次沿用已有官方域名、DeepSeek 凭证和教学/风险模型，只把搜索从 Responses 改接 Anthropic Messages。没有接入其他检索供应商、修改代理/DNS、关闭公网保护或发布生产版本。

- [官方 Anthropic 兼容说明](https://api-docs.deepseek.com/zh-cn/guides/anthropic_api/)支持 server_tool_use 与 web_search_tool_result；[Claude Code 接入说明](https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/claude_code/)说明原生网页搜索。先前“DeepSeek 整体不支持”的推断不成立，限制仅适用于 Responses 内置工具。
- 新适配器仅采用成对搜索工具结果的标题/URL，丢弃正文、思考、加密片段；不让模型记忆中的链接充当搜索记录。不跟随携带凭证的重定向。原有总时限、关闭句柄和最多两次外部请求沿用；单请求声明最多两次服务器搜索，达限只使用已完成的结果，不无限续调。
- 来源候选须原样匹配真实结果 URL，然后才公网读取、评估与引用。候选阶段根据标题/URL 选择待读资料，不提前要求全文证据；结构化结果直接作为数组传给选择模型。
- 搜索有结果但网页读取失败时为 insufficient；提示“已检索到相关资料，但网页未能读取，本次尚未完成核验”。真实空候选仍为 no_results。教练收到实际已读 URL 列表，空列表时禁止凭记忆补出处或自称核对过。
- healthz 明示 `anthropic_messages`，启动时仍为 `unverified`：没有暗中发送启动搜索，教学模型 ready 不等于该次搜索成功；每次调用独立检查工具证据。

## 实际验证

- [Flash / Pro 真实请求](search-models.jsonl)：原配置的两个模型都返回成对搜索结果；日志仅保留公开标题、URL、部分结果标志，无密钥、思考或 encrypted_content。
- [首次完整自动路由回放](live-initial-failure.txt)：未取得已读来源，正文仍声称核对过，不能算通过。随后加入实际已读 URL 列表约束。
- [后续 DNS 失败回放](live-dns-failure.txt)：实际搜索返回、模型选择三条官方候选，但读取均被公网地址保护拒绝。只检查涉及的公开域名，系统 DNS 全部返回 `198.18.x.x` 非公网地址，包括 docs.python.org、raw.githubusercontent.com。没有访问这些地址或降低保护。
- [候选选择失败回放](live-selection-failure.txt)：相关搜索结果存在，选择模型仍返回空候选。保留失败记录；随后明确候选/全文核验职责，并直接传递数组。不能用单次受控通过掩盖真实模型的不稳定性。
- [最终服务回归](service-tests.txt)：368 passed、56 subtests passed；保留两项既有 FastAPI 弃用提示。
- [未核验链接失败回放](live-links-failure.txt)：候选返回三条官方文档，网页读取被保护拒绝；正确标记 insufficient，但正文仍补记忆网址，严格断言失败。随后增加流式和最终正文共用的已读 URL 白名单处理，名单外网址显示“（链接未核验）”；代码示例不按引用处理。
- [最终完整自动路由降级回放](live-degraded.txt)：**通过**。真实搜索→选择官方候选→公网保护拒绝读取→如实说明且无未核验网址→生活类比追问 not_called、保留 insufficient、不重复核验尾注。没有固定意图或模拟搜索/读取；这是当前网络环境下的降级通过，**不是网页核验成功**。
- 受控回归覆盖：完整适配器→来源读取→证据评估→来源展示，以及无工具证据、错误、空结果、部分成功、限额、取消句柄/共享预算、凭证域名与重定向隔离、读取失败的状态和提示。受控网络读取不算真实网页验收。
- 本次只有后端及测试/文档修改，未改原生布局与组件。空闲开发 App 正常重启，原空白会话保留；[健康状态](runtime-health.json)显示原三个模型 ready、搜索选择 Anthropic。未向日常历史插入测试消息。

## 重跑与剩余验收

服务回归：`PYTHONPATH=/tmp/review-today-topic-test-deps-20260915 bash agent-service/run-controlled.sh`。

在 agent-service 下：

- 正常公网网络：`.venv/bin/python -m tests.verification_real_smoke --live`，要求真实搜索→实际网页正文→证据 supported/scoped→最终展示已读来源，下一轮复用证据。
- 当前非公网 DNS 环境：加 `--expect-read-blocked`，要求实际候选读取被保护拒绝、如实说明、追问不重复尾注。此模式通过也不代表网页核验成功。
- `--fixed-routing` 仅用于隔离已有 A010 意图问题，使用时必须披露，不冒充完整自动路由。

**完整真实网页核验仍未通过。** 需要先让本机公开域名恢复正常公网解析，再重跑成功场景。正文未核验网址现经确定性处理，已覆盖流式各前缀、代码示例、原样已读来源和最终文本。候选选择若仍返回空列表，继续按保留的 A008 样本定位。A010 不在本轮修改范围。
