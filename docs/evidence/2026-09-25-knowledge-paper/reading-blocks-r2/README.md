# 知识卡分区阅读修订

Rex 确认讲解、要点、误区及来源使用独立浅底区块，取消误区／来源折叠。首轮更新隔离原型轻纸面分支；随后按 Rex 授权接入日常 App，安装记录见下方。旧版对照、业务数据和评分不变。

- 阅读区最大 660pt；区块内边距 22pt、间距 24pt、圆角 18pt；无描边与嵌套背景框。
- 正文 15pt、附加行距 7pt；讲解段落间隔 24pt，判断条目间距 20pt。保留原文段落、编号、列表及短标签结构，不重写讲解内容。
- 常见误区独立常驻，使用中性提醒标记，不标记用户答错。来源依据完整常驻，保留链接、原会话删除和无证据提示。

原生检查：同一向量／RAG 讲解的三段正文、判断要点和常驻误区／来源；RAG 优势的编号与标签条目；默认浅色及最小深色窗口、滚动及固定操作区、关闭后重新打开。原型构建与 App Debug 构建通过。布局改动未新增镜像测试；未重跑模型、排期或 Harness。完整辅助技术与真人触控板体验仍未验证，Rex 视觉接受开放。

截图：[讲解](explanation-light.png)、[要点与误区](criteria-misconceptions.png)、[来源](source-light.png)、[标签条目](labeled-criteria.png)、[深色最小窗口](minimum-dark.png)。[原生滚动录像](reading-native.mp4) 为 35.95 秒原速、无音频，仅录本原型窗口。

打开方式沿用上层 README，底部选择「轻纸面」即本版，旧证据仅记录首轮，不作为本轮分区视觉依据。

## 日常 App 实装（2026-09-25）

- 主窗口启用同一分区阅读，未启用 `knowledgePrototype`；真实复习参与、管理和试题入口沿用既有流程。
- 更新现有日常开发应用：`~/Library/Developer/Xcode/DerivedData/Review_Today-gkeqhkrlvxqhunchqjqzselqoapv/Build/Products/Debug/Review_Today.app`，保留 `Rex.Review-Today` 身份与 Apple Development 签名。构建日志 `/tmp/knowledge-install-build.log`；构建及严格签名检查通过。
- 备份应用与一致性 SQLite：`~/Library/Application Support/Review Today/Backups/before-knowledge-blocks-20260925-192111/`。安装后完整性为 ok；22 张持久化表比较仅会话 `Z_OPT` 与主键 `Z_MAX` 计数改变，其余字段保持。8 条知识、2 个会话、2 条消息、3 条复习会话与3 条作答数量不变。
- 原生从日常知识库打开现有向量／RAG 卡片，检查分区、滚动、常驻误区及来源、固定底部操作；没有原型工具条。真实个人内容截图不提交到仓库。
- 本次没有提交答案、修改参与开关或触发模型；评分、排期、完整辅助技术未重跑。深色与窄窗检查来自前述隔离原型，视觉体验待 Rex 确认。
