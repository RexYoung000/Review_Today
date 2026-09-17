# A008 网页核验 / A009 中文加粗（2026-09-17）

## 实际交付

- A008 已修服务能力识别、状态区分和同主题旧提示重复；**网页检索尚未恢复**。DeepSeek 教学/路由/风险模型和凭证保持原配置，未接入新服务。
- 官方 [Responses API 文档](https://api-docs.deepseek.com/guides/responses_api/)现写明 web_search 等内置工具被忽略。用公开的 Python 列表文档查询，普通/强制 tool_choice 两次实测均 status=completed、output 只有 message、没有 web_search_call。正文虽然给出文档网址，也不能算实际检索。当前返回 unavailable，跳过无效模型请求，健康接口单列该能力。
- 只有 completed response + completed web_search_call + 非空结果才进入现有来源选择/公网读取/支持范围判断。兼容工具名只有明确工具不支持的 HTTP 错误才能尝试，拒绝/超时不靠换工具名掩盖。
- A009 在原生正文展示层补完整简单加粗的标点边界。保留原文和复制路径、行内代码/代码块/转义/链接/嵌套格式及未闭合流式。历史消息不修改即可重渲染。

## 发现与验证

1. [首次真实回放](live-initial-failure.txt)：原问答转成学习任务时旧核验状态丢失，例子再触发不可用提示；补同会话同主题证据继承，并纠正 new_knowledge 不能依赖核验成功。
2. [中间回放](live-repeated-prose.txt)：程序尾注已消失，但模型改写旧尾注进入正文。补本轮输出指令，不把旧通用服务说明作为新的证据摘要；具体证据范围仍保留。
3. [完整路由失败](live-routing-failure.txt)：例子请求偶发进入学习目标澄清，登记 A010，未把它隐藏为通过。
4. [定向真实回放](live-focused.txt)：`--fixed-routing` 固定合成意图，只隔离路由；知识准备、教练与流式仍真实调用当前配置模型。首轮 unavailable + 一次说明，追问 not_called + 保留 insufficient，无重复服务尾注。它不是完整路由端到端通过，也不是网页核验成功。
5. [服务回归](service-tests.txt)：348 passed、41 subtests passed；包括服务不可用不调用、未执行搜索的普通文本不能充当结果、失败后追问/强制刷新/风险核验、问答到学习证据继承、单来源选择/读取的受控模拟及重复复用、证据评估失败不冒充搜索服务不可用。FastAPI 既有 on_event 弃用提示保留。
6. [原生契约](native-checks.txt)：截图原句、多处相邻引号加粗、精确字符、普通加粗/斜体、代码/转义/链接、每个流式前缀通过。Debug 构建成功、严格签名通过。

## 原生体验

- `REVIEW_ANSWER_REGRESSION=1 bash tests/mac/run-answer-preview.sh` 渲染 340/580/780 pt、浅深各三张；已目视 [窄浅色](a009-340-light.png)、[宽深色](a009-780-dark.png)。
- 在真实独立内存窗口中切换窄幅与深色、播放真实逐字符预览，同时输入 `focus-test`；完成后焦点和输入保留，原句正常加粗，代码和转义星号保留。未新增动效，不改变系统减少动态偏好。
- 日常 App 空闲且无 committing 任务时正常退出，更新后的 Debug 重新打开。原会话“harness是什么意思”中原句及“替模型想办法”片段均已正常加粗；只查看，未重写历史或发送测试消息。旧核验尾注仍留在历史中，新的提示逻辑用于后续回复。
- 当前 [运行能力](runtime-health.json) 显示 teaching roles ready，web_search unavailable。生产发布未执行，最终观感待 Rex 验收。

## 重跑

- 服务：`PYTHONPATH=/tmp/review-today-topic-test-deps-20260915 bash agent-service/run-controlled.sh`（本机 pytest 依赖路径；脚本清空密钥、隔离测试库）。
- 原生：`bash tests/mac/run-contracts.sh AnswerDocumentContractTests`。
- 真实核验输出（隔离库）：在 agent-service 下运行 `.venv/bin/python -m tests.verification_real_smoke --live --fixed-routing`。省略 `--fixed-routing` 可复查尚未修复的自动路由问题；不得把失败样本改写成通过。

下一步：选择并确认可实际使用的检索服务及费用后接入，再补真实搜索→网页读取→核验→展示来源的成功证据；A010 单独对齐。未自动回退旧供应商或修改原模型配置。
