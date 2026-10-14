# MEM-02 实施与分项验证

2026-10-14，Rex 明确选择「按这个范围修复（推荐）」，决策 232 已备案，先同步 [Harness](../../agent-harness-v2.md#memory-recovery-stop)。生产仅修改 [LearningMemory.swift](../../../Review_Today/LearningMemory.swift) 的失效状态投影：依赖已失效时，`recovering` 与 `streaming` 回复都即时改为 `interrupted`，不再要求 Run 仍处于运行中；停止或回执先到也保持这一结果。原 Run 的停止、版本与控制处理不变，正文、完成历史、无关联回复及恢复次数／保存规则保留；不扩大一般停止／归档、自动记忆或模型语义判断。

## 实际验证

- [LearningMemoryContractTests.swift](../../../tests/mac/LearningMemoryContractTests.swift)新增运行中／停止中／已收到中断回执三个状态场景：依赖被排除后，恢复回复立即中断，正文与完整历史保留，另一会话的恢复回复不受影响；重复失效不新增停止请求或清除后来独立的确认。最终支持模块重新构建，五组原生记忆、会话删除、知识库管理、回放及控制合同与受控 SSE 通过，见 [native-tests-final.log](native-tests-final.log)。首轮单场景的用例归属调整与编译日志保留，最终三状态已由本次完整原生合同重新执行，不用首轮结果替代。
- [run-repair.py](run-repair.py)基于保留夹具，只替换获准修复的状态预期，使用重新编译的支持模块。六个原场景通过，[native-fixed.json](native-fixed.json)四个旧状态缺口均消失；引用失效、正文拦截、历史与正式复习、重新允许使用等原结果保持。
- 同一份生产服务公共页和停止回执原样重放，[paired-fixed.json](paired-fixed.json)显示本机排除后已为中断，有效回执后和新事件页后均保持中断；另以真实原生 `queueControl`／`deliverControl` 先接收回执，再排除来源，[paired-stop-first-fixed.json](paired-stop-first-fixed.json)同样通过。原文不变，迟到合成修复结果未发布。两个 SDK 回调调用和公共页为上一阶段的受控编排输出；本次没有供应商调用或完整 HTTP 链，不把离线重放当作真实模型验收。
- [service-tests-final.log](service-tests-final.log)：十项服务记忆／纠正检查通过，四十七项非本范围未运行，保留五条既有弃用 warning。没有修改服务源码或重复全量服务测试。
- [build.log](build.log)：普通签名 Debug 构建成功，严格签名检查通过。原日志路径、散列与行尾空白规范化见 [repair-log-manifest.json](repair-log-manifest.json)。

## 本机交付与界面边界

补查停止回执先到的顺序，首轮只在活动 Run 分支内改状态仍失败，见 [原失败源码](stop-receipt-order-initial.swift)与[日志](stop-receipt-order-initial.log)。这属于已确认的依赖失效即时中断范围：把未完成正文状态结算与 Run 是否仍活动分开，保持原停止／版本处理；随后扩为三个运行状态及两种真实事件／回执顺序重新验证。首轮程序、构建、签名安装和 QA 阶段单独保留，不能作为最终版本证明。

[local-install.json](local-install.json)记录：日常 App 和 8742 服务未运行，原 App、完整应用支持目录及三个 SQLite 一致快照已备份。首轮更新后，最终更新前再次逐表核对与备份覆盖一致，复用数据备份并另存首轮 App；候选与最终安装 App 严格签名有效，标识／签名团队保持。三库完整性正常，全表内容与结构摘要相同。没有启动日常 App／服务或写入聊天，下次打开使用最终版本，非发布；首轮安装另见 [first-pass-local-install.json](first-pass-local-install.json)。

[NativeMemoryQA.swift](NativeMemoryQA.swift)使用真实生产 `LearningWorkspace` 和同批服务事件，只加隔离检查控制条，数据为 SwiftData 内存模型，预览模式不可发送。首轮后台子进程未持续运行，改用受控前台会话；CUA 两次报告锁屏，未操作窗口，之后关闭。上述记录仅为历史，见 [锁屏记录](native-window-blocked.json)与[首轮初始状态](native-window-initial.json)，不能作为最终版本的 UI 证明。

## 解锁后的原生检查

Rex 回复「已解锁，继续界面检查」后，在 macOS 27.0.1（26A434）启动链接最终支持模块的 QA 包，按 Apple UI Review 契约检查本次状态修复。CUA 实际操作及截图、辅助功能树与程序状态分别记录在[窗口结果](native-window-final.json)；本轮未再修改或替换生产 App。

| 实际操作 | 观察结果 |
| --- | --- |
| 打开隔离窗口 | 先显示「正在整理完整回复」及原合成初稿，发送入口提示预览不可发送 |
| 点击「排除来源记忆」 | 尚未同步停止回执时，正文下立即显示「回复已中断」；原文完整保留 |
| 点击「同步停止结果」 | 生产回执与后续事件同步后仍为中断，原文不变；检查模型始终为零知识卡／零正式复习 |
| 浅色与深色 | 使用现有产品调色与系统字体，正文、中断提示和运行状态正常显示 |
| 系统窗口菜单收窄 | 原始截图由 2080×1640 变为 1522×1898 像素；约 761 点宽的窗口中，正文、提示与操作入口可见，没有新增裁切或重叠 |
| 展开运行详情、滚动后收起 | 历史事件保留，末尾为停止状态；正文与「回复已中断」可到达，收起后稳定显示 |

主题检查入口最初只设置内部颜色方案，被外层产品主题覆盖。仅为 QA 开关接入现有 `AppearanceController`，重编译并验签后重新操作通过；其独立 bundle 使用自己的偏好域，不修改日常主题。初次功能操作保留为[主题接线修正前的记录](native-window-functional-before-theme-fix.json)。两次边缘拖动未改变尺寸，改用系统 Window → Move & Resize → Left，实际得到上述窄窗，不把失败尝试当作尺寸验证。

查看[即时中断截图](ui-default-dark-immediate.jpg)、[同步后截图](ui-default-dark-synced.jpg)、[窄窗深色](ui-narrow-dark.jpg)、[窄窗浅色](ui-narrow-light.jpg)和[展开详情后的正文](ui-narrow-details-bottom.jpg)。这些是 CUA 返回的原始 JPEG，没有重绘或转换。辅助功能树见[最终记录](native-window-final-ax.txt)：中断文字、运行详情的名称／展开状态、正文及发送限制均存在；这只证明所检查语义，不等于完整 VoiceOver 或键盘独立完成任务。

检查范围内没有发现新的可行动产品缺陷。QA 已正常退出；[检查后核对](native-window-post-check.json)确认三个日常数据库各表内容／结构仍与原一致快照相同，模型配置与既有工程差异保留，日常 App／8742 服务未运行。原七个基线文件散列不变，生产源码与已交付版本一致，旧失败和锁屏记录保持。

复核入口：按[启动信息](qa-launch.json)的预览环境启动隔离包，先观察恢复提示，再依次操作排除与同步；不可无环境参数直接打开 QA 包。日常入口仍为 Agent 的来源会话记忆排除／知识库回收操作，只有依赖该来源的回复被停止；其他回复和独立卡片规则由原生合同覆盖。

真实供应商与完整 HTTP 恢复链、自然语言纠正识别质量、日常完整操作链、完整 VoiceOver／键盘完成、文字放大、最小高度及更宽窗口未在本轮检查；本次未新增动效，减少动态行为未另跑。最终视觉与日常使用体验待 Rex 验收，程序通过和隔离原生检查不代替这些边界。
