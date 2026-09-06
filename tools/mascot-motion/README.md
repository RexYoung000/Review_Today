# Review Today 动画制作 MCP

2026-09-07。用于本次 V3 吉祥物的 Spine 4.2 形变小样；不是通用自动绑定产品。已有源码、可调用 MCP、可操作预览与可编辑 JSON，未接入日常 App，未验证 Spine 编辑器导入。

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
node src/call.mjs motion_export '{"name":"recall-v1"}'
```

适配器通过 SDK 建立 stdio 连接、协商协议并调用工具；并非绕过 MCP 直接运行内部函数。图片响应保存到 `.work/renders/` 并返回路径，AI 可看图后再次修改；浏览器每 2.5 秒检查版本，在可见状态加载新版本。

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

- `npm test`：官方解析/加权形变实际生效、眼睛领先身体、权重与关键帧损坏检测、网格翻折拒绝；真实 stdio MCP 握手/工具清单/修改/绑定/图片返回/导出/失败后保留上一版；HTTP 同源/目录边界/错误请求检查，以及两个 MCP 进程同时修改时不丢失参数。9 项测试通过（含前后遮挡与投影裁剪回归）。
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
