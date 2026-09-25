# 设置与本机数据管理 · 2026-09-25

已接入并打开本机日常 App；最终视觉与动效节奏待 Rex 体验。

## 入口与行为

侧栏底部「设置」或 macOS 设置快捷键 → 通用 / 复习与提醒 / 数据管理 / 高级。结构参考已实看 Typeless 原生设置；沿用 Runway 纸面、黑白层级和原生控件。

数据管理支持重置复习进度（保留知识、聊天和参与状态，已参与内容立即到期）与清空全部学习数据。模型、API Key、偏好保留。确认页复核范围；清空全部要求输入“清空”；运行中拒绝，保存失败回滚。离线后台副本保留清理队列与无正文删除标记，不能表达成供应商零留存。

## 已验证

- Xcode Debug 构建成功，装入原日常 App 路径；服务 OpenAPI 包含新清理端点。
- 原生 LocalDataResetContractTests：预览不删、事务回滚、知识/参与/偏好保留、立即到期、范围变化、运行中拒绝、清空、删除标记、离线/缺回执不丢清理队列、成功回执、重复执行及控制器失效。
- ReviewControllerContractTests 与 SessionDeletionContractTests 回归通过。
- ReviewMigrationContractTests：WAL 一致备份、幂等与失败不标记；专属目录导入保留旧库，拒绝不相关默认库，再次打开不重复导入。
- Python `tests.test_local_data_cleanup tests.test_review_sessions tests.test_review_voice` 共 15 项通过；包含范围隔离、迟到结果、重开服务防恢复、非法 ID 和清理回执。
- 原生窗口实看通用、复习与提醒、数据管理；隔离小样实看浅深色。清空确认显示实际 2 个会话、8 张卡，未输入时禁用；Escape 正常取消。没有对日常资料执行删除测试。
- App 重启后专属库完整性正常，8 张知识卡、3 条作答仍在，今天显示 8 个到期知识点。

## 本机恢复记录

实施前发现运行 App 知识库显示空，原默认路径包含其他 schema，未修改该文件。Rex 明确同意从 `before-knowledge-blocks-20260925-192111/default.store` 恢复到 Application Support/Review Today/Data/ReviewToday.store。恢复核对为 8 张知识、2 个会话、2 条消息、3 轮复习、3 条作答。未保证恢复 19:21 之后的数据。旧 App 另存 `before-settings-20260925-200417`；备份留在本机，不提交。

备份中已有 33 条待同步会话删除标记，因此设置可显示待后台清理提示；不是本次对恢复资料执行了清空。本次新清理队列初始为空。

## 截图与复现

- [数据管理](data.png)
- [复习与提醒](review.png)
- [清空确认，仅查看并取消](confirmation.png)
- `tests/mac/run-settings-preview.sh` 可生成独立内存设置小样，启动设置 preview 环境，禁止发送模型/服务请求；重新启动恢复合成内容。

## 未验证

未进行真实供应商调用、正式数据删除或供应商留存清理。未完成 VoiceOver 实机朗读、全键盘遍历、减少动态与最小窗口的完整验收，也未制作动效录像。浅深色基本可读性与默认窗口排版已查看，不替代最终体验确认。
