# Agent 标题区 Mr. B · 三种点击反应验证

## 范围

Rex 确认吉祥物位于产品名与 slogan 左侧。现有四向眼神跟随和压扁回弹基础上，补齐左右晃身、轻跳落地，总计三种点击反应，随机且不连续重复。Rex 已确认当前点击交互 OK；随后按反馈改为文字块对齐内容区中轴，吉祥物作为左侧装饰，修订排版待视觉验收。

复用现有 Spine 4.2.120 骨架、加权网格、渲染器及浅深材质。`header-player.mjs` 是宿主输入驱动的骨骼姿态控制，不是新增可在 Spine 编辑器中打开的固定时间轴。角色画布为 92×74 pt，内部按钮为 76×62 pt；眼神 60 Hz 上限合并传递，不刷新学习页面状态；点击反应约 720 ms，播放中连点不排队。

## 验证环境与证据

- 文字居中修订：签名 Debug 构建通过；日常 Agent 页面和隔离 520 pt 窄窗口目视确认文字与内容中轴对齐。四张静态图与原速录像已更新为当前文字居中、三种点击版本。
- 历史：居中修订的两次复测曾分别在最小化、向下跟随失败，保留 [当时记录](text-centering-checks.txt)。本次发现测试窗口缺少 `.miniaturizable`，补上后等待实际最小化完成再断言；本次四向和最小化均通过，先前向下跟随的单次失败未复现，原因未认定。
- macOS 27.0 (26A428)，Xcode 27.0 (27A266a)，Apple Silicon。
- 隔离 App 使用实际 `LearningWorkspace`、实际输入组件与离线 Spine 渲染器，SwiftData 仅内存，不发送模型请求。
- [浅色](light.png)、[深色](dark.png)、[减少动态](reduced.png)、[520 pt 窄窗口](narrow.png)。
- [原速原生录屏](native-interaction.mp4)：ScreenCaptureKit 仅录制测试进程自己的窗口，无声音；鼠标／点击／键盘事件由原生测试程序投递，视频时钟跟随实际运行时间，不是离线合成动画。录屏中的系统指针不代表每个测试事件的坐标。
- 日常签名 App 通过 CUA 查看 Agent 起始页及实际拖动指针；未向日常输入框写测试内容或发送消息。

## 三种点击版本通过的检查

- 17 项 Node 检查：三种可选择、有效点击不连重、拒绝的连点不改变反应、三种姿态可区分且精确回正、全部动作与视线组合的网格和眼白边界，以及既有待机／材质检查。
- 原生实际按钮依次触发 wobble、hop、squash；不连重、连点不排队、四向跟随、中文 marked text 与焦点保持、输入回正、减少动态、实际最小化停播、离页清理和返回不补播全部通过。详见 [本次原生日志](three-reactions-native-checks.txt)。
- Debug 签名构建通过；日常应用已重启并通过 CUA 查看 Agent 页面。12 秒原速录像包含三种实际点击和上述状态变化。

## 首轮通过的检查（历史）

- 15 项 Node 检查：新增跟随／收势／连点／网格／眼白边界，以及原有待机与材质回归。
- `InteractionFocusTests`、`LearningInputContractTests`、`NavigationRenderContractTests`：现有焦点、中文预输入、草稿及导航契约回归通过。
- 原生标题测试：四向跟随；真实按钮触发点击；连点不排队；中文 marked text 与输入焦点保持；打字后眼神回正；减少动态静止；最小化停止；离页拆除跟随区域；重新进入不补播。
- Debug 签名构建与签名完整性检查通过。

## 修正与边界

原生测试发现：仅添加区域追踪不足以稳定收到窗口鼠标移动事件，现显式启用并在移除时恢复原值；输入组件原有「外部点击释放焦点」规则需对当前可见吉祥物的左键点击增加狭窄例外。其余外部点击规则保持。

普通 `.focusable()` 会在鼠标点击时取得编辑式焦点，因此标题按钮使用 `.focusable(interactions: .activate)`。按 [Apple 的 activation 说明](https://developer.apple.com/documentation/swiftui/focusinteractions/activate)，macOS 键盘激活遵循系统的所有控件键盘导航设置。本轮检查了按钮可访问名称，未更改用户系统设置；开启所有控件导航后的 Tab/Space 全路径及 VoiceOver 未完成实机验证。

初轮测试曾把向上指针发到测试控制栏附近，已将测试坐标限定在内容区；跟随区域绑定实际页面框体。开发中失败的测试不作为完成证据，最终日志以本目录文本文件为准。

## 复跑与 Rex 验收

```sh
node --test tools/mascot-motion/test/header.test.mjs tools/mascot-motion/test/idle.test.mjs tools/mascot-motion/test/material.test.mjs
bash tests/mac/run-contracts.sh InteractionFocusTests LearningInputContractTests NavigationRenderContractTests
bash tests/mac/run-agent-title-native.sh --interactive
```

打开日常 App → Agent 起始页：左右上下移动指针，点击 Mr. B，再连续点击；输入途中再点一下，确认仍能继续打字。重点看角色与两行文字的比例、眼神灵敏度和回弹手感。每隔约一秒点击一次，检查三种动作及不连续重复；新增两种反应的幅度和节奏待 Rex 最终视觉验收。
