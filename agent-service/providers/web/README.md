# Harness 独立网页工具

默认搜索未配置，网页读取为本地安全读取。没有模型内置搜索降级路径。

已准备 Tavily 适配器，但本项目尚未配置服务或密钥。确认选用后，将 `.env.example` 复制为本目录 `.env`，本地填写 `TAVILY_API_KEY`，将搜索 provider 改为 `tavily`。如同时使用远程网页读取，将 read provider 改为 `tavily`。重新启动 Agent 服务后生效。不要提交 `.env`，不要把密钥发送到聊天。

- Search 只接收最小化的公开主题，固定 basic、最多 5 条，不请求生成答案或自动升级参数。
- Extract 只接收选中的公开 URL，最多每轮读取 3 个候选；正文须经模型证据判断才能用于“已核验”。
- 模型仍使用原有配置和凭据，网页工具不接收模型名或模型密钥。
- 本地读取保留 DNS、连接目标、重定向校验。选择远程 Extract 后，由 Tavily 访问公开网站；客户端限制 URL 类型，远程服务承担其抓取网络的隔离。不会因本地读取失败自动改用远程服务。
- `/healthz` 分别报告 web_search / web_read。配置存在只能标记 unverified，不能证明真实请求成功。
- 401/403、协议/配置错误不重复尝试；瞬态搜索错误沿用 Harness 的有限重试和取消机制。响应大小限制 1 MB；单次 HTTP 最多 30 秒。

实际服务使用受独立账号额度/费用约束，本代码不注册账号、不购买额度、不自动启用。接口参考：[Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)、[Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract)、[额度](https://docs.tavily.com/documentation/api-credits)。
