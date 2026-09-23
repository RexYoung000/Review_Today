# 今天与复习界面接入 App

2026-09-23。Rex 授权先接回 App，再进行视觉和交互体验。此次将第六次原型样式迁入实际页面，使用真实 SwiftData、ReviewController 和现有语音服务；模拟考仍限「知识测验／模拟面试」选择页。

## 体验入口

- 今天：复习主区域、玻璃学习／模拟考入口、最近学习详情、最近复习和学习足迹。
- 有到期知识：今天 → 准备复习 → 语音或文字开始。暂停后显示继续本轮。
- 已结束一轮：今天右上角「最近小结」，或最近复习的「查看小结」。历史不会替换暂停清单。
- 当前 App 库有 3 个会话、30 条消息、0 个知识；因此显示真实空状态。知识保存并加入复习，到期后才出现可开始的清单；没有导入合成知识或成绩。

已更新并启动原先正在使用的 `Review Today · Jev 测试`，身份 `Rex.Review-Today.Jev.NativeQA`。继续使用原数据库、服务端口和凭证来源。可执行文件位于 `/tmp/review-today-jev-native-build/Build/Products/Debug/Review_Today.app`。旧应用和数据库已备份，路径、计数及校验见 [安装记录](installed-app.json)。未修改另一实例的日常数据库。

## 工程验证

通过 5 组定向契约：`ReviewUIIntegrationContracts`、`ReviewControllerContractTests`、`ReviewFlowContractTests`、`NavigationDataContractTests`、`AppRuntimeContractTests`。控制器最后修改后复跑前两组；后续原生显示修复通过最终 Debug 构建与实际窗口操作检查。[初轮日志](logs/contracts-initial.log)、[控制器复跑](logs/contracts-controller-final.log)、[最终安装构建](logs/debug-installed-build.log)。

原生 QA 使用实际 ContentView、ReviewView、ReviewController、内存 SwiftData 和合成内容，仅把模型判断及语音连接替换为受控事件。没有请求模型、采集麦克风或写用户数据库。已实际操作：

- 今天入口、最近学习详情及对应会话继续、模拟考双选项、准备页目标切换。
- 连接失败留在当前题并展开文字；遗忘 → 提示 → 答对仍保留首次未独立回忆；自动转题。
- 纯跳过、暂停／关闭／恢复原清单、从小结修正转写并返回同一小结。
- 第一轮 3 个完成、其中 1 个需帮助、1 个跳过、0 个未完成；第二轮只包含剩余到期知识，完成后显示 1 个完成、0 个跳过。部分小结与完整小结均有实际 Mr. B 呈现。
- 最近小结重开；历史不替换暂停清单另由契约验证。浅深色、默认／最小窗口、键盘和减少动态分支。

最终 QA 构建为 `/tmp/review-today-integration-qa.jqmOXA/TodayReviewQA.app`；返回今天复测保持 `main-AppWindow-1`，不再新建主窗口。安装版原生确认今天的历史、热力图、模拟考选择、复习空态和角色；服务 `/healthz` 返回正常，签名严格校验通过，安装前后会话／消息计数及消息内容摘要一致。

## 检查中发现并修复

1. 原生可选文字偶尔沿用上一题或旧反馈。为题目、反馈和最新回答绑定显示内容身份，独立观察反馈；复测已实际显示新题和帮助文案。
2. 返回今天使用 WindowGroup 打开操作导致重复开窗。改为复用已有主窗口，缺失时才创建。
3. 跳过后最近回答可能来自更早的题，改为标明所属知识点，避免错误标成上一题。
4. 预览题恢复限定同一知识与题目；与正式复习清单隔离。

初轮截图保留在 [first-pass](first-pass)，其中旧题／反馈显示与 QA 深色配置尚未修正，不能作为最终通过证据。中途一轮 QA 编译因同时修改源文件失败，后续停止编辑后重建成功；最终构建日志见 [native-qa-final-build.log](logs/native-qa-final-build.log)。

## 原生截图

这些截图来自实际控制器的合成数据 QA，不代表真实模型判断质量。截屏时的原速动效姿态不等同于完整动画录像。

| 场景 | 截图 |
| --- | --- |
| 修复后的遗忘反馈／深色 | [帮助状态](1790171279.41053-help-dark.png) |
| 转题后的新题和保存反馈 | [第二题](1790171434.8149981-asking-dark.png) |
| 部分完成与 Spine 陪伴 | [部分小结](1790171465.5707111-summary-light.png) |
| 历史小结／最小窗口／减少动态 | [历史小结](1790171554.777717-summary-light.png) |
| 下一轮完整完成与收尾角色 | [完整小结](1790171583.227186-summary-light.png) |

## 复跑与边界

从仓库运行：

```sh
python3 tests/mac/run-contracts.py ReviewUIIntegrationContracts ReviewControllerContractTests ReviewFlowContractTests NavigationDataContractTests AppRuntimeContractTests
bash tests/mac/run-today-review-integration.sh
```

第二条只构建独立 QA，输出 `.app` 路径，打开后可连续操作；合成判断不等于语义评测。所有检查详情与最终源文件摘要见 [checks.json](checks.json)。

本轮没有验证真人麦克风连续对话、扬声器回声、模型评分准确性、自由鼠标悬停手感／帧时间、系统减少透明度、完整 VoiceOver 或 Release 构建。玻璃实现复用已有原型循环光效，既有受控录像保留在 [第六次修订](../2026-09-23-today-review-prototype/pages-and-glass-r6/README.md)，不把旧录像说成此次实际鼠标悬停验证。最终视觉、光效力度及真人语音由 Rex 体验后继续校准；没有关闭 M1 或 Harness 总体验收。
