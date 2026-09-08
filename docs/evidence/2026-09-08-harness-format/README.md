# 意图 JSON 格式恢复验证

2026-09-08，针对问候两次 `json_invalid` 后无回复的修复。保持 DeepSeek 官方 Flash/Pro、智能/深入强度、严格 schema、每步骤两次总尝试与停止/归档/授权守卫。没有改变客户端界面或数据模型，没有关闭 M1 验收。

## 实际改动

- 非流式及流式最终 JSON 校验失败时记录固定格式类别、字符/字节长度与解析行列/位置；可用的 HTTP 请求 ID 经白名单过滤后关联事件。供应商本轮未提供可用请求 ID 时如实为 null。
- 每次失败独立保存 `model_attempt_failed`，保留实际步骤与尝试序号；第二次成功也能回看第一次失败。
- 区分代码围栏、纯文本/前缀、尾随内容、其他 JSON 语法和字段/枚举错误，生成一次针对性修复规则。规则放入可信系统消息，原始用户上下文保持 JSON 结构；失败响应原文不写日志、不放进系统消息。
- 不剥围栏后直接接受结果；JSON 正文字符串内的合法 Markdown 不受影响。已经显示正文或停止/归档失效时不启动第二次生成；连续两次失败继续保留输入，手动重试仍受原流程控制。

## 同条件真实服务验证

用合成“你好”、Auto/smart、空历史/记忆，分别建立 20 个临时 Session，执行真实 accept → drain → 模型请求 → 校验/有限恢复。容量初始估算同为 5,289 tokens；未向模型发送日常知识数据。

| 样本 | 首轮通过 | 首轮失败后恢复 | 两次均失败 | 总请求 |
|---|---:|---:|---:|---:|
| 修复前 | 14 | 5 | 1 | 26 |
| 修复后 | 18 | 2 | 0 | 22 |

首轮提示未改，首轮错误数量变化不能归因于本次修复。这些数值仅描述小样本，不代表长期可靠性。修复后的两次围栏失败均通过定向重试恢复，且事件保留 `markdown_fence`、第 1 行第 1 列、长度与序号。

证据：[修复前运行](before-runs.jsonl)、[修复前响应格式](before-attempts.jsonl)、[修复后运行](after-runs.jsonl)、[修复后响应格式](after-attempts.jsonl)、[恢复成功仍保留的失败事件](recovered-failures.json)。响应正文未存入这些诊断文件。

可复跑入口：在 agent-service 运行 `.venv/bin/python -m tests.stream_real_smoke --case greeting`；该入口使用独立临时库与合成输入，会产生真实模型用量，重复执行可收集新的样本。不能通过重放旧成功输出来证明恢复稳定。

## 受控与原生验证

- 新增 8 项测试覆盖：围栏/纯文本/语法/尾随内容分类与脱敏、错误枚举、请求 ID 白名单、正文内 Markdown、流式最终严格校验、完整适配器与 Harness 的同模型/强度/上下文恢复、连续失败上限及落盘/手动重试、停止后的迟到失败、正文预览后不重生成。
- `run-controlled.sh`：223 项通过，见 [日志](controlled.log)。现有两组测试使用 pytest，单纯 unittest 发现不会执行其函数测试；另运行这两个模块，65 项通过，见 [日志](dictation-regression.log)。初跑缺 pytest，补入 `/tmp/review-today-harness-pytest` 后复跑；安装使用项目的有效 CA 验证，没有跳过 TLS 验证或修改日常 .venv。
- Mac ConversationReplayTests 与真实 loopback Unicode SSE 通过：事件重复/缺口、稳定消息 ID、停止/归档/revision、会话隔离与游标恢复，见 [日志](mac-replay.log)。
- 签名 Debug NativeQA 构建和 `codesign --verify --deep --strict` 通过，构建日志 `/tmp/review-today-harness-fix-native-build.log`。本次没有 Swift 改动，未重复 Release 与旧库迁移。
- 原生隔离 bundle `com.rexyoung.ReviewToday.NativeQA`，端口 18748，库位于 `/tmp/review-today-harness-native-20260908`。CUA 在实际输入框发送问候并看到自然回复，服务记录 1.778 秒。未用日常数据测试发送、保存或删除。
- 日常入口沿用 `output/default-brand-build/Build/Products/Debug/Review_Today.app`。确认 8742 无活动任务后正常停止旧服务，再打开日常 App；新服务 PID 51731，三模型角色 ready，coach 流式 ready。日常会话/知识保留，历史失败不自动重发。临时 QA App 已退出。

## 扩大原生验收发现，尚未修复

本次只交付格式诊断与定向恢复，以下不能算作完整学习链路通过。原生合成输入与结果保留在 [native-results.json](native-results.json)。

1. **Auto 覆盖明确的资料学习意图。** 用户要求“按资料学习方式，先讲第一小节，不保存”，模型返回 workflow=source_learning、scope=learning；执行层却进入 organize。`conversation.py` 创建新任务前的 `if "material" in intents and not task and data["mode"] == "auto"` 无条件设置 memory_organization，覆盖了明确目标。最终交付整理稿，23.579 秒。违反既有“明确目标优先、无用途资料才轻整理”约定，后续应补明确 goal + material 的路由回归。
2. **指定资料学习时一次出现无效任务目标。** 原生选择 source_learning 再发送同类合成资料，1.948 秒后 `RT.INTENT.INVALID_TARGET`。这是解析之后的目标守卫错误；需进一步核对模型引用和客户端传入上下文，不归因于格式修复，也不报告通过。
3. **新会话普通问答出现多余澄清。** Auto 问“RAG 是什么？这次只解释，不安排训练，也不保存”，1.762 秒后返回“继续刚才内容还是开始新问题”的澄清，没有实际回答。原因尚未定位，需核对意图、记忆/会话上下文与澄清门槛。见 [原生截图](native-routing-limitation.png)。

尚未验证：全部学习模式/长对话的供应商稳定性、所有恢复组合的原生 UI、上述路由问题。受控回归与问候样本通过不等于 M1 学习闭环验收完成。
