# 旧记忆失效时机：MEM-02 只读检查

本页保存 2026-10-14 原只读检查，起点为 MEM-01 已交付的 `a8588fb`。当时 Rex 对下一检查项回复「继续」，只检查和备案，未取得实施回复。随后 Rex 已明确确认 232，本轮实现、验证、本机更新和解锁后的原生实测另见[实施记录](repair.md)，不再等待同一范围确认。当前停点由 [MEM-02](../../work-status.md#mem-02)维护，既有意图来源为 [Harness 三层记忆](../../agent-harness-v2.md#184-三层学习记忆)。

## 已核对的事实与缺口

`LearningMemory.valid` 的来源、版本与递归依赖守卫，`setAllowed` 的本机即时停止，知识库回收与会话删除的同事务失效，以及服务策略和最终发布检查均存在。六个隔离原生场景确认旧内容、摘要与候选被挡住，历史、独立卡片、正式复习和无关联会话保留；重新允许使用不复活旧引用。

修复前缺口在本机状态投影：[LearningMemory.swift](../../../Review_Today/LearningMemory.swift) 当时只把 `streaming` 回复标为中断，没有处理 `recovering`。生产 [conversation_model_call.py](../../../agent-service/agent_service/conversation_model_call.py) 会在已展示初稿后的一次格式修复产生后者；当前 [LearningWorkspace.swift](../../../Review_Today/LearningWorkspace.swift) 将其显示为「正在整理完整回复」。当时来源失效后，在离线／未收到新版本 Run 事件时仍有该提示；即使收到有效停止回执，后续事件页到达之前也保持。新版本事件能够修正为中断，旧最终正文未发布；不是永久停不下来或旧内容泄漏。

## 执行证据

- [MemoryInvalidationInspection.swift](MemoryInvalidationInspection.swift)调用生产原生失效与持久化方法，使用 SwiftData 内存模型；[native-baseline.json](native-baseline.json)六场景包含正常流式排除、重新允许使用，以及恢复状态下的排除／纠正／卡片回收／来源会话删除。四个显示缺口共用同一根因。脚本明确断言现有缺口，exit 0 不是修复通过。
- [service-probe.py](service-probe.py)执行真实服务编排：合成 SDK 初稿后格式失败，第二次受控修复等待期间排除来源，生成恢复和中断事件。公共页面直接来自生产 `session_events` 函数；[service-baseline.json](service-baseline.json)保留实际生成的页、回执与身份。两个回答调用是合成适配器调用，没有真实供应商请求；迟到合成修复结果被挡住。
- [ServiceEventReplay.swift](ServiceEventReplay.swift)将上述原页和实际公共 Run 回执交给生产 Mac 的 `persist`／`deliverControl`；[paired-baseline.json](paired-baseline.json)显示本机排除后和有效回执后都仍为 `recovering`，后续新版本事件后才是 `interrupted`。原文字保留，未生成知识卡或正式复习。这是跨组件离线重放，没有 HTTP 传输或真实 UI 窗口。
- 五组既有原生记忆、会话删除、知识库管理、回放和控制合同通过；支持模块复用此前的隔离目录，已核对本轮原生源码无变化及相关散列一致，不能把这次检查称为新 App 构建或安装。
- 十项服务记忆／纠正检查通过，四十七项非本范围未运行，保留五条既有弃用警告。没有为只读检查重复整套服务测试。

日志来源、基线散列、失败边界与未执行项由 [review.json](review.json)汇总；服务结果见 [service-tests.log](service-tests.log)，原生探针结果见 [native-probe.log](native-probe.log)。

初次原生夹具捕获尚未初始化的属性导致编译失败；修正夹具后，旧断言错误预期新版本 Run 事件也无法中断，被实际执行否定。修订观察边界为「即时／有效回执后／新版本事件后」再执行成功；初始失败日志与后续结果分别保留，不作为产品额外故障。

## 重放与候选范围

重现旧基线须使用修复前版本：在 `agent-service` 下，用虚拟环境、`PYTHONPATH=.` 和兼容测试进程分支运行 `service-probe.py`，新输出另存，不覆盖已归档 `service-baseline.json`；它在内部使用临时数据库。对应旧源码运行 `python3 tests/mac/run-contracts.py LearningMemoryContractTests SessionDeletionContractTests LibraryManagementContractTests ConversationReplayTests ConversationControlTests` 创建支持模块，再执行本目录 [run-native.py](run-native.py)并传 `--support-dir`；两个原生探针断言旧缺口，仅用于旧版本。当前已修复版本使用 [run-repair.py](run-repair.py)和新支持模块，结果另存，不改写已归档基线。

当时拟议只修被失效守卫停止的恢复回复立即标为中断，保留已展示正文、历史和原版本／停止／恢复次数／保存规则；该范围后来已确认并实施，其他扩大治理未确认。原只读阶段未运行真实供应商、完整 HTTP、原生窗口和自然语言纠正识别质量，未改生产代码、日常数据库、配置或 App；后续交付与未覆盖项独立记录。
