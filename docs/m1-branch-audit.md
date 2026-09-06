# M1 分支与工作树核对（2026-09-06）

Rex 先授权合并 issue 10–16，随后明确要求“你先帮我合入 #17 吧”。两批均已完成：PR #18–25 已合入 main，对应本地和远端分支已删除。现在本地和远端均只有 **1 条分支 main**，项目只有 **1 个工作树**。Issue #17 继续保留用于完整体验验收，分支清理不等于里程碑验收完成。

## 当前保留

| 分支 | 状态 | 用途 |
|---|---|---|
| `main` | 当前工作分支；已包含 PR #25 合并提交 `903b620` | issue 10–16 基线及后续 Harness、学习记忆、DeepSeek、UI、256K 与启动修复；原本仅在本地的 Opal 研究归档 `2f8533f` 也完整保留 |

## 已合并并清理

全部使用保留历史的 merge commit 合入 main；完成后逐个确认本地/远端分支 tip 都是 main 的祖先、没有打开的 PR 继续以它们为 head/base，再删除分支。

| Issue | PR | 结果 |
|---|---|---|
| #10 | [#18](https://github.com/RexYoung000/Review_Today/pull/18) | MERGED；本地和远端 `m1/issue-10` 已删除 |
| #11 | [#19](https://github.com/RexYoung000/Review_Today/pull/19) | MERGED；本地和远端 `m1/issue-11` 已删除 |
| #12 | [#21](https://github.com/RexYoung000/Review_Today/pull/21) | MERGED；本地和远端 `m1/issue-12` 已删除 |
| #13 | [#20](https://github.com/RexYoung000/Review_Today/pull/20) | MERGED；本地和远端 `m1/issue-13` 已删除 |
| #14 | [#22](https://github.com/RexYoung000/Review_Today/pull/22) | MERGED；本地和远端 `m1/issue-14` 已删除 |
| #15 | [#23](https://github.com/RexYoung000/Review_Today/pull/23) | MERGED；本地和远端 `m1/issue-15` 已删除 |
| #16 | [#24](https://github.com/RexYoung000/Review_Today/pull/24) | MERGED；本地和远端 `m1/issue-16` 已删除 |
| #17 | [#25](https://github.com/RexYoung000/Review_Today/pull/25) | MERGED；本地和远端 `m1/issue-17` 已删除；Issue #17 仍 OPEN |

对应 issue 10–16 随 PR 合入默认分支关闭。issue #17 与父 issue #1 仍 OPEN，不代表完整 M1 已通过 Rex 体验验收，也不进入 M2。

## 复核与保留证据

### PR #25 合入（2026-09-06）

- 候选提交 `5794114a96ce86c710634a00ded74ea1535c8f6d` 含 36 个尚未进入 main 的提交、122 个变更文件。普通 merge commit `903b6208940cc468940072924c6808e5821acd8b` 保留全部历史，其树与候选完全一致；随后将本地 main 快进并切换到 main，未回退运行中的 App 源码。
- 本次重新运行 **194 项无密钥服务测试、全部 Mac 契约与 loopback SSE、旧磁盘模型迁移、macOS Debug / Release 构建，全部通过**。日志 `/tmp/review-today-pr25-service.log`、`/tmp/review-today-pr25-contracts.log`、`/tmp/review-today-pr25-migration.log`、`/tmp/review-today-pr25-debug.log`、`/tmp/review-today-pr25-release.log`。编译检查关闭签名；日常签名与原生验证沿用源码未变的验收 §0.18 证据。
- 删除前确认远端分支仍指向上述候选，全部提交已是 main 的祖先，且没有打开的 PR 以该分支为 head/base。删除后本地/远端仅 main、1 个工作树；PR #25 为 MERGED，Issue #17 与 #1 均 OPEN。
- PR 标题与说明已按最终实施和证据重写，旧 HTTP 403、132 项测试及“快照恢复待实现”不再作为当前 PR 状态。完整学习/入库、交接与记忆组合、Rex 视觉体验验收继续由 #17 跟踪；不启动 M2，不发布。
- 候选提交的 GitHub Actions run `34022021651` 因账户付款/消费额度限制未启动，不能视作远端测试通过；本次没有改变账单、保护规则或使用管理员绕过合并检查。

### issue 10–16 前批合入

- 审查了本批结构/来源校验、评分与 ACK、客户端保存和失败恢复的关键改动，以及各 PR 既有真实模型和原生证据；保留完整体验验收在 #17。
- 对实际拟合入的基线树 `587e82b232557cc33756942eefbdd6f10b4a9600`（issue-16 + 原本地 main 的研究记录）在 `/tmp/review-today-premerge-10-16` 独立导出验证，未创建额外 Git 工作树：**20 项无密钥服务测试通过，macOS Debug / Release 构建通过**。日志 `/tmp/review-today-premerge-service.log`、`/tmp/review-today-premerge-debug.log`、`/tmp/review-today-premerge-release.log`。
- PR #21 仅 `docs/m1-acceptance.md` 有追加记录冲突；用此前 `96109f9` 中已经整合的版本保留评分与本地提交两份记录。新提交 `39e40ed` 是普通 merge，没有重写分支历史。其余自动合并内容与该历史整合树一致。
- 7 个 PR 合并后的树与原 issue-16 完全一致；保留研究记录后的 main 树与上述已验证树完全一致。本地 issue-15 原本多出的 `9d316ba` 已完整进入 main，没有丢弃提交。
- `2f8533f` 原始研究提交及附件已保留在 main / origin/main，也同步进当前 issue-17。同步后与修复交付点 `3e63aae` 比较，`Review_Today`、`agent-service`、Xcode 工程没有代码差异，当前日常 App 无需回退或重建。
- 分支删除前引用备份 `/tmp/review-today-precleanup-refs.txt`；合并提交对应表 `/tmp/review-today-merged-pr-results.jsonl`。该批完成时 PR #18–24 为 MERGED，PR #25 仍打开并改为基于 main；后续合入结果见上方。
- issue-17 远端 Actions 在此前提交上的失败原因是账户付款/消费额度限制，任务未启动；没有将其报告为远端测试通过，也未修改账单、保护规则或绕过检查。上述本次合并基线的验证为本机独立运行结果。

后续前置分支在 PR 合并、提交已进入主线且无未合并 PR 依赖后及时清理；尚未完成的工作保持在明确的活动分支中。
