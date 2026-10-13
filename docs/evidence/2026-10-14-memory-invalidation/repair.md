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

[NativeMemoryQA.swift](NativeMemoryQA.swift)使用真实生产 `LearningWorkspace` 和同批服务事件，只加隔离检查控制条，数据为 SwiftData 内存模型，预览模式不可发送。首轮构建与初始模型加载成功；首个后台子进程未持续运行，改为受控前台会话保持窗口。CUA 两次报告 Mac 锁屏、自动解锁不可用，已请求手动解锁；未进行按钮操作、原生实看、浅深色／窄窗或辅助功能验收，自己的 QA 进程已关闭。最终原生源码续修后，QA 已重新编译链接最新支持模块，尚未启动；详见 [锁屏记录](native-window-blocked.json)、[首轮初始状态](native-window-initial.json)与[最终启动信息](qa-launch.json)，后续使用其中的预览环境启动，不能无环境参数直接打开 QA 包。首轮日志有临时 QA 包的 sandbox extension 提示，初始模型仍已加载，不用此日志宣称窗口可见。

解锁后的隔离入口：检查窗口先显示服务实际生成的「正在整理完整回复」；点击控制条「排除来源记忆」，生产正文下应立即显示「回复已中断」，原合成初稿保持；再点「同步停止结果」，提示与原文保持。实际日常入口仍为 Agent 的来源会话记忆排除／知识库回收操作，只有依赖该来源的回复被停止；正式卡片独立于原会话的规则保持。

旧检查脚本、输出及其七个来源文件散列保持。原生窗口实看、真实模型与完整 HTTP、自然语言纠正识别质量及 Rex 体验没有当作完成；实现、程序检查和签名交付各自成立。
