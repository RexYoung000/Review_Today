# M1 分支与工作树核对（2026-09-06）

本次已 fetch --prune，核对本地/远端提交图及 GitHub issue/PR。只有 **1 个工作树**（当前项目路径），共 **9 条本地分支**（main + issue 10–17）。多的是分支引用，不是复制了 8 份工作区。

## 分类与处理

| 分类 | 分支 | 当前事实 | 处理 |
|---|---|---|---|
| 已合入 main、可直接清理 | 无 | #10–17 和对应 PR 均 OPEN、未合并 | 本次无符合条件的删除项 |
| 前置代码已包含在当前分支，待审/待收口 | m1/issue-10–16 | 各分支 tip 均为 issue-17 的祖先；仍有打开的 PR，部分也是后续 PR 的基线 | 保留远端依赖和本地引用，不当作已验收完成 |
| 当前开发与验收 | m1/issue-17 | 包含 10–16 及后续 UI/Harness 修复；#17 尚未获得完整 Rex 验收 | 继续当前分支，不额外创建工作树/分支 |
| 主分支及独立本地记录 | main | 本地比 origin/main 多 2f8533f：Opal 研究归档；该提交不在 issue-17 | 保留，不覆盖或删除 |

## 待审 PR 依赖

| Issue 分支 | PR | PR 基线 |
|---|---|---|
| 10 | [#18](https://github.com/RexYoung000/Review_Today/pull/18) | main |
| 11 | [#19](https://github.com/RexYoung000/Review_Today/pull/19) | m1/issue-10 |
| 12 | [#21](https://github.com/RexYoung000/Review_Today/pull/21) | m1/issue-10 |
| 13 | [#20](https://github.com/RexYoung000/Review_Today/pull/20) | m1/issue-10 |
| 14 | [#22](https://github.com/RexYoung000/Review_Today/pull/22) | m1/issue-12 |
| 15 | [#23](https://github.com/RexYoung000/Review_Today/pull/23) | m1/issue-14 |
| 16 | [#24](https://github.com/RexYoung000/Review_Today/pull/24) | m1/issue-15 |
| 17 | [#25](https://github.com/RexYoung000/Review_Today/pull/25) | m1/issue-16 |

11/13 曾通过本地 merge 提交汇入后续分支，但 GitHub PR 仍打开；这不是合入 main。另有一个引用差异：本地 issue-15 指向 9d316ba（与 issue-16 相同），远端 issue-15 停在 9d81b3e，本地 ahead 1。该提交已在远端 issue-16/17 保存；本次不重置或擅自推送 issue-15 来改 PR 范围。

当前没有依据把全部前置问题都认定为验收通过。建议后续先独立审查各 PR 与对应 issue 的完成证据，再经 Rex 授权处理 PR 合并/收口，合入主线且不再被未合并 PR 引用后删除相应本地和远端分支。普通 commit/push 授权不包括合并 PR 或关闭验收。本次不修改 issue 状态、不合并 PR、不删未合并分支。
