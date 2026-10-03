# 听写反馈原生对照

2026-10-03；独立原型完成，等待 Rex 选择表现。没有接入日常 App，也不代表真实听写链路验收。

## 打开与体验

项目根目录执行 `bash tests/mac/run-dictation-prototype.sh`，然后打开 `output/dictation-prototype/DictationPrototype.app`（本次交付已构建并打开）。独立 Bundle ID 为 `Rex.Review-Today.DictationPrototype`，最低目标 macOS 26.5。

1. 点击 A 或 B 的麦克风。两版同时使用同一模拟信号，比较纯黑白声波与局部银白柔光。
2. 切换自然说话、轻声、静音。A 主要依靠柱条起伏；B 的光带亮度与扩散随同一信号变化。两版共享草稿，便于比较相同状态。
3. 点「完成听写」：转成文字 → 整理 → 回填可编辑草稿，不自动发送。编辑后点击箭头仅模拟发送。
4. 已有草稿时重新开始，再点左侧叉或 Esc；原草稿保留。勾选「下次转写失败」后完成，可以重试或丢弃。
5. 切换深色／减少动态；⌘9 切到 650 pt 窄窗口，⌘0 恢复 1000 pt。⌘D 开始，⌘Return 完成。

系统减少动态或小样内减少动态任一开启时，取消声波起伏、光带变化和处理转圈，保留静态形态与状态／声音强弱文字。时间和输入状态也暴露为可访问性值，未进行 VoiceOver 全流程验收。

## 交付与边界

源码：`tools/dictation-prototype/`；构建脚本：`tests/mac/run-dictation-prototype.sh`；状态回归：`tests/mac/DictationPrototypeTests.swift`。

仅采用 Typeless 官方演示的集中操作布局和本机 Codex 的输入区替换思路；参考不是代码来源。界面尺寸、光感、节奏尚待视觉验收。沿用 Runway 中性纸面值，独立绘制本轮声波；不修改共享吉祥物、连续语音复习、听写服务或 Xcode 主工程。

没有麦克风、网络、模型、数据库或正式消息写入。声音、转写和等待时间均为演示，不代表真实识别效果与延迟。完成时追加固定样例文字，全程静音不添加文字。所有草稿与模拟发送内容仅在内存中存在。

## 验证证据

环境：Apple Silicon、macOS 27.0.1（26A434）、Swift 6.4；真实 macOS 窗口，内容尺寸 1000×790／650×760，中文。

- 独立应用编译、ad-hoc 签名校验、`git diff --check` 通过。
- Swift 6 状态回归通过：取消保留草稿、取消后迟到结果无效、重复完成只追加一次、完成不发送、显式发送、失败重试／丢弃、静音不造文字、自然停顿、300 秒自动结束、重置抑制迟到结果。300 秒边界采用受控时钟前移，没有真实等待五分钟。
- CUA 实际操作：开始／完成、草稿回填与中文粘贴编辑、再次听写后取消保留原稿、显式模拟发送、失败重试、全程静音无新增文字。完成异步回填后焦点回到发起方案的文本区。
- 浅色默认窗口、深色窄窗口、减少动态与失败状态实际查看。修复动态更新时对照标题偶发消失、声音选择标签换行以及浅色模式处理指示器对比度不足。
- 精选无音轨录像由 ScreenCaptureKit 捕获当前进程自身窗口，保留实际时间戳；目标 30 fps，实际为可变帧率。没有桌面、其他应用或麦克风录音。原始编译与中间迭代留在忽略的 `output/dictation-prototype/`。

| 文件 | 内容 |
| --- | --- |
| [listening-light.png](listening-light.png) | 同源声波与柔光、左右动作 |
| [editable-draft.png](editable-draft.png) | 回填后的可编辑草稿及独立发送 |
| [processing-light.png](processing-light.png) | 停录后的明确处理状态与高对比指示器 |
| [reduced-dark-narrow.png](reduced-dark-narrow.png) | 深色、窄窗口、减少动态 |
| [failed-dark-narrow.png](failed-dark-narrow.png) | 失败提示、保留／重试入口 |
| [listening-to-draft.mp4](listening-to-draft.mp4) | 正常速度收音、停顿、完成和回填 |
| [reduced-failure-retry.mp4](reduced-failure-retry.mp4) | 减少动态、失败、重试和回填 |

视频参数与解码结果见 `video-metrics.json`、`decode-check.json`。解码校验使用 `-fps_mode passthrough -enc_time_base demux`，保持原录屏时间基；默认 null muxer 时间基会把相近帧舍入成相同 DTS，不能将该舍入警告误判为源文件损坏。

未验证：真实音频输入与转写、系统权限／网络／服务失败、系统设置面板切换减少动态、VoiceOver／Full Keyboard Access 完整流程、其他平台与语言。此次只有小样内减少动态开关被实际操作；系统设置接线存在，但没有改变用户系统偏好。最终视觉与使用体验由 Rex 看过原型后选择，正式接回另行授权。

状态回归复跑：

```sh
mkdir -p output/dictation-prototype/checks
xcrun swiftc -parse-as-library -swift-version 6 tools/dictation-prototype/DictationDemoState.swift tests/mac/DictationPrototypeTests.swift -o output/dictation-prototype/checks/state-tests
output/dictation-prototype/checks/state-tests
```
