# A008：Harness 独立网页工具（2026-09-17）

## 当前交付与限制

用户确认：模型只负责公开查询准备、理解资料和回答；Harness 直接执行搜索、网页读取，不再额外请求 DeepSeek 模型触发内置搜索。

- 已移除 `deepseek_search.py` 及模型客户端的搜索接口；会话、选材、资料读取、录入核验和兼容任务统一走 `web_tools.py`。
- 搜索签名不接受模型名/思考强度，独立配置和错误；健康接口分别报告 search/read。旧搜索缓存不会因同一查询而误用。
- 提供可选 Tavily Search/Extract 适配器，固定服务端点与独立 key，尚未启用。发送最小公开主题/选中 URL，不发送模型凭据、整段私人对话或知识库。
- 先搜索候选，再读取正文，最后让模型判断证据支持范围。HTTP 200 但抽取失败仍失败；摘要、模型生成的链接、未读取的网页不作为已核验来源。录入兼容流程也修复这一边界。
- 搜索保留有限重试、预算和取消；会话远程读取注册取消句柄并检查运行版本。本地读取继续保持 DNS/目标连接/重定向校验及原有超时，不能绕过 Fake-IP 地址限制。
- 未改教学模型、已有凭据、系统 DNS/代理；没有配置任何真实 Tavily key、注册账号或购买服务。

**真实联网未完成：**独立搜索服务选型和密钥仍待用户确认/本地配置。缺配置时返回 `RT.WEB.NOT_CONFIGURED`，不回退旧托管搜索。本机此前公网 DNS 返回非公网地址的问题未修复，默认本地读取可能继续受阻。选择远程 Extract 属于显式服务配置，不能称为修复了本地 DNS。

## 验证

- 全套 **370 项测试、58 项子测试通过**（36.70 秒）；仅有既有 FastAPI lifespan 弃用警告。受控测试使用隔离数据库与 HTTP MockTransport，不访问真实搜索服务。
- 覆盖直接 Search → Extract → Harness 证据判断 → 回答来源的完整受控链路；模型切换、缺 key/缺配置、禁止模型回退、正文失败/错 URL、敏感 URL 拒绝、HTTP 错误脱敏、取消句柄、共享请求预算、录入正文核验。
- 保留原有 SSRF、对话结束、上下文、知识录入时机及 Markdown 回归。
- `configured-health.json` 是新进程本地配置检查（未启动模型探测），模型 checking 不代表模型故障；它证明 search=none/unavailable，read=local/unverified。
- 空闲开发 App 已正常重启，未向日常历史插入测试对话；[实际运行健康状态](runtime-health.json) 显示原三个模型 ready、新工具协议已加载、独立搜索未配置。
- 本轮未改原生 UI，未运行 Xcode 构建；联网成功与最终用户体验仍待服务配置后验收。

运行：`PYTHONPATH=/tmp/review-today-topic-test-deps-20260915 bash agent-service/run-controlled.sh`。

## 配置后的验收

按 [网页工具配置说明](../../../agent-service/providers/web/README.md) 在本地填写独立 key，重启服务。使用隔离脚本：在 agent-service 目录执行 `.venv/bin/python -m tests.verification_real_smoke --live`。

预期：首轮官方文档问题真实 search/read 成功、证据判断有支持范围、回答展示实际读取来源；第二轮仅请求类比，复用现有证据，不重复搜索或弹旧失败提示。完整真实链路通过后再更新 A008 状态；当前不得以受控通过代替。
