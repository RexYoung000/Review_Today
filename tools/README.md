# 本机应用包管理

日常唯一入口固定为 `/Applications/Review Today.app`。只用已核验的日常签名包更新此路径，不能因为整理入口顺带发布尚未批准加载的修复；更新前退出 App、保留可恢复归档，更新后核对包内容与签名。

开发构建与 QA 包使用 `.noindex` 临时目录；验收结束先退出，再注销该包的 LaunchServices 注册并压缩归档。回退包存入 `~/Library/Developer/ReviewTodayAppArchives.noindex/`，压缩后实际解包核对内容再收起原 `.app`，不在工作区或 Application Support 的数据备份里保留可被搜索的副本。禁止把包含旧 `.app` 的备份递归复制到下一份数据备份。

历史证据中记录的原始 App 路径可能已经归档，需按本批目录中的映射恢复到 `.noindex` 隔离位置；不能改写旧校验结果或据此启动日常服务。数据、配置、账本与旧调用额度独立保留，不随应用入口整理而清理。首次整理记录见[单一入口证据](../docs/evidence/2026-10-22-single-app-entry/README.md)。

# 三条历史删除记录的兼容

`repair-legacy-deletion-lifecycle.py` 只处理决定 260 固定的三条记录，不是通用生命周期迁移。默认只检查，`--apply` 才在隔离副本中执行；目前不接受日常目录。固定清单由 `legacy-deletion-lifecycle-scope.json` 单独维护并由工具校验指纹，不允许命令行扩大对象。

工作目录须为本项目 `output/legacy-lifecycle-repair-2026-10-22/` 的子目录，或 `/private/tmp/review-today-legacy-lifecycle-*.noindex/`。提供 `app.store`、`checkpoint.sqlite3` 和 `archive-proof.store` 三份实际副本；工具匹配原删除队列、三份后台内容和固定旧备份，确认这三条本机实体均已不存在且旧状态已归档，只补入两个缺失字段。成功前保留一致备份，三条共用事务；失败回滚，不清除原标记，不发送删除请求。

后续清理仍使用既有原生和服务代码，并独立核对实际回执。当前授权只到隔离复验；日常加载／历史数据处理另行对齐。具体结果见[本批证据](../docs/evidence/2026-10-22-legacy-lifecycle-repair/README.md)。

# 旧知识库接回

`import-legacy-library.py` 配合 SwiftData 写入器，只用于本轮已核实的旧库结构。它不是通用快照恢复器，不导入 Agent 会话、草稿、任务或 outbox，也不推断历史卡片的创建归属。

先退出日常 App，再在数据库副本上演练。Python 入口使用 SQLite backup API 同时备份源库和目标库（包括 WAL），按原 ID / 内容检查冲突后才调用 Swift 写入器；一笔事务写入，不覆盖同 ID 的现存内容。导入后逐字段检查源数据、关联和排期，并重复执行一次验证幂等。不要直接调用写入器绕过检查。备份和含正文的临时文件不得提交到 Git。

在仓库根目录编译：

```bash
sources=()
for file in Review_Today/*.swift; do
  case "$file" in */Review_TodayApp.swift) ;; *) sources+=("$file");; esac
done
xcrun swiftc -parse-as-library -D DEBUG -swift-version 5 -default-isolation MainActor \
  "${sources[@]}" tools/import-legacy-library.swift -o /tmp/review-today-library-importer
```

通过 Python 入口指定 `--source`、`--target`、一个尚不存在的 `--backup-dir`，以及 `--importer /tmp/review-today-library-importer`。先把 target 指向独立副本；正式导入前核对路径和备份。失败时停止，不自动覆盖现场，可用本次 `current.store` 备份进行受控恢复。

本轮接回 8 张卡、11 个问题、8 条排期、1 个必要来源及 3 条预览练习。旧库没有完成时间，预览保持 preview，不补造正式复习。4 个无练习记录的未完成旧复习窗口不导入、不恢复执行。

写入器的 `--seed-deletion` 和 `--fail-before-save` 仅供 `/tmp/review-today-` 下的隔离验收使用；前者建立删除样本，后者在保存前抛错验证事务回滚。实际导入与回归证据见 [M1 验收记录](../docs/m1-acceptance.md) 末节。
