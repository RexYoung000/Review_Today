# A008：多服务网页搜索与正文备用

## 独立 Key 接入补验（2026-09-17）

当前状态覆盖下方早期的匿名开发配置记录：Rex 已配置 Exa/Tavily Key，因费用暂不启用 Brave。本机搜索/读取均为 Exa → Tavily，Context none；Brave 没有发送请求。Key 仅存于被忽略的本机 `.env`，Exa 用固定 MCP 地址的 Authorization 请求头传递，认证失败不匿名重试。

- 受控：411 tests / 69 subtests 全通过，新增带 Key 的握手/工具/清理、401 不重试与脱敏、认证冷却并切换、Key 更换重置冷却、Brave 关闭场景。见 `authenticated-controlled-summary.txt`。
- 真实工具：用各自独立 Key 调用 Exa/Tavily 的搜索与指定 Python 官网正文读取，均成功，正文均截取 12,000 字符并包含 append/extend。注入 Exa RATE_LIMIT 后，Tavily 实际执行搜索和同 URL 读取恢复。见 `live-authenticated-providers.jsonl`。该故障由测试注入，不表示 Exa 账户实际耗尽。
- 完整真实对话：在 agent-service 执行 `.venv/bin/python -m tests.verification_real_smoke --live --scenario official`；自动意图路由、Exa 搜索/读正文、模型核验及引用展示成功；第二轮复用来源，不再次搜索。临时数据库隔离，未改用户聊天。见 `live-authenticated-exa-conversation.jsonl`。
- App 重启前检查没有运行中的会话；重启后健康接口显示 Exa/Tavily 两路、Context 未配置，模型角色 ready。见 `authenticated-runtime-health.json`。健康信息 unverified 是逐轮内容核验状态，并不抵消上面的实际调用证据。
- Brave 真实接入暂不验收；未购买套餐或修改任何账户计费设置。Key 调用仍受各自账户额度/计费约束。无 UI 改动，未执行原生视觉验收；Rex 可用文末的两轮问题体验新配置。

认证方式依据 [Exa 官方 MCP 说明](https://github.com/exa-labs/exa-mcp-server#authentication)。

## 已实现

- 搜索 Exa → Tavily → Brave；读取 Exa → Tavily。Tavily 支持显式匿名模式或独立 Key；Brave 缺 Key 时跳过。正式服务端点直接请求，无新 CLI/MCP 进程依赖。
- 搜索与读取独立切换，共享服务冷却。429 遵守 Retry-After，无值时暂避 5 分钟；认证/瞬态错误分别冷却。每服务在进程内一个在途请求，排队超过 2 秒转备用；取消、非法 URL 不继续调用。
- 每操作 30 秒、单服务尝试 12 秒；核验轮累计网页等待/执行 60 秒、10 次调用，不累加模型推理耗时。搜索空结果至多补充一次其他服务查询。
- 普通教学没有可读正文时补充 Brave Context，标记 extracted_chunks，仅按片段支持范围核验，不能进入完整页面缓存。知识入库保留原正文核验规则。
- 运行详情和健康接口报告实际服务及安全状态；备用成功不重复失败提示。仓库默认关闭，本机开发配置明确启用备用。

## 受控验证

`PYTHONPATH=/tmp/review-today-topic-test-deps-20260915 bash agent-service/run-controlled.sh`

407 tests、69 subtests 通过；仅既有 FastAPI on_event 弃用警告。完整输出见 `controlled-summary.txt`。新增案例覆盖：429/超时/5xx 切换、Brave 第三路接管、缺 Key、相同 URL 读取切换、跨搜索/读取冷却与恢复、并发只探测一次、忙服务跳过、排队取消、轮次总预算、空结果补检、全部失败、URL 安全、官网过滤、keyless 限额响应及正文片段语义。模型与传输模拟和真实请求分开记录。

## 真实外部验证

1. **模拟 Exa 限额，Tavily/模型真实执行**：运行 `python -m tests.verification_real_smoke --live --scenario official --force-exa-limit`，搜索/读取备用环境变量按 providers/web/README 配置。两轮自动路由通过：第一轮 Tavily 搜索并读取两份 Python 官网文档，评估并展示实际来源；第二轮复用证据，无新网页调用/旧失败提示。见 `live-exa-limit-tavily-recovery.json`。
2. **模拟 Exa 单页不可读，Tavily 真实读取**：对相同 Python 官方 URL 读取恢复，返回 20,000 字符；没有重新搜索。见 `live-read-recovery.json`。
3. **Brave**：搜索、Context 接口和故障切换通过受控测试，但当前没有 BRAVE_API_KEY，尚未做真实外部请求，不能宣称实际三路全部可用。配置本机 Key 后需补真实搜索、正文片段和来源展示验证。

## 保留的失败与修正

- `initial-live-model-failure.json`：首轮网页备用成功，次轮进入 lesson 后模型生成失败，整个两轮回放失败。重新运行后两轮通过；此前 A010 的追问进入教学任务/回答偏长仍单独待处理。
- `initial-live-source-filter-failure.json`：Tavily 返回第三方教程，官网来源校验正确拒绝，导致没有可读候选。修正：Tavily 将官网域名约束同时传给 include_domains；用户显式要求官网时不能因准备模型漏标而取消官网限制。随后官网两轮通过。
- 只进行安全错误分类，不执行服务返回的支付、奖励或登录指引。不自动付费；匿名 Tavily 和 Exa 仍各有自身额度。

## 开发运行与验收

本机 `.env` 保留原凭据、权限 0600；搜索 exa/tavily/brave、读取 exa/tavily、Context brave，缺 Brave Key 跳过。重启前检查真实库没有运行中的会话；真实回放使用隔离数据库，没有导入合成会话到用户库。新增 `web_context` 健康项，未配置明确为 NO_KEY。

Rex 可在 Agent 新会话输入“请查阅 Python 官方文档，解释 append 和 extend 的区别，并附来源”，再问“举个生活类比”。第一轮应有实际来源，第二轮复用资料；运行详情可见真实使用服务。正常提问不保证触发备用，故障切换依据上方注入主服务错误的真实备用验证。未新增 UI 布局，未做原生视觉验收；生产多实例共享限流、生产发布及 Rex 最终验收未完成。
