# KT-01 原生邀请隔离验证 · 2026-10-04

正式 `LearningWorkspace`、`TopicCapturePanel`、待处理与知识库组件；模拟后端 offer／答题结果，使用真实隔离 SwiftData 保存和保存回执。无模型调用，不连接日常服务、不读取日常数据库。交互验收沿用 Apple UI Review 的原生运行标准。

## 当前修订

首轮已验证完整操作，但 Rex 反馈信息重复。最终呈现收紧为「知识名称＋一句保存内容＋次要复习选项＋新增知识／稍后」。仅改变 `verified_check` 邀请；旧收尾继续保持原行为。范围与知识名相同的旧快照不重复显示，合同已覆盖此兼容输入。

最终版已在正式原生窗口复核：范围更新后 AX 文本包含最新补充，中文草稿与编辑焦点保持，更新前后滚动值相同。点击提交 version=2、reviewRequested=false，实际本机提交后才显示真实结果和查看入口。760×680 深色／减少动态布局可读、关键动作完整可见；最终保存点击在标准窗口验证。

最终证据：[原速录像](native-interaction-final.mp4)、[浅色邀请](invitation-compact-light.png)、[范围更新与草稿](scope-refresh-compact-and-draft.png)、[真实提交后的状态](saved-compact.png)、[深色窄窗减少动态](invitation-compact-dark-narrow-reduced.png)、[最终浅色](invitation-compact-final.png)、[观察结果与 AX 摘录](validation-final.json)、[操作日志](native-interaction-final.log)。

`native-interaction-v1.mp4` 及下方首轮截图为精简前证据，不能当作最终呈现。首轮范围更新的真实画面正确，但 AX 组合文本保留了旧范围；最终版通过范围文字局部 identity 刷新修复，并实测确认。未将 AX 检查称为系统 VoiceOver 完整验收。

## 首轮已走查

- 邀请位于有效作答的反馈下，默认未选「已学过，加入复习」，出现邀请不生成或保存卡片。
- 同一 offer 更新范围并保留锚点；未发送中文草稿与编辑器焦点保持。更新后实际点击提交 version=2、reviewRequested=false。
- 点击后由真实隔离本机提交写入两张合成卡片，再出现「查看知识」；点击确实打开知识库，卡片未参与复习。卡片正文来自保存夹具，不是本轮模型生成，不能证明知识质量。
- 模拟本机写入失败仅显示失败／重试，未发成功回执；关闭模拟失败后重试成功。
- 稍后进入待处理，可继续发送追问；待处理返回同一邀请可保存。新邀请没有 next_request，没有自动续讲。
- 760×680 深色与减少动态可阅读，关键动作完整可见；检查未通过时无邀请。旧收尾「跳过，继续」仍显式续讲一次。

原速录像：[首轮完整交互](native-interaction-v1.mp4)，140.87 秒，1040×820；[窗口与封装检查](recording-validation.json)、[实际操作日志](native-interaction-v1.log)。

截图：[浅色](invitation-light.png)、[范围更新及草稿](scope-refresh-and-draft.png)、[真实保存后打开](saved-knowledge-view.png)、[写入失败](local-save-failed.png)、[稍后待处理](deferred-inbox.png)、[深色窄窗减少动态](invitation-dark-narrow-reduced.png)、[未通过无邀请](unpassed-no-invitation.png)、[旧收尾显式续讲](legacy-explicit-continuation.png)。

## 自动检查与未覆盖项

原生合同验证旧／新 offer 解码、同 id／锚点范围刷新、当前显示版本点击绑定、旧请求保留原版本、迟到 revision／归档隔离、复制 offer 不写知识。知识入库合同验证磁盘回滚、实际提交后的回执、重复／ACK 重试、复习默认关闭及显式选择。

最终两组合同全部通过：[完整日志](contracts-final.log)。当前模块同时包含紧凑呈现、AX 刷新和重复范围兼容处理；[QA 编译](qa-build-final.log)通过。编译告警为既有音频 API 弃用、测试 sourceLocation／rpath 及 QA Sendable 警告，未忽略编译错误。

当前未覆盖系统 VoiceOver 完整朗读／键盘导航、真实后端到原生的端到端答题邀请、多轮真实教学质量、Rex 最终视觉／手感验收。后端语义与真实受控样例由本轮其他证据说明，不混入本机合成 QA 结论。截图顶部隔离标识、预览状态及夹具用户消息的连接提示属于 QA 辅助状态，不是新增知识邀请的产品文案。

隔离工具：`bash tests/mac/run-topic-capture-native.sh`，可用 `REVIEW_TODAY_TOPIC_QA_OUTPUT` 指定证据目录。每次新建 `/tmp/review-today-topic-native-UUID`，独立端口 18764。背景启动的主窗口／截图旧崩溃已在 QA 工具修复，不是生产保存路径变更。

日常 App 后续已由主线程完成签名构建、备份更新与数据核对，见[本批安装记录](../local-install.json)；不计入上述隔离原生语义链路。
