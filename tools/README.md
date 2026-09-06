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
