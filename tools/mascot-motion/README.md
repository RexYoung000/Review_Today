# Review Today 动画制作 MCP

2026-09-07。用于本次 V3 吉祥物的 Spine 4.2 形变小样；不是通用自动绑定产品。已有源码、可调用 MCP、可操作预览与可编辑 JSON，已将 recall 接入日常 App 的运行状态，语音四态提供原生组件和开发验证入口；听写/真实语音事件未接通，Spine 编辑器导入仍未验证。

## App 内接入

`node tools/mascot-motion/src/build-native.mjs`（仓库根目录）从已提交骨架、纹理与共享模块生成 `Review_Today/MascotMotion.html`；`--check` 检查资源是否与源一致。今天入口的两条图标 Spine 时间轴由 `node tools/mascot-motion/src/build-entry-icons.mjs` 重建，改动它们后先运行此命令，再生成 HTML。App 随包加载，不依赖 Node、8769、远程脚本或麦克风，页面通过 CSP 禁止网络请求。修改已确认动效后须重建该资源，再构建 App；MCP `.work` 草稿不会自动替换日常 App。

SwiftUI 的 `MascotMotion` 包装本地 WebKit/官方 Spine 渲染，避免重做另一套碰撞。`RunPhaseLine` 仅在已启动的 running / adjusting 时驱动 recall，完成/停止后短促收拢。四态组件参数为 surface、phase、level、reduced、rate；语音 level 当前用于明确标识的模拟验证，不是已接通的录音输入。非活动/遮挡/移除视图暂停，组件不接收鼠标或键盘焦点。

`bash tests/mac/run-mascot-native.sh` 编译隔离原生验证程序：检查本地资源载入、Run 状态映射、环绕/收拢、减少动态、隐藏暂停、四态调用及停稳。加 `--interactive` 可查看同一原生组件、实际 RunPhaseLine、浅深色和半速（每次演示最多 20 秒）。日常 Debug App 的「文件 → 新建 → 新已确认动效 · 原生验证窗口」或设置中的开发入口也可打开；旧 POC 仍保留。

## 运行

需要 Node.js 20+。仅视频导出需要 PATH 中的 ffmpeg。依赖锁在 `package-lock.json`；首次运行：

```sh
cd tools/mascot-motion
npm ci --ignore-scripts
npm run build
npm test
npm start
```

打开 <http://127.0.0.1:8769/>。服务只监听 127.0.0.1，网页写操作要求同源 JSON。无账户、密钥、上传、麦克风或模型请求。

`npm run build` 从身体纹理、网格轮廓及 `brand/refresh-2026-09/motion-rig/recipe.json` 重建基线，并复制本机依赖中的运行时到忽略提交的 `vendor/`。MCP/界面编辑写入 `.work/current.json` 和历史版本，保留已提交基线。导出使用独立目录，不覆盖历史导出。

## 让 AI 调用

`npm run mcp` 启动标准 MCP stdio 服务。MCP 客户端配置的 command 是本机 Node 可执行文件，args 是本目录 `src/mcp.mjs` 的绝对路径。stdout 只输出协议；当前未更改任何全局 Codex/Claude 配置。

无需重启宿主或改全局配置，也可通过适配器调用同一个真实 MCP 服务：

```sh
node src/call.mjs rig_inspect
node src/call.mjs weights_bind '{"softness":85}'
node src/call.mjs motion_author '{"bend":10,"wave":5,"gaze":0.85}'
node src/call.mjs preview_frame '{"time":1.25,"size":640}'
node src/call.mjs preview_clip
node src/call.mjs preview_frame '{"animation":"speaking","time":2.8}'
node src/call.mjs preview_clip '{"animation":"speaking"}'
node src/call.mjs motion_export '{"name":"recall-v1"}'
```

适配器通过 SDK 建立 stdio 连接、协商协议并调用工具；并非绕过 MCP 直接运行内部函数。图片响应保存到 `.work/renders/` 并返回路径，AI 可看图后再次修改；思考页每 2.5 秒检查版本，在可见状态加载新版本；语音页打开/刷新时读取当前版本。

| 工具 | 范围 |
| --- | --- |
| `rig_inspect` | 当前骨架、参数、权重/拓扑检查及官方运行时采样 |
| `weights_bind` | 调整 3 个身体区域的影响范围并重新计算归一化权重 |
| `motion_author` | 时长、身体幅度、眼神、局部弯曲、波动及采样密度 |
| `preview_frame` | 官方骨骼计算 + Canvas 渲染，直接返回 MCP PNG image 内容 |
| `preview_clip` | 使用相同数据生成本地 MP4，依赖 ffmpeg |
| `preview_status` | 预览地址、当前版本、服务是否可达 |
| `motion_export` | 新目录内导出 JSON、atlas、部件图片、参数及验证记录 |

数据通过官方 Spine 4.2.120 解析；形变使用 4.2 的 `animations.*.attachments.default.body.body.deform` 结构。每顶点 3 个权重，FFD 偏移按每个骨骼影响分别编码，不重复乘权重。局部骨骼变换与 FFD 同时生效。

输入参数限定范围；每次生成后遍历关键帧与中间采样，检查所有三角形有向面积、有限坐标与循环首尾。参数在数值范围内也可能组合出翻折，该次生成会被拒绝，不更新当前版本。跨 HTTP/MCP 进程写入通过 `.work/author.lock` 串行化，当前文件原子替换。异常退出遗留锁会让编辑报 busy；确认没有作者进程运行后可移除该工具临时目录中的空锁目录。读取与预览不依赖写锁。

## 验证与边界

- `npm test`：官方解析/加权形变实际生效、眼睛领先身体、权重与关键帧损坏检测、网格翻折拒绝；真实 stdio MCP 握手/工具清单/修改/绑定/图片返回/导出/失败后保留上一版；HTTP 同源/目录边界/错误请求检查，以及两个 MCP 进程同时修改时不丢失参数。11 项测试通过（含前后遮挡、投影裁剪及语音局部形变/零声量/快速切换回归）。
- 人工通过 Codex 浏览器检查：465 px 与 1280 px 布局、播放/暂停、时间轴、分离中收拢、网格/权重、浅深主题、减少动态效果、参数生成与 MCP 版本同步。
- 已通过 MCP 实际生成 PNG、5.6 秒 MP4 和独立导出目录。仓库预览 `evidence/` 保存最终样例；MP4 是离线运行时渲染，不是原生 App 或 UI 操作录屏。
- 当前身体网格 193 顶点、336 三角形，另有随体加权裁剪轮廓 48 顶点，14 根骨骼，135 个采样关键帧。24 fps 视频为 135 帧、实际 5.625 秒（动画标称时长 5.6 秒）。完整默认动画检查 271 个时间点，未发现翻折，首尾误差为 0。
- 首轮离线 Canvas 出现三角形抗锯齿接缝；用小幅三角形覆盖和外轮廓裁剪修正。骨骼与形变计算仍来自官方运行时；该局部光栅适配器不重新实现 Spine。
- 没有通用图片自动理解、自由手绘权重、任意拓扑编辑或任意动作生成。当前工具面向这套固定控制结构，AI 调参数，确定性程序算权重与关键帧。
- 身体纹理由 imagegen 去眼得到，但生成器未稳定提供 Alpha；因此保留 RGB 源，使用网格边界限定显示区域。不能把 `body.png` 单独当作透明生产层。轮廓与眼睛的位置经预览检查，未承诺逐像素还原原图或通过 Rex 静态造型验收。
- 未取得 Spine 编辑器 `.spine` 往返证据；未发现常见应用目录中的 Spine 安装。导出的 JSON 可由官方运行时读取，不代表已经在编辑器打开。完整编辑/发行还需满足 Spine 授权条件，见 `THIRD_PARTY.md`。
- 18 px 仍无法清楚表达眼神；工具小样不自动授权扩大原生占位或接入真实语音。

## 取舍与来源

调研中的 [spine-motion-mcp](https://github.com/nihatcagri44/spine-motion-mcp/tree/a02127e4054709536941af5f9d1c7214a8a69ab9) 缺网格/FFD，CLI 也未实测。本轮采用其「编写数据 → 预览 → 导出」接口思路，针对缺失能力独立实现小型 MCP，没有复制其代码或安装其整个服务。其他候选旧版/非商业/许可不明的实现没有纳入工程。

官方数据定义以已锁定的 npm `@esotericsoftware/spine-core` 4.2.120 源码为兼容性依据；不要把旧 3.8 示例的 `deform` 顶层路径直接用于 4.2。

### 环绕深度修订

2026-09-07：主体缩至 86%，主色保留。浅青绿球走倾斜扁椭圆，Spine 绘制顺序随近/远半圈切换。新增三层投影附件，表面投影由加权 clipping 限定，FFD 与身体轮廓同步。浏览器和离线渲染器均支持本小样的 clipping 与独立区域绘制；半透明阴影不使用重叠三角形绘制，避免中间产生斜线。区域绘制适配器仅支持本工具生成的整页、未裁切 atlas，不宣称通用 Spine 播放器。Editor 导入仍待实机验证。

### 语音点修订

新增 [语音预览](http://127.0.0.1:8769/voice.html)，共用 14 骨骼与纹理，无额外依赖。`listening` / `speaking` 各为 4 秒、97 关键帧的可编辑循环（默认 24 fps），每条检查 193 个时间点，循环端点误差为 0。`motion_author` 同时重建三条动画，原 recall 数据保持一致。

`preview_frame` 与 `preview_clip` 增加可选 `animation: recall | listening | speaking`，默认 recall 保持兼容；语音截图时间允许 0–8 秒，视频固定生成 8 秒、85% 模拟声量。语音渲染使用与浏览器相同的 `voice-scene.mjs`，包括声量包络、局部形变混合、波浪和投影；JSON 本身只包含骨骼/FFD 循环及附件，真实声量、状态与 Canvas 波浪仍由宿主驱动。已实际调用作者、语音 PNG、语音 MP4 和完整导出；没有改全局 MCP 配置或调用麦克风。

### 弹性接触试作

`preview_frame` / `preview_clip` 新增 `animation: thinking`。示例：`node src/call.mjs preview_clip '{"animation":"thinking"}'`。使用与语音页相同的 `wave-contact.mjs`，生成 8 秒「跳跃 → 4.8 秒请求停止 → 余波平息」视频。固定步长弹簧表面、接触位置和程序式骨骼/加权 FFD 共用一个状态；目前没有把这一段烘焙到 `motion_export` 的 JSON 中，导出的 recall/listening/speaking 时间轴保持原样。页面明确标注下载范围。

当前共 13 项测试通过，新增跳跃过程网格不翻折、裁剪同步、停止时位置连续、余波最终静止与重新起跳检查。新思考是本轮试作，聆听/回答仍为前版，原生/真实语音与编辑器导入未验证。

### 四态整合，无投影

语音预览现在统一使用程序式接触层：incoming 向内汇聚、outgoing 向外传出、思考跳跃和停止收势。宽画布 19 条，窄窗 15 条。`preview_frame` / `preview_clip` 新增 `animation: conversation`；视频为 14 秒四态连播，帧时间允许 0–14 秒。其余选项的时长范围不变。示例：`node src/call.mjs preview_clip '{"animation":"conversation"}'`。已通过实际 MCP 调用生成视频，当前 14 项测试通过；这一层仍未烘焙进 `motion_export`，旧版 JSON 中的语音循环不能代表当前交互预览。

### 受力形变强化

语音程序层新增聆听向内吸收、思考落地底部接触面与 120 ms 承重、模拟句首的一次低幅下落。回答每 3.6 秒为一句示例：眼睛先下瞟，落地后发出主要声波，句中只轻微起伏。网格在骨骼姿态后的世界坐标中变形，再按每个骨骼的逆矩阵转换为加权 FFD；形变保持裁剪一致。仍未烘焙到导出时间轴。

当前 16 项测试通过，增加轮廓收缩、底部弧度、承重时长、句首冲击次数与眼神/声波先后验证。MCP 四态连播已重新生成；半速只用于浏览器观察，视频维持正常速度。另补充停止尚未收稳时重新思考的恢复检查，防止停在静止姿态。真实句首/语音驱动与编辑器导入仍未验证。
