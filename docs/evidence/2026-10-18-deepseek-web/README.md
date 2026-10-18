# DeepSeek Search／Fetch 可选网页服务

2026-10-18，按决定 244 完成公共工具层接入与小样本真实对照。当前作为显式可选服务；本机 Exa → Tavily、教学模型与按需联网规则保持，未启动或替换日常 App。此前 Xcode 工程未提交差异不属于本次改动，原 EVAL-03 30／30／STOP 保持。

## 实现与配置

- 新增固定官方 JSON Search／Fetch 适配，复用 HTTP、预算、取消、冷却、事件、可读性与公开 URL 检查。单独使用 DeepSeek 时同样通过统一路由，避免绕过调用上限和限速；Search／Read 显式主备及 Browser 末级读取均可使用。
- 使用本机 `providers/web/.env` 内独立 `DEEPSEEK_WEB_API_KEY`，Rex 提供后已按授权配置；文件被 Git 忽略、权限 600，其余配置保持，原文件在本机私有临时目录留有恢复副本。代码不自动读取模型 Key 作为网页凭据，受控回归入口新增清空网页 Key。
- 查询最多五条、无模型端点、无 `ori_question`／定位 IP／全文上传。超过 128 Unicode 字符不发送 DeepSeek、不截断查询，已配置备用收到原查询。搜索正文／权威分数不提升为正文证据；空标题改以真实 URL 展示，不编造标题。
- Fetch 403／404 仅令当前网页读取失败；401／402 冷却服务；429 保留 `Retry-After`。每个进程保守限制同服务启动间隔 0.25 秒；不保证多进程或其他客户端共享账号的总 QPS。Fetch 仅提供请求 URL、标题、正文、截断元数据，不编造最终跳转 URL。

## 真实对照

原始公开样本和实际返回保存在 [comparison.json](comparison.json)，执行入口为 [compare_web_providers_live.py](../../../agent-service/tests/compare_web_providers_live.py)。一个独立进程按 DeepSeek → Exa → Tavily 顺序执行；每家相同的两条中英文 Python 列表查询，以及中文 Python、英文 Python、DeepSeek 新接口指南三个指定 URL。关闭自动备用与 Browser，不调用教学模型，不恢复任何会话或访问日常数据库。

| 服务 | 成功操作 | 两次搜索平均秒数 | 三次读取平均秒数 |
|---|---:|---:|---:|
| DeepSeek | 5／5 | 0.432 | 2.453 |
| Exa | 5／5 | 7.880 | 4.965 |
| Tavily | 5／5 | 4.165 | 2.260 |

共 15 次工具操作；Exa MCP 握手／清理不另算一次搜索或阅读。DeepSeek 实际两次有结果搜索、三次有正文抓取，按官方单次 0.005 元估算本批约 0.025 元；未核对供应商账单，Exa／Tavily 实际账单未核对。这里比较的是当前接入路径的单次墙钟耗时，样本很少且顺序固定，含供应商缓存及 MCP 开销，不是普遍性能结论。

转义守卫完成后另作一次独立真实 Fetch，约 0.419 秒成功，原始 `need\_content` 表示及 6,402 字符正文保持；见 [post-guard-fetch.json](post-guard-fetch.json)。不重跑原对照批次；本轮合计 16 次工具操作，其中 DeepSeek 6 次，按标价估算 0.030 元，零教学模型请求。

内容检查的关键发现：

1. 三家两条查询均返回五个 Python 官方域名结果。DeepSeek 在中英文查询的前两位都给出 Python 2 的中文／法语 `_sources` 文本，之后才出现 Python 3 的数据结构页面；空标题证据保持原始记录，随后适配层已补 URL 回退。官方域名命中不代表版本、语言或相关性正确。
2. Exa 两条查询首位均为当前 `/3/` 数据结构页，中文查询也有第二位中文页；Tavily 首位同为 `/3/`，但中文查询后续包含 argparse、collections 等非目标页面。不能据此将任一家概括为总是相关。
3. 三家三页都有可读正文。Python 页命中 `append`／`extend` 等固定标记，但标记只是传输覆盖信号，不证明完整或事实正确。DeepSeek 英文页到达 20,000 字符上限并报告截断；其他服务也受现有 20,000 字符上限约束，长度不能直接作为质量排名。
4. DeepSeek 指南返回大量 Markdown 反斜杠转义，原字符串标记 `need_content` 未命中，但原摘录中实际可见 `need\_content`；这是表示差异，不能记为字段缺失。本次保留服务原始正文，不对真实证据做去转义改写。由此新增的脚本外壳转义样本在修复前失败；适配层现同时检查去转义后的可读形式，拒绝转义脚本外壳，正常技术文章仍保留原始正文与引用依据。

结论：新接口可用于公共网页服务，搜索耗时值得继续观察；版本／语言排序和正文表示仍有限制，保留显式可选，不调整日常主备。动态脚本、登录／验证码、广泛领域、长期稳定性、真实模型选材／入库和原生端到端未验，不据本批关闭 M1 或 Rex 体验验收。

## 受控验证

受控入口五组离线用例库检查均通过；完整服务回归为 **1272 passed、4 原 skipped、588 subtests**，耗时 425.98 秒。五项警告来自未改动的 Starlette／FastAPI 废弃 API，未新增依赖。此轮完整测试开始时新服务收集 22 项；运行中追加的传输样本与 Markdown 转义守卫，最终通过四份网页工具组合复跑：**78 passed、4 原 skipped、71 subtests**，包含新增服务最终 24 项。结果与覆盖边界见 [validation.json](validation.json)；没有把最终局部新增项目算入早先完整运行的数字。

转义脚本样本修复前的受控失败保存在 [escaped-gate-before.log](escaped-gate-before.log)，修后同一场景及正常技术文章保留原文场景通过。日志仅移除行尾空白；该失败是合成传输用例，不是从真实网页确认了脚本误入学习结果。

覆盖模型独立与独立密钥、128 字符／完整长查询备用、来源摘要不冒充正文、敏感输入／URL、空正文与脚本外壳、账号／余额／页面错误隔离、限速与冷却、预算与遥测、排队／传输取消、浏览器末级接续，以及原 Exa → Tavily 配置保持。真实 API 不在这些受控测试中调用。

复现真实小样本时，在 `agent-service` 目录执行 `.venv/bin/python -m tests.compare_web_providers_live --live --output /tmp/review-today-web-new-comparison.json`；必须使用尚不存在的输出路径。显式开启后最多 15 次工具操作，无内部重试、无备用，不需要模型调用。新一轮结果另存，不覆盖本批证据。网页 Key 不进入命令行或结果。

规格见 [Harness](../../agent-harness-v2.md#deepseek-web-tools)，当前进度见 [WEB-01](../../work-status.md#deepseek-web-tools)，配置见[网页工具说明](../../../agent-service/providers/web/README.md#显式试用-deepseek)。接口与单价依据：[DeepSeek 官方指南](https://api-docs.deepseek.com/zh-cn/guides/search/)。
