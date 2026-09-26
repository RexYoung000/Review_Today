# 产品材料续接与流式中断修复

2026-09-26。已实现并进行工程自检，最终使用体验仍待 Rex 在日常 App 验收。

## 本次处理

1. 本轮意图单独标识材料对象。补小程序链接、产品文字或截图不再因同一面试目标重跑 JD；明确重试／更新 JD 才重新分析岗位。
2. JD 正文充分即清除“补充材料正文”；生成失败保留未完成分析状态。产品材料检查与 JD 检查独立，不覆盖原任务和已展示的问题选择。
3. 最多三条已展示的失败／中断输出作为独立上下文传给后续轮次，保留状态；不冒充完成消息，不进入知识、掌握证据或完成摘要。
4. 流式调用保留整轮 180 秒总预算：首段有效正文默认最多等 90 秒，之后连续 30 秒无有效正文才空闲超时。持续输出不再触发单步 90 秒硬切。取消、调用次数和过期结果守卫仍生效。
5. 日常 App 用橙色提示说明未完成；任务重试优先定位失败运行，避免产品问答完成后把重试按钮指向该已完成问答。
6. 复用 JD 内公司／产品介绍；公开资料查询和直接操作微信分开判断。检索工具未执行时不能说“已查过但没有结果”。
7. 收紧输出依据：不以名称大小写、JD 条目顺序或经验数量推断招聘要求；页面未展示不等于产品没有，设计建议应说明假设。减少重复风险和无关补材料请求。

## 自动化与原生验证

- 相关后端回归：123 passed，8 subtests passed。随后新增的旧任务兼容、操作优先级与直接教学保护通过定向复测（26 passed，4 subtests passed）。
- 最终四组核心回归（产品续接、材料路由、时限策略、流式输出）55 passed、6 subtests passed。
- 全量后端回归：847 passed、9 failed、4 skipped、354 subtests passed。**没有把全量测试标成全绿。**
- 在修改前提交 `bb09d163e31c959b2507af5648cea434bd0df0bb` 的服务模块上复现同样 9 个失败。其中 7 项是 OpenAI 兼容适配器测试继承本机 DeepSeek 配置；显式指定 `REVIEW_TODAY_LLM_PROVIDER=openai_compatible` 后消失。另两项既有失败为：
  - `test_closure_repair.py::ClosureRepairTests::test_fetched_source_is_reused_on_generation_retry_and_refresh_has_version`
  - `test_closure_repair.py::ClosureRepairTests::test_mixed_material_keeps_generated_identity`
- 显式测试环境的复核结果为 101 passed、上述两项 failed、6 subtests passed。本次未改动这些旧缺陷，不能据此宣称全部材料链路已验收。
- 原生 `ConversationControlTests`、`ConversationReplayTests`、`LearningInputContractTests` 通过；重试定位修改后重新运行前两项通过。包括真实本机 SSE 传输、取消与版本隔离，以及失败 JD 后出现已完成产品回复时的重试目标。
- macOS Debug 构建成功，签名严格验证通过；没有更换日常 App 的签名要求或隐私权限。

可复现的核心回归命令（仓库根目录）：

```sh
cd agent-service
REVIEW_TODAY_LLM_PROVIDER=openai_compatible .venv/bin/python -m pytest -q tests/test_product_continuation.py tests/test_material_routing.py tests/test_execution_policy.py tests/test_response_stream.py
```

原生回归命令（仓库根目录）：

```sh
python3 tests/mac/run-contracts.py ConversationControlTests ConversationReplayTests LearningInputContractTests
```

## 真实模型回放及证据边界

回放使用独立临时数据库和合成的 Mello 岗位／产品内容；模型为当前配置的 `deepseek-flash` 与 `deepseek-v4-flash`。没有把用户真实聊天发给模型，也没有写入日常数据库。模型输出、路由决定、调用计数与结果保存在同目录 `live-*.json`。

每批八轮：缺 JD → 补 JD 后中断 → 询问微信能力 → 发小程序分享链接 → 补首页文字 → 明确重试 JD → 局部产品追问 → 查询公开介绍。

- 四批均通过八轮路由与任务状态断言：产品补充没有再次调用 `jd_analysis`，明确重试完成岗位分析，后续追问保留 JD 版本与待选问题。
- 这是**真实模型 + 受控故障**：首次 JD 输出在真实正文达到一定长度后主动注入 `TIMEOUT`，不是实测 90 秒断网；网页读取是失败夹具，公开检索在探针内显式关闭，不构成真实网页搜索可用性的证明。
- 90／30／180 秒规则由可控时钟与真实缩短时限的 watchdog 测试覆盖；没有为验收故意让用户真实会话等待超时。
- `live-1.json` 中发现对已补材料重复解释无法打开；`live-2.json` 中发现把未执行检索描述为结果为空；均据此修正提示。`live-3.json` 的检索说明正确，但仍出现从首页文字推断机制缺失的表述，随后增加明确的条件式建议规则。
- 最后一批 `live-4.json` 的产品回答明确区分推断与页面事实，没有再断言角色机制缺失；公开查询失败也明确为未执行。
- **仍有输出质量限制**：第四批 JD 回答仍以“职责第一条”解释最高准备优先级，说明提示约束尚不能稳定消除这类推断；也仍可能超过推荐短答字数、附带额外补材料建议。路由与任务状态的通过不等于这些措辞问题已全部解决；没有加入额外模型审稿调用，也不会以截断正文的方式强行满足字数。

真实模型探针需显式 `--live`，会产生模型调用费用，默认测试不会运行它：

```sh
cd agent-service
.venv/bin/python -m tests.product_continuation_real_smoke --live --output /tmp/review-product-new-replay.json
```

## 日常 App 与数据

- 更新原有 DerivedData 路径的开发 App，没有另造用户入口；更新前已备份 App 和数据库。
- 重启后服务健康，原会话可打开，底部可见“生成超时，已保留未完成的回复”和重试入口。
- 启动前后 20 条消息、6 个会话、8 条知识、11 道题、8 条复习状态、3 轮复习和 3 条复习作答均保留。消息与学习数据逐行匹配备份；服务会话持久化内容与备份相同。
- App 启动后的会话表变化只涉及 SwiftData 版本号、恢复检查点确认信息和材料建议同步版本；没有改写历史正文或替用户发送消息。
- 旧的半截回复不会被安装操作自动补写；在原会话点击“重试”，或明确要求重新分析 JD，才会生成新结果。旧的过时缺材料阶段在下一次处理时根据已保存材料纠正，不重写历史事件。

## Rex 验收路径

进入原会话，先补小程序链接或一张产品页面截图，预期只承接产品问题、保留岗位任务；然后明确“重新分析刚才的 JD，给完整优先问题”，预期完成岗位分析并出现问题选择。还可在生成中停止，确认保留已输出内容且停止后不会继续写入。

本轮没有重新验收微信跨 App 拖拽、实际小程序读取或公网搜索服务；沿用现有图片入口与模型配置。
