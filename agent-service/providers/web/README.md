# Harness 独立网页工具

默认搜索未配置，网页读取为本地安全读取。没有模型内置搜索降级路径。

2026-09-17 经 Rex 授权，本机开发配置显式使用 Exa；仓库默认仍不启用服务。

## Exa（本机当前方案）

将本目录 `.env` 的 `REVIEW_TODAY_SEARCH_PROVIDER` 和 `REVIEW_TODAY_READ_PROVIDER` 均设为 `exa`，重启 Agent 服务。无需复制开发环境的 skill、mcporter 配置或任何模型密钥。固定连接官方 `https://mcp.exa.ai/mcp`，通过 MCP 直接调用 `web_search_exa` / `web_fetch_exa`，不调用 Exa Agent 或研究生成工具。

这是官方匿名限额模式，不承诺无限量或生产 SLA。429/认证要求明确失败，不自动登录、付费或换服务。初始化与工具调用都在有限预算内，JSON/SSE 响应校验、总大小限制 1 MB；已停止会话关闭客户端并拦截晚到结果（不保证远端已开始的抓取立即停止）。搜索结果文本按已验证的格式解析，格式变化时返回协议错误，不让模型猜来源。正文返回 URL 必须与请求 URL 一致。

Exa 收到最小公开检索词或指定公开 URL，远程读取沿用公开 URL 结构限制。原本地 DNS 防护没有被削弱；远程读取成功不代表本机 Fake-IP 问题已修复。官方：[MCP 文档](https://exa.ai/docs/get-started/exa-mcp)、[开源实现](https://github.com/exa-labs/exa-mcp-server)。

## Tavily（保留可选适配）

确认选用后，将 `.env.example` 复制为本目录 `.env`，本地填写 `TAVILY_API_KEY`，将搜索 provider 改为 `tavily`。如同时使用远程网页读取，将 read provider 改为 `tavily`。本适配是直接 API 路径，需要 key；官方 CLI 的匿名模式不在该适配内。重新启动 Agent 服务后生效。不要提交 `.env`，不要把密钥发送到聊天。

- Search 只接收最小化的公开主题，固定 basic、最多 5 条，不请求生成答案或自动升级参数。
- Extract 只接收选中的公开 URL，最多每轮读取 3 个候选；正文须经模型证据判断才能用于“已核验”。
- 模型仍使用原有配置和凭据，网页工具不接收模型名或模型密钥。
- 本地读取保留 DNS、连接目标、重定向校验。选择远程 Extract 后，由 Tavily 访问公开网站；客户端限制 URL 类型，远程服务承担其抓取网络的隔离。不会因本地读取失败自动改用远程服务。
- `/healthz` 分别报告 web_search / web_read。配置存在只能标记 unverified，不能证明真实请求成功。
- 401/403、协议/配置错误不重复尝试；瞬态搜索错误沿用 Harness 的有限重试和取消机制。响应大小限制 1 MB；单次 HTTP 最多 30 秒。

Tavily 服务使用受独立账号额度/费用约束，本代码不注册账号、不购买额度、不自动启用。接口参考：[Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)、[Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract)、[额度](https://docs.tavily.com/documentation/api-credits)。
