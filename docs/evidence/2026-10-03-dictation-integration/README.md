# B 版听写接入

Rex 选定「黑白声波＋局部银白柔光」后，将独立小样方向接回 Agent 日常输入区。原型历史仍留在相邻目录；本目录只记录正式组件接入。

## 已实现

- 录音在输入框原位显示深色面板：左侧取消、中间真实音量驱动的声波／局部柔光及计时、右侧「完成听写」。普通工具与发送退出；完成只启动转写／整理，不发送。
- 权限、转写、整理、保存分别显示文字，不播放假收音。取消保留原稿；失败恢复可编辑原稿和既有重试／重录／丢弃入口。
- 原生编辑器实例始终保留，隐藏时禁止编辑、点击和无障碍聚焦；隐藏期间仍能回填并保存。成功恢复编辑、一次撤销和独立发送。空草稿的发送按钮采用禁用视觉。
- 减少动态采用静态声波和声音强弱文字；窗口隐藏、失活、最小化暂停装饰时间线。最长仍为 5 分钟，最后一分钟显示剩余时间。
- 不改变录音、云服务、音频存储、会话或附件规则。

## 定向验证

最终五组合同在 `CFFIXED_USER_HOME` 临时目录运行，无真实录音或供应商请求：

1. `DictationSurfaceContractTests`：实际 NSHostingView + LearningEditor 实例保持、隐藏布局／命中／焦点、取消保留文本与选区、隐藏期间回填保存、恢复不重复、一次原生撤销、不自动发送。
2. `DictationContractTests`：权限拒绝、取消、缓存保留、整理回退、保存失败重试、会话切换迟到结果、回填与撤销。
3. `LearningInputContractTests`：原生输入、输入法、快捷填入、草稿、首发原子性等既有输入规则。
4. `UIPolishContractTests`：初始／显式／锁定／迟到焦点和选择保护等既有契约。
5. `SessionDeletionContractTests`：既有会话隔离、清理与恢复保护。

结果摘要见 [contract-results.txt](contract-results.txt)。复跑：

```sh
qa_home=$(mktemp -d /tmp/review-today-dictation-contract-home.XXXXXX)
CFFIXED_USER_HOME="$qa_home" bash tests/mac/run-dictation-contracts.sh
```

正常 Debug 在独立 DerivedData 构建，保留 `Rex.Review-Today`、Apple Development 和原 Team；严格／深层签名通过。完整构建退出 0，但 Xcode 对两份既有文件输出调度诊断，随后同目录增量复核退出 0、无 error；两轮日志保留在本机。签名、二进制摘要与诊断边界见 [build-verification.json](build-verification.json)。本轮没有修改既有工程文件的格式差异。

## 原生验收与本机更新

正式组件的独立原生 App 已实看：1000pt 浅色输入区录音／处理／回填及一次 ⌘Z；400pt 深色输入区与减少动态、静音文字、Esc 取消保留原稿、转写失败恢复原稿及重试成功。两次成功回填后真实编辑器仍是同一个实例；原稿可继续编辑，没有自动发送。声音、服务延迟与保存回调均由隔离夹具提供，未启用真实麦克风。失败恢复栏由验收夹具模拟既有动作，日常失败栏的业务仍由控制器合同覆盖。

- [录音到草稿原速录像](listening-to-draft.mp4)：21.18 秒，真实帧时间。
- [减少动态、取消、失败重试原速录像](reduced-cancel-retry.mp4)：45.96 秒。
- [浅色正式面板](listening-light.png)、[400pt 深色静音／减少动态](silent-reduced-dark-narrow.png)。

两段视频均无音轨，帧时间严格递增、解码无错误；[video-verification.json](video-verification.json) 记录尺寸、帧数与检查方法。视频有变化不等于真实麦克风验证，也不以单帧代替动作验收。

隔离验收入口：先跑上述合同取得输出的 shared-contract 目录，再运行 `bash tests/mac/run-dictation-integration.sh <shared-contract-directory>`，打开 `output/dictation-integration/DictationIntegration.app`。它直接链接正式组件；原生启动器与 Swift 路径断言将缓存限制在专用 isolated-home 中。最终包已重建，依赖完整打包，重新启动检查通过。

日常 App 已正常退出、备份并替换为本次原签名构建，然后打开原 RAG 会话。空草稿、会话及学习数据入口保持；空发送按钮已显示禁用状态。学习业务表记录数量未变，仅 SwiftData 历史事务记录增长；服务 health 正常、三个角色 ready、Jev off。旧 App、完整 Data、Dictation 及两份服务数据库备份在 Git 忽略的 `output/dictation-b-local-backup-20261003-205356`。本机路径、二进制摘要和核对结果见 [local-update.json](local-update.json)。

体验路径：日常 App → Agent → 输入框麦克风 → 说话 →「完成听写」→ 编辑草稿 → 手动发送。取消应保留录前草稿；处理期间不出现发送按钮。

## 保留边界

受控信号和服务验证不等于真实采音、识别质量或网络延迟验收。本轮不更改供应商配置或发起真实云端听写。最终视觉、手感以及真实麦克风联动仍由 Rex 在日常 App 体验；VoiceOver 完整朗读流程未运行。没有合并 PR、生产部署或关闭产品验收。
