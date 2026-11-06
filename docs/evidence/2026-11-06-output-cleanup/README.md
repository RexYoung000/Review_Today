# output/ 空间清理与 276 离线入口修复（2026-11-06，真实 0／0）

本轮是本机维护动作，不是产品验证批次。未启动 App／服务，未打开正式数据库，新增模型请求 0、网页操作 0。

## 清理结果

| 项 | 清理前 | 清理后 |
|---|---|---|
| `output/` 体积 | 9.5G | 2.4G |
| `output/` 条目数 | 75 | 72 |
| 删除文件数 | — | 561 |
| 释放磁盘 | — | 约 7.7G |

删除内容分三类：

1. **Xcode 构建产物**——`default-brand-build`、`session-tools-build`、`ingestion-build`、`management-release`、`soft-blocks-release`、`material-check/DerivedData`、`glass-preview/daily-build-check`、`local-app-preflight-2026-10-22/build`、`ingestion-tests`、`default-brand-checks`。均可由源码重新构建。
2. **冗余历史应用数据快照**——`card-preview-backup-20261004-215447`、`card-preview-backup-20261004-222547`、`memory-backup-20261014-000742`、`steering-backup-20261013-174841`。五份同族快照的 `Backups` 清单指纹一致（`c7e02d65…`），已确认 `card-preview` 两份全树指纹一致（`8eb4e3f6…`）。
3. **无任何证据记录引用的孤立大文件**。

删除文件的路径与体积、以及被删除但仍可在原证据记录中查到的哈希关系，写在本机受限目录：

`~/Library/Developer/ReviewTodayEvidence.noindex/2026-11-06-output-cleanup/cleanup-manifest.json`（目录 0700／文件 0600，不提交 Git）

**保留项**：276 离线入口的三件承重文件（`output/daily-service-preflight-2026-10-25/backup-pins.json`、`…/activation/`、`output/managed-teaching-preflight-2026-10-25/runtime-pins.json`）；两份快照（`memory-state-backup-20261014-034238`、`local-app-preflight-2026-10-22`）；全部仍存在的历史证据引用文件；两个 archive tag 与 4 个 codex checkpoint ref。

## 已知不可逆损失

保留快照内有 **3 个历史回滚点被误删**：

- `Backups/before-settings-20260925-200417/`
- `Backups/before-stream-smoothness-20260927-230724/`
- `Backups/agent-harness-before-image-compaction-20260927-215101.sqlite3`

单份约 19–46MB。本机无 Time Machine、无 APFS 本地快照，私有归档中无同哈希副本，**无法恢复**。成因是清理脚本的"孤立大文件"规则未正确排除保留目录。其余 13 个回滚点、正式数据（`~/Library/Application Support/Review Today/`）与 17 份原备份均完好，17 份原备份逐份哈希复验通过。

## 276 离线入口修复

项目目录从 `~/Desktop/vibe coding/Review_Today` 迁移到 `~/Desktop/vibe coding/项目导航/01 个人产品/Review_Today` 后，276 入口无法运行。两处原因，均与本次清理无关，属搬迁后的既存失效：

1. **326 条旧根绝对路径失效**——`policy.json`、274／273 `setup.json`、`archives.json` 内的绝对路径仍指向旧根。处置：在旧根建立指向新根的符号链接，使 7 条策略锚点恢复可解析。该链接是本机安排，不提交 Git；移除链接即恢复原状。
2. **工程文件 pin 不符**——`project.pbxproj` 当前为提交版本 `854c6eac…`，而 274 pin 记录的是 2026-10-25 工作区版本 `ab9f204e…`，且当时的 `git diff` 非空。该版本在 2026-11-01 切回 `main` 时已不在工作区。

处置：从 Codex checkpoint `refs/codex/turn-diffs/checkpoints/a8ed3087b…/95b2ff3d…/1792990543350/df5662f8…` 取回 2026-10-25 版本并写入工作区。校验结果：

- 文件 `sha256` = `ab9f204e3bd83a413ba1f9ff684e9359f187ee3188cd3ebca807b4966fb48cca`，与 274 `source-pins.json` 完全一致
- `git diff -- Review_Today.xcodeproj/project.pbxproj` 的 `sha256` = `8b31e8d2938a6ff21062e1a8be6de940784ea729763136d4b54573fa52c63502`，与 274 `user_project_diff_sha256` 完全一致
- 两版**功能等价**：均声明 `XCLocalSwiftPackageReference` 指向 `Vendor/SwiftFSRS`、FSRS 产品依赖并链接进 Frameworks，差异仅为 Xcode 排版风格

**该文件保持未提交状态**——276 入口同时校验文件哈希与 `git diff` 哈希，提交或清理该改动都会使入口再次失效。

4 个 codex checkpoint ref **不予删除**：它们指向的 tree 中独占 blob 为 0 字节（内容已在对象库），删除不释放任何空间，且其中一份是上述工程文件版本的唯一副本；Codex 仍在本机活跃使用该仓库。

## 当前阻塞

macOS 清理 `/tmp` 后，276 基线中另有 **36 条历史证据路径缺失**，超出已批准的 121 条例外范围，入口停在：

```
Unapproved historical original missing: /private/tmp/review-today-fullflow-i9njdmrd.noindex/quota.json
```

36 条分布在 `review-today-fullflow-i9njdmrd`、`review-today-fresh-fullflow-c3g9rc3e`、`review-today-teaching-scope-fullflow-3pzbuq_i` 三个旧运行目录。**全部 36 条在私有归档中有同哈希副本**，与 276 的处理方式一致可机械执行；按 276 规则须经 Rex 确认后才扩展例外范围。

入口当前进度：策略锚点 7／7、当前源码与配置 pin 319／319、用户工程差异、正式七文件与依赖均通过；停在上述 36 条新增缺失。
