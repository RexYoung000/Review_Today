# Harness 独立网页工具

仓库默认搜索 `none`、读取 `local`，不会自动发送网络搜索。本机开发配置经 Rex 于 2026-09-17 授权启用多服务备用；教学模型及其凭证独立，不调用模型供应商托管搜索。

## 本机推荐配置

在本目录忽略提交的 `.env` 中配置（参考 `.env.example`）：

```dotenv
REVIEW_TODAY_SEARCH_PROVIDER=exa
REVIEW_TODAY_SEARCH_FALLBACKS=tavily
REVIEW_TODAY_READ_PROVIDER=exa
REVIEW_TODAY_READ_FALLBACKS=tavily
REVIEW_TODAY_CONTEXT_PROVIDER=none
REVIEW_TODAY_TAVILY_KEYLESS=1
EXA_API_KEY=
TAVILY_API_KEY=
BRAVE_API_KEY=
```

不填写 Brave Key 时搜索与 Context 都跳过 Brave，不阻塞 Exa/Tavily。若要启用 Brave，将 Key 只写在本机 `.env`，不要贴入聊天或提交 Git；重启服务后配置生效。不自动注册、登录、支付、购买额度或执行供应商返回的支付/奖励指令。

2026-09-17：Rex 已填写 Exa/Tavily Key，因费用暂不启用 Brave。本机搜索和读取使用 Exa → Tavily，Context 关闭；Brave 适配保留，恢复需显式配置备用列表和 Key。

Exa 认证契约：存在独立 `EXA_API_KEY` 时，固定 MCP 端点的握手、工具调用及会话清理均使用 `Authorization: Bearer` 请求头；Key 不进入 URL、工具参数、事件或错误文本。空 Key 保留匿名模式。认证失败遵守既有冷却并切换 Tavily，不降级匿名重试，不使用模型供应商凭据。额度由 Exa 账户管理，接入 Key 不代表无限或永久免费。

## 服务与凭据

- **Exa**：固定 `https://mcp.exa.ai/mcp`，直接调用 `web_search_exa` / `web_fetch_exa`。优先使用 `EXA_API_KEY`，未配置时匿名限额模式；不依赖 mcporter/本机 skill，不调用 Exa Agent。MCP JSON/SSE、请求 ID、工具错误、URL 和响应格式均校验。支持页面 Published/Author 元数据。匿名公开源码默认每 IP 每天 50 次、每秒 2 次，线上配置可能不同，不能据此计算准确剩余额度。
- **Tavily**：直接调用官方 Search/Extract API。显式 `REVIEW_TODAY_TAVILY_KEYLESS=1` 才允许无 Key，使用官方 keyless 请求模式；存在 `TAVILY_API_KEY` 时优先使用该独立 Key。搜索固定 basic、最多 5 条、关闭生成答案。无需安装 CLI/MCP 进程。匿名模式有公平使用限额，数值不作保证。
- **Brave**：`BRAVE_API_KEY` 用于官方 `/res/v1/web/search` 和 `/res/v1/llm/context`，不使用 Answers/生成摘要。搜索取最多 5 条；Context 取最多 3 个 URL、约 4096 tokens 总预算。Context 接收公开查询，返回相关正文片段，不能替代指定 URL 读取；没有 Key 不发请求。
- **Local**：保留现有安全公网读取，DNS、实际连接与重定向保护不变；当前 Fake-IP 环境不保证可读。local-only 配置不会自动切换到远程。

只有搜索/读取备用列表显式配置时才启用该操作的多服务切换。普通单服务配置保留既有行为。`/healthz` 列出搜索、读取及 Context 的配置可用性；`unverified` 表示尚须本次真实内容核验，不等于服务调用失败。

## 自动切换契约

- 搜索 Exa → Tavily → Brave；指定 URL 读取 Exa → Tavily。工具异常尝试下一个已启用服务，搜索空结果最多补充一次其他服务查询。无关候选不会强制凑来源数量。
- 每条调用链最多 30 秒，每服务尝试最多 12 秒且仅一次；每轮核验累计网页等待/执行最多 60 秒、10 次服务调用（模型推理时间不计）。同一服务在进程内最多一个在途请求，排队计预算且可取消，等待超过 2 秒转下一服务；Exa 起始间隔至少 0.55 秒。
- 429 读取 `Retry-After`，缺失时冷却 5 分钟；认证失败冷却 1 小时，瞬态故障/协议异常冷却 30 秒；特定网页不可读不停止该服务的其他页面。冷却搜索/读取共享，凭证更换隔离状态；仅内存保持，重启后重新探测。多实例部署需共享限流，不能以此承诺生产并发。
- 用户取消、会话过期、非法 URL 不触发下一服务。响应最多 1 MB，原 URL 安全校验保留，远程工具只获得公开查询/URL，不获得私人对话/知识库/模型密钥。
- 运行详情记录 `web_provider` 事件（操作、实际服务、状态、安全错误码）；备用成功不显示失败提示。全部失败保留诚实限制，不自动升级付费。

## 证据范围

普通教学核验在正文来源都不可用时，至多补充一次 Brave Context。其实际 URL 经官网域名边界过滤，文本标记 `content_kind=extracted_chunks`，不能写进“指定 URL 已读正文”的缓存。只凭片段支持的回答保留 scoped 和内容范围说明。常规正文标记 `page_text`，受长度上限影响，同样不承诺抓取网页全部内容。

知识卡片入库核验仍要求正文读取，沿用既有严格契约，不以 Context 片段自动放宽入库条件。

参考：[Exa MCP](https://exa.ai/docs/get-started/exa-mcp)、[Tavily 官方 keyless 实现](https://github.com/tavily-ai/tavily-mcp/blob/main/src/index.ts)、[Brave MCP](https://github.com/brave/brave-search-mcp-server)、[Brave Context](https://api-dashboard.search.brave.com/documentation/services/llm-context)。
