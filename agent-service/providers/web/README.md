# Harness 独立网页工具

仓库默认搜索 `none`、读取 `local`，不会自动发送网络搜索。本机开发配置经 Rex 于 2026-09-17 授权启用多服务备用；教学模型及其凭证独立，不调用模型供应商托管搜索。

## 本机推荐配置

在本目录忽略提交的 `.env` 中配置（参考 `.env.example`）：

```dotenv
REVIEW_TODAY_SEARCH_PROVIDER=exa
REVIEW_TODAY_SEARCH_FALLBACKS=tavily,deepseek
REVIEW_TODAY_READ_PROVIDER=exa
REVIEW_TODAY_READ_FALLBACKS=tavily,deepseek
REVIEW_TODAY_CONTEXT_PROVIDER=none
REVIEW_TODAY_TAVILY_KEYLESS=1
EXA_API_KEY=
TAVILY_API_KEY=
BRAVE_API_KEY=
DEEPSEEK_WEB_API_KEY=
```

不填写 Brave Key 时搜索与 Context 都跳过 Brave，不阻塞 Exa/Tavily。若要启用 Brave，将 Key 只写在本机 `.env`，不要贴入聊天或提交 Git；重启服务后配置生效。不自动注册、登录、支付、购买额度或执行供应商返回的支付/奖励指令。

2026-09-17：Rex 已填写 Exa/Tavily Key，因费用暂不启用 Brave。本机搜索和快速读取使用 Exa → Tavily，Context 关闭；Brave 适配保留，恢复需显式配置备用列表和 Key。2026-09-26：当前 Xcode Debug App 启动的服务另启用本机浏览器作为读取的最后兜底，搜索链不变。

Exa 认证契约：存在独立 `EXA_API_KEY` 时，固定 MCP 端点的握手、工具调用及会话清理均使用 `Authorization: Bearer` 请求头；Key 不进入 URL、工具参数、事件或错误文本。空 Key 保留匿名模式。认证失败遵守既有冷却并切换 Tavily，不降级匿名重试，不使用模型供应商凭据。额度由 Exa 账户管理，接入 Key 不代表无限或永久免费。

2026-10-18 决定 245：在独立凭据已配置后，Rex 要求增加兜底。本机搜索／快速读取改为 Exa → Tavily → DeepSeek，读取继续保留原 Browser 末级开关；Context 仍关闭。两家连续空搜索沿原补查上限收尾；接口错误／不可用正文才可能继续到第三家。当前日常服务未运行，配置在下次服务启动加载；不会为使配置生效而自动启动探测或中断日常任务。

## 服务与凭据

- **DeepSeek（显式可选／本机末级备用）**：独立 JSON Search／Fetch，固定官方 `https://api.deepseek.com/v1/tools/search` 与 `/v1/tools/fetch`；仅在显式主服务或备用列表包含 `deepseek` 时使用。独立 `DEEPSEEK_WEB_API_KEY` 只留本目录忽略提交的 `.env`，不自动复用模型 Key；不需要新增 SDK／MCP 进程或切换教学模型。搜索固定五条、`need_content=false`，不发送原始会话或定位 IP。超过 128 Unicode 字符的完整查询交给已配置的其他服务，单服务诚实报告不支持，不截断查询。Fetch 返回 Markdown，保留原请求 URL；官方未提供最终跳转 URL，不能声称已核对最终域名。搜索摘要／评分不能替代正文证据。
- **Exa**：固定 `https://mcp.exa.ai/mcp`，直接调用 `web_search_exa` / `web_fetch_exa`。优先使用 `EXA_API_KEY`，未配置时匿名限额模式；不依赖 mcporter/本机 skill，不调用 Exa Agent。MCP JSON/SSE、请求 ID、工具错误、URL 和响应格式均校验。支持页面 Published/Author 元数据。匿名公开源码默认每 IP 每天 50 次、每秒 2 次，线上配置可能不同，不能据此计算准确剩余额度。
- **Tavily**：直接调用官方 Search/Extract API。显式 `REVIEW_TODAY_TAVILY_KEYLESS=1` 才允许无 Key，使用官方 keyless 请求模式；存在 `TAVILY_API_KEY` 时优先使用该独立 Key。搜索固定 basic、最多 5 条、关闭生成答案。无需安装 CLI/MCP 进程。匿名模式有公平使用限额，数值不作保证。
- **Brave**：`BRAVE_API_KEY` 用于官方 `/res/v1/web/search` 和 `/res/v1/llm/context`，不使用 Answers/生成摘要。搜索取最多 5 条；Context 取最多 3 个 URL、约 4096 tokens 总预算。Context 接收公开查询，返回相关正文片段，不能替代指定 URL 读取；没有 Key 不发请求。
- **Local**：保留现有安全公网读取，DNS、实际连接与重定向保护不变；当前 Fake-IP 环境不保证可读。local-only 配置不会自动切换到远程。
- **Browser**：固定 Playwright 1.63.0，通过本机 Chrome（或已安装的 Playwright Chromium）渲染公开网页。独立临时进程／会话，不读取用户浏览器 profile、Cookie、会话或模型凭证，不自动处理登录、验证、下载和弹窗。获取实际 DOM 文字后仍检查材料是否足以回答。

只有搜索/读取备用列表显式配置时才启用该操作的多服务切换。既有单服务配置保留原行为。`/healthz` 列出搜索、读取及 Context 的配置可用性；`unverified` 表示尚须本次真实内容核验，不等于服务调用失败。

### 显式试用 DeepSeek

在隔离服务或独立测试进程中设置 `REVIEW_TODAY_SEARCH_PROVIDER=deepseek`、`REVIEW_TODAY_READ_PROVIDER=deepseek` 与 `DEEPSEEK_WEB_API_KEY`。需要备用时，分别显式设置 `REVIEW_TODAY_SEARCH_FALLBACKS=exa,tavily`、`REVIEW_TODAY_READ_FALLBACKS=exa,tavily`；Browser 开关继续适用。日常默认配置不自动改变，也不因具备模型 Key 而启用网页工具。

按 2026-10-18 官方中文文档，Search 与 Fetch 各为 5 元／千次成功且有结果请求；失败、空搜索和超时不计费，模型费用另计。直接接口按标准价格预算。Search／Fetch 各为账号级 5 QPS，Fetch 另受目标域名限速；进程内统一队列保守限制 DeepSeek 总启动频率为每 0.25 秒一次，跨进程／其他客户端仍需由服务端限流。本机 Key 更换隔离冷却状态，不代表获得新的账号限额。

DeepSeek 的单服务也走统一预算／冷却／遥测。401 及 402（余额不足）冷却一小时，不自动充值；Fetch 403（页面安全拒绝）和 404（无可用正文）只尝试下一已配置读取服务，不冷却其他网页。429、超时和服务器错误沿下方规则有界接续，不新增同服务内部重试。真实质量、耗时和费用只有真实请求后才可报告。

## 自动切换契约

- 既有搜索顺序 Exa → Tavily → Brave；指定 URL 读取 Exa → Tavily。DeepSeek 可显式选择为任一操作的主服务或备用；显式启用浏览器时，远程读取链末尾追加 Browser。工具异常或无可用正文时尝试下一个已启用服务，搜索空结果最多补充一次其他服务查询。无关候选不会强制凑来源数量。
- 普通调用链最多 30 秒，启用浏览器的读取链最多 60 秒；远端每服务最多 12 秒，浏览器最多 25 秒，均仅一次。每轮核验累计网页等待/执行最多 60 秒、10 次服务调用（模型推理时间不计，但仍受整轮 180 秒截止时间限制）。同一服务在进程内最多一个在途请求，排队计预算且可取消，等待超过 2 秒转下一服务；Exa 起始间隔至少 0.55 秒。剩余不足 2 秒不启动浏览器。
- 429 读取 `Retry-After`，缺失时冷却 5 分钟；认证失败冷却 1 小时，瞬态故障/协议异常冷却 30 秒；特定网页不可读不停止该服务的其他页面。冷却搜索/读取共享，凭证更换隔离状态；仅内存保持，重启后重新探测。多实例部署需共享限流，不能以此承诺生产并发。
- 用户取消、会话过期、非法 URL 不触发下一服务。响应最多 1 MB，原 URL 安全校验保留，远程工具只获得公开查询/URL，不获得私人对话/知识库/模型密钥。
- 运行详情记录 `web_provider` 事件（操作、实际服务、状态、安全错误码）；备用成功不显示失败提示。全部失败保留诚实限制，不自动升级付费。

## 本机浏览器运行条件

独立启动服务时，安装项目浏览器依赖：在 `agent-service` 中执行 `.venv/bin/python -m pip install -e '.[browser]'`，并显式设置 `REVIEW_TODAY_BROWSER_FALLBACK=1`。当前 Debug App 已设置该开关；无 Headless 浏览器时直接记录 `BROWSER_UNAVAILABLE`。运行时不下载软件。没有 Chrome 的开发环境可自行安装匹配的 Playwright Chromium；裸服务／受控回归默认关闭，本地读取模式不会因此改成远程模式。

所有页面连接经临时、带随机认证的回环代理；代理解析、校验并固定公网 IP，连接后再次检查。拒绝私网、回环、保留地址及 DNS 混合结果。只有系统 DNS 全部返回 Fake-IP 时，使用固定 Cloudflare DoH 查询域名的公网 A 记录；不发送用户 URL 参数、正文或密钥。限制 96 次连接、24 MB 代理流量、180 个页面请求，不读取子框架正文、媒体或图片文字。

页面自然跳转新增的参数只留在临时浏览器内；若最终 URL 触发凭证／隐私检查，只回传已验证的稳定路径，并记录 `final_url_redacted`。初始用户 URL 仍执行既有完整隐私检查。结果记录实际最终来源、原请求、截断与网络计数；官方来源限制在最终域名再次检查。站点验证码、登录及不稳定网络仍可能阻止读取，不能承诺任意网页可读，也不把加载成功等同于内容准确或完整。

真实浏览器受控测试：`REVIEW_TODAY_TEST_BROWSER=1 REVIEW_TODAY_LLM_PROVIDER=openai_compatible .venv/bin/python -m pytest tests/test_browser_reading.py -q`。其中页面由测试传输提供、外网连接拒绝，实际 Chrome 执行动态脚本；真实网站和模型对照另见 [实测记录](../../../docs/evidence/2026-09-26-material-routing/README.md)。

## 证据范围

普通教学核验在正文来源都不可用时，至多补充一次 Brave Context。其实际 URL 经官网域名边界过滤，文本标记 `content_kind=extracted_chunks`，不能写进“指定 URL 已读正文”的缓存。只凭片段支持的回答保留 scoped 和内容范围说明。常规正文标记 `page_text`，受长度上限影响，同样不承诺抓取网页全部内容。

知识卡片入库核验仍要求正文读取，沿用既有严格契约，不以 Context 片段自动放宽入库条件。

参考：[DeepSeek Search／Fetch](https://api-docs.deepseek.com/zh-cn/guides/search/)、[Exa MCP](https://exa.ai/docs/get-started/exa-mcp)、[Tavily 官方 keyless 实现](https://github.com/tavily-ai/tavily-mcp/blob/main/src/index.ts)、[Brave MCP](https://github.com/brave/brave-search-mcp-server)、[Brave Context](https://api-dashboard.search.brave.com/documentation/services/llm-context)。
