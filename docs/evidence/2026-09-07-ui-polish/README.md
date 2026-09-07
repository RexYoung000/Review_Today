# 页面布局、焦点与角色统一验证

2026-09-07；macOS 26.7（25G220）。本轮是原生 UI 修改，不改后台、识别/文字模型、数据库原始标题或统计卡操作语义。最终体验验收与发布保持开放。

## 实现范围

- 今天页固定标题/主按钮，统计、最近学习与热力图独立滚动；保持统一 24 pt 横向边距和 960 pt 最大正文宽度。热力图增加月份、紧凑全零状态；最小窗口且侧栏展开时允许图表内部横向滚动，避免页面越界。
- Agent 起始页名称、slogan 居中；输入正文左对齐。初次进入/普通切换不自动获焦，明确点击、Tab、快捷填入和听写保存后的回焦保留；新操作优先于异步回焦。输入锁定和窗口失活不显示活动编辑状态。
- 统一各控件自身轮廓；会话行整行背景、悬停、按下和焦点不再分别套用不同矩形。选中填充与键盘焦点独立。
- 知识库显示当前筛选「总数 N」，窄窗主题另排；失效主题恢复全部。卡片使用进入符号、最多两行和完整悬停标题。检查的旧卡标题字段为空，旧展示算法又截断学习目标；现改用已有完整目标展示，不写回数据。另保护已知半截词形的标题回退，正常短标题不扩写。
- 会话列表始终展开；无进行中会话且未搜索显示常规字重气泡和新角色。点击只进入 Agent 并聚焦草稿。空态复用 150×170 阅读动作，等待 1 秒播放一次 8 秒后静止；其他待机入口仍使用原默认动作。
- 知识库空态与复习页换成新角色；判断时思考，保存时普通进度，其余静止。

## 自动验证

| 检查 | 结果与范围 |
| --- | --- |
| UIPolishContractTests | 通过：初始/显式/外部点击/锁定/过期回焦、回填后解锁回焦、草稿与选区保护、6 类完整标题与无数据写入、主题去重展示、胶囊轮廓一致、书本原生配置兼容 |
| LearningInputContractTests | 通过：12 场景、快捷卡刷新、预填与 IME marked text/撤销、原生输入、首发失败重试、独立草稿、侧栏偏好等 |
| DictationContractTests | 通过：权限拒绝、取消、保留与清理、回退提示、旧缓存、计时、重复回调、追加及一次撤销；未发起真实识别请求 |
| InteractionFocusTests | 通过：单控件焦点不广播到其他行，选中与焦点独立，浅/深/禁用渲染 |
| SessionDeletionContractTests | 本轮前段通过：会话删除与草稿/录音清理回归；后续未修改删除实现 |
| JavaScript 动效回归 | 30 项通过；共享资源与源一致，未新增动作或修改语音/环绕轨道 |
| 原生 WK 动效 | 通过：主题、语音/思考、单次阅读、隐藏暂停及恢复不追赶、减少动态、装饰表面不抢输入 |
| Debug / Release | 构建通过；Debug Apple Development 签名及 strict/deep 校验通过；Release 未签名编译，不作为发行包 |

复跑命令（仓库根目录）：

```sh
bash tests/mac/run-dictation-contracts.sh UIPolishContractTests LearningInputContractTests DictationContractTests InteractionFocusTests
node --test tools/mascot-motion/test/*.test.mjs
bash tests/mac/run-mascot-native.sh --record-ui-book
```

最后一处修改仅移除覆盖全文提示的通用 accessibilityHint；在该修改后重新通过 Debug/Release，并在日常构建核对完整可访问标题。契约验证对应同一行为实现。

## 原生界面实际检查

使用独立 bundle `Rex.Review-Today.UIPolishQA` 与内存 fixture，样例带「不可发送」标识，不向日常 Agent 发送测试消息。

- 默认宽窗与 760 pt 最小窗口、侧栏展开/收起，浅深主题：今天标题及主按钮固定，滚动区域只移动正文，顶部与卡片边距一致。
- 首轮发现最小窗口 + 展开侧栏时热力图挤出右边界，修复图表横向兜底后复查右侧 24 pt 边距恢复。
- 宽窗筛选/数量居中对齐；窄窗主题第二排滚动。当前筛选数量 5 → RAG 3 → 暂停 1 → 删除 0 一致；切换到不含旧主题的生命周期后恢复「全部」。
- 中文完整目标、长主题与中英术语标题正常；进入符号保留详情行为。首轮出现主题剥离后残留「的」，已修复并回归。
- 普通进入 Agent 无光标；点击编辑器出现活动焦点，外部空白点击退出；快捷填入后 Cmd-Z 恢复原稿。Tab 离开到「添加材料」，Shift-Tab 返回编辑器。
- 新建气泡和知识库「开始学习」能进入 Agent 并聚焦草稿，不创建/发送消息。会话搜索无结果和归档空态各自正确，不显示新建气泡。
- 知识库零项显示「总数 0」、准确引导和新静止角色；复习窗口等待作答显示新静止角色，未提交真实评分请求。
- 系统「减弱动态效果」临时 off → on 时，重新进入会话空态保持静止并保留提示文字；检查后恢复 off。原生隐藏/恢复不追赶另由 WK 测试覆盖。

## 录像与未完成项

[native-sidebar-book.mp4](native-sidebar-book.mp4) 是隔离原生 WKWebView 在实际时钟下采样的约 11 秒录像：150×170 取景，以 300×340 编码；浅色单次阅读后静止，最后深色减少动态。它不是离线骨架渲染，也不是整个 App 的屏幕录像。已检查拿出、展开、翻阅、收回和静止的画面。

以下未标为通过：

- 整窗顶部滚动和焦点切换录像：系统 Screenshot 工具两次启动超时，未取得录像；上述原生动作通过实际窗口和 AX/截图检查，不能替代所缺录像。
- 完整 VoiceOver 流程：尝试启用后未稳定进入导航，后续系统开关为 off；只确认控件标签、选中状态和输入焦点语义，不宣称读屏体验通过。
- 真实中文输入法候选操作：自动化 Unicode 输入未稳定得到目标句子；marked text 与撤销由原生契约覆盖，不能替代真实候选窗验证。
- 本轮没有重新测试真实麦克风识别质量、评分后所有复习阶段或所有页面减少动态组合。此前听写麦克风质量与完整体验缺口仍保留，不因 UI 构建成功关闭。

## 验收入口

日常开发 App：`output/default-brand-build/Build/Products/Debug/Review_Today.app`，保持正常数据目录。已更新并实际打开，原有 8 张知识卡、4 个学习中任务保留，未发送测试消息。

建议依次查看：今天页滚动 → Agent 点击/外部点击/Tab → 知识库筛选与长标题 → 会话空态阅读。空态不要通过删除日常数据构造；可用隔离样例：

```sh
xcodebuild -project Review_Today.xcodeproj -scheme Review_Today -configuration Debug -derivedDataPath /tmp/review-ui-polish-qa PRODUCT_NAME=UIPolishQA PRODUCT_MODULE_NAME=Review_Today PRODUCT_BUNDLE_IDENTIFIER=Rex.Review-Today.UIPolishQA build
REVIEW_TODAY_M1_UI_FIXTURE=today REVIEW_TODAY_UI_POLISH_FIXTURE=empty /tmp/review-ui-polish-qa/Build/Products/Debug/UIPolishQA.app/Contents/MacOS/UIPolishQA
```

将 `empty` 改为 `populated` 可看长标题、有内容会话和复习入口。先退出上一隔离进程再切换数据集。小样不会写日常库。
