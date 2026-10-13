# 项目记忆第一小点：同名知识卡的检索身份

2026-10-13 只读检查与范围确认；2026-10-14 已按决策 231 完成最小修复、分项验证与本机备份更新。进度由 [MEM-01](../../work-status.md#mem-01)维护，契约见 [Harness](../../agent-harness-v2.md#memory-card-identity)。

## 初始证据

- [LearningMemoryInspection.swift](LearningMemoryInspection.swift)调用真实 `LearningMemory.candidates` 与 `valid`，使用隔离 SwiftData 内存模型。七场景覆盖空库、不同标题／同名双卡、同卡重复引用、版本更新、删除、没有卡片的学习记录与同概念归并。
- [native-baseline.json](native-baseline.json)：两张同名卡都通过真实卡片 URI 明确引用，库内两张、候选上限十二，实际仅一张。较新卡幸存，另一张身份缺失；脚本断言旧缺口，exit 0 不代表修复通过。
- [selection-probe.py](selection-probe.py)使用实际原生候选身份、合成其余选择元数据，调用服务 `select_references`；[selection-baseline.json](selection-baseline.json)显示异名双卡接受两张，同名双卡只接受一张。这不是完整 HTTP 抓包或真实模型选择。
- [native-tests-baseline.log](native-tests-baseline.log)：既有 LearningMemory 与 SessionDeletion 合同通过；当前原生源码未修改，复用此前构建的隔离支持模块。后续改源码须重新构建，不能用旧模块证明修复。
- [service-tests-baseline.log](service-tests-baseline.log)：记忆守卫九项通过，四十八项非本范围未运行，五条既有弃用警告。
- [baseline-review.json](baseline-review.json)保存起点提交、源码／复现文件散列、原工程差异及日志来源。此阶段没有日常数据库写入、供应商请求、App 更换或发布。

## 重放边界

[run-native.py](run-native.py)仅用于旧版本基线。先在对应旧源码版本运行 `python3 tests/mac/run-contracts.py LearningMemoryContractTests SessionDeletionContractTests`，再传入其打印的隔离目录 `--support-dir`；此脚本明确断言旧故障。选择基线在 `agent-service` 下用现有虚拟环境及 `PYTHONPATH=.` 执行；脚本内部使用临时服务数据库。

## 实际修复与验证

生产仅修改 [LearningMemory.swift](../../../Review_Today/LearningMemory.swift) 的候选去重入口：知识卡使用 `knowledge_id`，学习记录继续使用会话与概念。没有变更排序、十二候选上限、服务两条关联上限、版本／排除守卫、模型、知识保存授权或界面。

- [LearningMemoryContractTests.swift](../../../tests/mac/LearningMemoryContractTests.swift)新增七组行为检查：同名双卡、同卡重复、无标题同目标、改名／版本更新、删除、学习记录归并及不同会话保留、十三同名卡的十二条上限与原排序。全新支持模块重新编译后，记忆、删除、输入和回放四组原生合同及受控 SSE 通过，见 [native-tests-final.log](native-tests-final.log)。
- [run-repair.py](run-repair.py)在保留的原 Swift 夹具上，只调整同名双卡的预期与报告阶段，并将两张卡身份固定为旧报告同一组身份。调用全新原生模块，七个原场景均通过；[native-fixed.json](native-fixed.json)的同名双卡从一条变为两条，缺失身份为空。复现源与旧输出逐项散列不变。
- [selection-repair.py](selection-repair.py)使用上述真实原生身份，在未修改的服务选择入口回放；[selection-fixed.json](selection-fixed.json)显示两张请求关联均可接受。其余元数据仍是合成数据，不是完整 HTTP 抓包或真实模型选择。
- [service-tests-final.log](service-tests-final.log)：服务记忆守卫九项通过／四十八项非本范围未运行／五条既有弃用警告。未为本次原生去重改动重复整套服务测试。
- [build.log](build.log)为普通签名 Debug 构建成功日志；[final-log-manifest.json](final-log-manifest.json)保留原始日志路径及散列，提交日志只裁剪行尾空白和末尾空行。
- [local-install.json](local-install.json)：当前日常 App 与服务均未运行，App 原包、完整应用支持目录与三个 SQLite 一致快照已备份。候选与安装包严格签名有效、标识与签名团队保持、可执行文件散列一致。三库完整性正常，全表内容及结构摘要前后不变；没有启动日常 App／服务或触发真实供应商调用。下次打开本机 Debug App 生效，非最终发布。

后续可用 `python3 tests/mac/run-contracts.py LearningMemoryContractTests SessionDeletionContractTests LearningInputContractTests ConversationReplayTests` 构建新隔离支持模块，再用其打印目录运行 `run-repair.py --support-dir ...`，结果保存为 `native-fixed.json`；在 `agent-service` 下用虚拟环境和 `PYTHONPATH=.` 执行 `selection-repair.py`。不要将旧支持模块当作新源码或签名包的证明。

## 使用验收与边界

重开 Review Today 的 Agent 聊天，在原知识卡选择入口先后加入两张同名卡，再提问比较其内容。现有选择器每次选择一张后关闭，需要重新打开加入第二张；本轮没有改成多选界面。已验证检索不再按同名丢掉不同身份，界面布局及知识保存行为保持。

没有运行真实模型到原生的双卡回答或最终使用验收；候选齐全不保证模型选择两张或语义回答正确。自动后台记忆、其他检索覆盖率、修改卡片与新增调用均未扩大授权。下一点检查纠正／排除／删除后的旧记忆失效时机。
