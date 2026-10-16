# KT-03：补充原预览时保留「先不保存」（2026-10-16）

Rex 已按决定 238 授权最小修复与零新增模型受控复验。本次恢复已有同点补充契约，不改变保存确认、版本、记忆／生命周期、真实新引文或一次修复上限；不新增 UI、模型或产品规则。原真实试跑与失败保留在 [EVAL-03](../2026-10-16-continuous-acceptance/resumed/README.md)，本批 20／30 与 STOP 不动，余 10 次本阶段不使用。

实现范围仅限明确同一目标的补充／纠正且附带拒绝保存动作时，仍将当前可编辑邀请交给回答步骤，并沿用现有更新指令。实际保存请求／确认、条件动作、其他操作、新话题和纯拒绝继续走既有边界。先新增能复现问题的受控流程，再修复并验证；实际模型引文错误仍应被拒绝，受控通过不代表本批真实更新成功。

## 实际交付

生产仅修改 `knowledge_invitation.candidates`：同一目标下的 continuation／continue_goal，具有 correction 或 followup，且所有附带动作均为 save／reject 时，保留原可编辑邀请。原任务、版本、纠正中状态、生命周期与记忆过滤继续生效；有实际保存请求／确认、条件或其他动作时不进入此例外。既有回答更新指令自动随非空候选加载，没有新增模型步骤、保存许可或 UI。

## 验证

| 检查 | 实际结果 |
|---|---|
| 修复前新增回归 | 3 failed／1 passed／7 subtests passed，补充／纠正拿不到原预览 |
| 修复后同组 | 4 passed／7 subtests passed：纠正替换、补充保留、无自动保存、旧按钮无效、错误新引文只修复一次后失败；七种其他操作／范围继续隔离 |
| 完整服务回归 | 1233 passed／4 原 Chrome opt-in skipped／556 subtests passed；5 项既有弃用警告 |
| DeepSeek 配置的邀请／预览组合 | 36 passed／20 subtests passed，受控模型替身，不是供应商实际请求 |
| 留存数据生产 Harness／公开事件页 | 真实失败前检查点＋同一句输入＋原路由／准备／回答正文；**更新元数据与预览为有依据的受控替身**，同一邀请 v1 → 纠正候选 v2 → 发布 v3，3 要点＋一句总结；学习步骤与理解状态保持，未入库 |
| 原实际错误输出 | 即使恢复候选，原三条新引文仍被 RT.MODEL.SCHEMA 拒绝，没有据此放行真实失败 |

初次回放脚本把内部 `preview` 字段当作公开字段断言，已改为核对既有公开 `preview_points`／`preview_summary`；原脚本失败日志单独保留，未因此改生产投影或 UI。

两份供应商配置、106 个 Swift 文件、其余 71 个生产 Python 文件、101 个前序证据、七个日常文件和原工程差异均保持；原首启／诊断／恢复三份归档 27／36／55 文件及清单保持，真实运行目录文件、旧批 30／30 和 STOP 保持。停止的测试服务没有重新启动。最终校核见 [result.json](result.json)。

## 续接位置

KT-03 已实现并完成零新增模型受控复验，服务下次启动加载。未替换日常 App，未重新检查原生窗口或真实模型新输出；原 EVAL-03 第 4 步失败仍保留，另题、原生保存、详情查询与保存后进度仍未执行。下一步先单独确认是否恢复原余 10 次，仅复验当前同点补充关卡，再按失败即停判断后续；本记录不自动恢复调用、不另开预算、不关闭完整八步验收。

复跑入口：在 `agent-service` 下用 `.venv/bin/python ../docs/evidence/2026-10-16-preview-deferral/test_runner.py -q`。该入口隔离存储、清空进程凭证并禁止公网连接；`--deepseek` 仅切换受控配置，不调用真实供应商。留存回放用 `agent-service/.venv/bin/python docs/evidence/2026-10-16-preview-deferral/replay_retained.py`，最终保护校核用同目录的 `finalize.py`。既有归档回放脚本维持修复前语义，不用新代码重写历史结果。

原始资料：[修复前](baseline-tests.log)、[修复后](fixed-tests.log)、[完整回归](full-tests.log)、[DeepSeek 组合](deepseek-tests.log)、[回放结果](replay-result.json)、[公开事件页](public-page.json)、[最初脚本字段假设失败](replay-initial-field-assumption.log)、[保护基线](setup.json)。当前工作位置由 [KT-03](../../work-status.md#kt-03) 维护。
