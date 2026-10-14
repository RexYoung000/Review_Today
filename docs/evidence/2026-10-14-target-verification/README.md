# TARGET-01：目标完成核验检查

2026-10-14，Rex 在 MEM-02 原生检查收尾后回复「继续」，沿既定位置检查目标核验。本批只检查现有完成边界并保存证据，没有新的产品决定或生产实现。Review Today 起点为 `933aadc`，ZCode 继续固定在 `29628c9acdb81b703bbd4080c207a0e7ce5e276e`；当前停点见[工作记录](../../work-status.md#target-01)。

## ZCode 可参考什么

固定版本的[完成核验契约](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/contracts/src/tools/target.ts#L196)要求按目标类型和每项要求判断，返回是否通过、原因和下一步。值得参考的是让完成判断对应具体证据，而不是只看一轮输出结束。

同时，[运行实现](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/core/src/runtime/methods/target-completion-verification.ts#L200)在格式无法解析、核验器尝试调用工具或非取消调用异常时采用默认通过；运行层据 `passed` 更新目标为完成。这是该编码 Agent 避免核验故障卡住续跑的产品取舍，不能作为学习已掌握或知识已保存的依据。用户取消另有停止处理，不概括成所有故障都放行。

本轮通过网页和固定提交的原始文件读取正文，下载散列见[检查元数据](review.json)。未安装依赖、运行 ZCode、调用其模型或重新执行形式模型。

## 本项目已有的完成依据

意图来源：[Harness 五模式与成果](../../agent-harness-v2.md#173-五模式与成果)、[小题与本节综合检查](../../agent-harness-v2.md#conservative-check-scope)及[保存回执恢复](../../agent-harness-v2.md#保存回执与未落盘领取的恢复2026-10-12已授权实施)。这些规则先前已确认，本轮不新增核验调用。

| 实际事实 | 完成边界与实现依据 |
| --- | --- |
| 本轮回答结束 | Run 可以完成，学习 Task 仍等待用户；两种状态独立更新，见[会话编排](../../../agent-service/agent_service/conversation.py)的 `drain`／`_publish` |
| 普通题答对 | 只记录绑定知识点，不能使用模型的整步标签升级整节，见[学习进度](../../../agent-service/agent_service/learning_progress.py)的 `guard_completion`／`record_check` |
| 综合题有完整当前答案依据 | 验证当前节；普通学习目标需计划各节均为验证状态，见 `_evaluate`。逐项引文守卫保证定位，语义是否足够仍依赖评分 |
| 问题攻克 | 独立作答和迁移追问两道门槛都通过后才完成目标，不能由一次通过替代 |
| 用户继续／跳过至计划末尾 | 可以结束讲解，保留未验证状态；显示「学习安排已讲解完毕」，不宣称掌握 |
| 评分格式失败、超时、意外异常或停止 | 保留输入与进度；失败可重试，停止丢弃迟到评分，不记为掌握 |
| 完成学习或形成草稿 | 尚未保存知识卡；保存生成、提交和匹配本机回执独立，见 `acknowledge_task` 与[保存恢复](../../../agent-service/tests/test_commit_recovery.py) |

## 实际执行

[inspection.py](inspection.py)复用既有受控夹具，调用生产 `ConversationHarness` 和暂存 SQLite。十一阶段检查全部通过，完整状态见[场景输出](scenarios.json)：普通题越权、综合缺依据、单节与全计划、跳过全部检查、独立与迁移两阶段、三类评分失败、停止后的迟到正面结果。正例能正常完成，负例保持未完成；十一阶段均未调用知识录入模型。合成评分只验证状态边界，不证明真实答案评分准确。

相关现有服务测试 **56 passed／38 subtests passed**，保留五条既有弃用警告，见[测试日志](service-tests.log)。覆盖综合条件、原文定位、提示、旧绑定、停止、问题攻克及保存 ACK／恢复；只有部分提交 HTTP 路由通过 TestClient 检查，未运行完整模型到 Mac 链路。

两个测试进程各使用临时全局库，并在进程内选择兼容夹具分支；模型、网页能力与知识生成均受控，没有真实供应商请求或日常数据库写入。生产源码与起点提交逐项一致，供应商配置和既有工程差异散列保持；不重新构建或替换 App。原始测试日志保留其警告与数字，提交归档仅规范行尾空白，原始与归档散列由[检查元数据](review.json)记录。

复核时，在 `agent-service` 使用虚拟环境执行 `PYTHONPATH=. .venv/bin/python ../docs/evidence/2026-10-14-target-verification/inspection.py`；输出另存，不覆盖本批证据。

## 结论与下一位置

本轮没有复现新的确定性完成缺口，现有完成／掌握／保存边界分项通过。保留这些机制与异常用例，暂不新增生产实现。此前语义评分误判仍是未通过记录，本轮没有重跑真实模型或将其改为通过；详见[SCOPE-01 证据](../2026-10-13-conservative-check-scope/README.md)。

真实语义准确性、自然语言路由、完整原生链路与 Rex 日常体验未验。下一研究位置为状态枚举与连续教学评测：先检查现有证据覆盖，再对齐实际缺口，不把形式模型枚举通过等同于本产品教学有效，也不据此启用新的日常核验器。
