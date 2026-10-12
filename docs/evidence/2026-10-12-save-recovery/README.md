# 停止与保存回执恢复：隔离复现

2026-10-12，针对 ZCode 第 3 条已确认的停止、重试与有限恢复边界，检查现有代码的组合路径。初始定位与原始 JSON 保留在下方；Rex 随后授权实施，现已修复、验证并更新本机开发 App，待 Rex 体验。最终状态以 [TOOL-01](../../work-status.md#tool-01) 为准。

## 方法与结果

复用仓库 `ConversationTests.make_committable()` 合成夹具，模型、知识生成和搜索能力均受控；运行实际 ConversationHarness、临时 SQLite、领取提交、停止和回执方法。没有调用日常服务、读取日常数据库或真实模型。Mac 端是否已落盘由场景假设区分，卡片 ID 是夹具值，不能作为真实原生写入证据。

| 场景 | 实际执行结果 | 验证边界 |
|---|---|---|
| 已领取，假设 Mac 已保存但 ACK 未送达，随后停止 | 原运行版本从 1 变为 2，提交版本仍为 1；再次领取报 `RT.TASK.COMMIT_REVOKED`，任务保持 `committing`。直接补 ACK 则变为 `completed`，会话仍暂停、前台运行仍为空 | 验证真实服务方法与状态转换；Mac 落盘是模拟前提 |
| 已领取，假设 Mac 尚未写入，随后停止 | 再次领取同样被拒绝，保存包仍保留；没有发送虚假成功 ACK | 验证未写入窗口不能用补成功回执处理；未验证显式恢复后的原生全流程 |

原生源码的关联路径：`HarnessProcessor.synchronize` 对 `committing` 先领取提交，再进入本机保存与 ACK；`commitMemory` 在领取后再次检查本地停止／补充。已保存的展示由 `memoryCommitted` 与真实知识引用优先决定，未发现此处把已保存知识卡显示成未保存。

因此，受控证据证明再次领取会被停止后的版本检查拒绝；结合原生当前调用顺序，已保存后的后台状态同步存在被该检查阻塞的路径。**这不是丢卡、重复卡片或日常用户界面故障的实测证据。**

## 回放

从仓库根目录执行：

```sh
agent-service/.venv/bin/python docs/evidence/2026-10-12-save-recovery/repro.py
```

[旧顺序脚本](repro.py) 在导入服务前隔离默认存储并清空本进程服务凭证，复用受控夹具；只在临时目录创建数据库，JSON 输出到标准输出。[原始结果](result.json) 来自修复前的执行。该脚本直接重现旧的再次领取顺序，exit 0 只表示旧请求仍按版本守卫被拒绝；新恢复链改为直补真实回执或释放未落盘领取，没有放宽这个守卫。不能把旧脚本当作修复后的验收标准。

## 已授权的最小修复与验证

- 只有实际本机保存记录与对应卡片引用能证明已保存时，才直接补同步原回执；不重新领取写入权限或重写卡片。
- 未写入的提交继续服从停止、内容版本和归属检查；不能统一放宽重复领取，也不能以预期卡片 ID 伪造成功。领取后尚未落盘即停止的状态收尾与显式恢复须一并验证。
- 补充原生与服务之间的故障回归：保存成功／ACK 失败／停止／再次同步，以及领取成功／本机未写入／停止；确认卡片数、实际保存展示、后台完成状态及队列暂停。

Rex 回复「开始」后已按上述范围实施：持久化回执直接 ACK，未落盘且失效领取以原运行和 revision 幂等释放，同版本显式保存复用整理包；正常首次保存与恢复 ACK 分开，后者明确禁止续学。还补了“停止已送达，旧许可才返回”的本机 revision 检查。

新增服务回归见 [test_commit_recovery.py](../../../agent-service/tests/test_commit_recovery.py)，原生磁盘回归见 [SaveRecoveryContractTests.swift](../../../tests/mac/SaveRecoveryContractTests.swift)。覆盖直接 ACK／重复 ACK、释放幂等、仍有效领取拒绝释放、旧运行／revision 拒绝、同版本重试复用、内容变化不复用、未存不能伪造 ACK，以及恢复通知不得提前续学。

原生到真实受控 HTTP 的两类链路见 [SaveRecoveryHTTPTests.swift](../../../tests/mac/SaveRecoveryHTTPTests.swift)与[桥接驱动](../../../tests/mac/run-save-recovery-http.py)：实际 SwiftData 保存后服务模拟 ACK 失败，再停止、同步完成；以及领取成功后先停止、本机零写入、释放、显式再保存。模型、生成和搜索仍使用合成夹具；不据此宣称真实供应商质量或最终用户体验通过。

## 最终验证与本机交付

- [标准受控脚本](controlled-final.log) exit 0：1113 passed、4 Chrome opt-in skipped、508 subtests，5 条已有弃用 warning。新增恢复文件及话题收尾的[最终定向检查](service-targeted.log)为 39 passed／2 subtests，这些已包含在全量结果中，不另外相加。
- [四组原生合同](native-contracts.log) exit 0：SaveRecovery、KnowledgeIngestion、TopicCapture、ConversationControl。实际磁盘落盘／回执超时／停止／恢复及重复同步通过；没有多生成卡片、覆盖保存后编辑或重发成功提示。未落盘停止、已经送达的停止、失效释放及显式重试通过；缺引用或仅内存标记不能伪造回执。
- [两类原生到 HTTP 链](native-http.log) exit 0：实际 FastAPI 路由＋原生 SwiftData，已存场景再次同步不领取，服务状态完成且仍暂停；未存场景零 ACK、释放后等待用户，显式重试沿用一次整理包。此 HTTP 服务使用临时存储和受控模型，不运行日常服务或真实供应商。
- [最终签名构建](build-final.log)成功；候选与安装版本均通过 `codesign --verify --deep --strict`。[安装记录](local-install.json)记录完整旧 App 和三个数据库的一致性备份；安装后所有数据库全表行数与内容摘要不变，完整性正常。当前日常 App 未运行，下次打开启动新版服务；没有在日常库制造故障或新增卡片。

初次原生夹具把连接超时错误预期为终态，已按既有连接恢复规则修正，见[初次日志](native-initial.log)。一次并行构建时源文件发生变动，编译器拒绝该次构建，见[中间日志](native-source-change.log)；随后冻结源码重建并完成上述验证。二者不算最终通过证据。

最终 GUI 操作与使用手感仍由 Rex 体验；本轮未运行真实模型生成，未以这些受控测试宣称教学质量或整个 M1 通过，也未最终发布。三条规则、决定与续接见 [TOOL-01](../../work-status.md#tool-01)。
