# Agent 语音后端隔离验证 · 2026-10-03

本记录只证明受控合同与 synthetic 真实供应商链路。没有采集麦克风、播放声音、访问日常数据库、启动／替换日常服务或修改供应商配置。真人外放回声、自然停顿、打断手感、音质与最终体验均待验收。

## 实现与边界

独立 `/v2/agent/voice/{owner_id}/audio` 复用当前阿里云北京实时配置；未知 draft UUID 可连接且不建聊天，active/0 的首次文字提交可接续。归档、删除、生命周期变化会失效；句子逐个照稿核对再释放音频。`interrupt` 清当前／等待播报，不丢已提交转写；`clear(false)` 仅清未提交输入；默认 `clear` 让旧转写失效且保留旧 ACK 占位。所有音频只在服务内存流转，用量表仅保留匿名数字汇总。

输入渠道 `text/voice` 与内容类型独立；旧 text 幂等回执兼容，换渠道复用消息 ID 拒绝。最新补充、排队拆分、停止／恢复和主题续接保留对应渠道。仅公开正文节点增加口语约束，不增加工具、记忆、知识保存或评分权限。

## 受控验证

- 初版新旧语音及渠道合同 24 项通过。
- 既有 conversation/topic_capture 与语音定向回归 97 项、5 个子用例通过。
- 后续补齐已完成供应商响应的本地打断竞态、精确待播队列、分帧 PCM 总量、主题续接渠道后，最新新旧语音及渠道合同 **28 项通过**。
- 检查覆盖：迟到音频、旧 ACK／转写错配、逐句顺序、静音保留已提交内容、空转写不造文字、无效／归档／删除 owner、运行中 lifecycle 改变、输入与排队限额、匿名用量、渠道幂等与公开风格边界。
- 完整后端全量回归见下方增补；这些测试不替代完整 Mac UI 或真实设备验收。

## 首次三轮真实链路

输入由 macOS `say` 合成并送入临时服务；合成 WAV 读取后立即删除。每轮转写原文通过真实现有 Agent 写入同一合成 Session，然后把最多前两句实际回复送回实时供应商。音频只统计字节，不向扬声器播放。本脚本自己的句子切分不证明 Mac 正式切分器通过。

| 轮次 | 转写提交后 | Agent 完成 | 每句首音频等待 |
| --- | ---: | ---: | --- |
| 1 | 631 ms | 5,639 ms | 3,122 ms |
| 2 | 398 ms | 6,185 ms | 2,046 / 2,728 ms |
| 3 | 393 ms | 5,182 ms | 3,021 ms |

这些计时分段测量，不是端到端首句延迟承诺。首音频是在整句文字一致核对后放行。另验证了生成中打断、清除排队句、新句恢复（首音频 1,438 ms）与同 Session 重连。三条用户消息保留，同 UUID 从草稿变成 active Session。

原始证据：[音频链路与计时](synthetic-live.json)、[三轮完整 Agent RunReport](synthetic-agent-runs.jsonl)。该组 transport／结构断言通过，语言质量仍须人工判断。

### 原始内容人工复核

- 三轮分别讨论光合作用的作用、原料和能量、串起前述过程；实际第二／三轮确实承接首轮主题。记录保留全部模型输入与原始回答，未用关键词出现来判语义通过。
- 首轮 ASR 把“只讨论”识别为“之讨论”；本样例仍被正确理解，不能据此推断真实说话识别准确率。
- 初次第二轮有三段和未被询问的化能合成旁枝，偏离简短对话目标；第三轮“把原料和能量交给叶绿素”的措辞不够准确。它们作为真实限制保留，不隐藏或算作高质量教学通过。
- 风格随后轻量收紧为一般一个核心点、2–4 句，不添加未问旁枝，不以口语化牺牲事实精确；未硬截断模型输出、切模型或改 thinking。只用原首轮上下文重放原第二轮一次，未重新跑三轮音频。
- [单回合真实风格验证](synthetic-style-turn2.jsonl) 新回复：“原料是二氧化碳和水，能量是光能。……叶绿体里的光合作用用光能作动力，把二氧化碳和水这两种原料合成葡萄糖，同时放出氧气。”更直接、无原先旁枝；仍分两段，不能外推为所有场景稳定符合风格或完整自然度验收。
- 第一次准备固定上下文时，测试脚本把报告中“缺省字段”的 null 还原成集合值，产生本地 TypeError，发生在模型调用前。已修复脚本并保留[失败记录](synthetic-style-fixture-failure.jsonl)；该次模型调用数为零，不是日常服务或供应商失败。

## 实际用量与费用边界

累计包含原三轮与风格单回合，以下是供应商上报 token；缓存输入是输入总量的子集，不重复相加。配置模型名与服务上报的实际名称可能不同，原始回执保留两者。

| 配置文字模型 | 实际传输请求 | 输入 token | 输出 token | 其中缓存输入 |
| --- | ---: | ---: | ---: | ---: |
| `deepseek-flash` | 8 | 47,141 | 1,582 | 44,800 |
| `deepseek-v4-flash` | 4 | 16,719 | 371 | 12,672 |

实时音频主连接：6 次 response.created，输入 token 5,354、输出 token 593、合计 5,947；收到输入 PCM 400,994 字节，释放输出 PCM 1,843,200 字节。另有一次仅连接后关闭的重连，其 token usage 未上报，不将缺失值认定为零费用。取消请求的账单可能与可见生成不同。

没有本次账单或经过核对的计价依据，**不报告人民币／美元费用**，也不把 token 合计当作结算价格。机器可核对汇总及证据哈希见 [usage-summary.json](usage-summary.json)。

## 重现入口

```sh
cd agent-service
.venv/bin/python -m tests.agent_voice_live --live --output /tmp/new-agent-voice-report.json
.venv/bin/python -m tests.agent_voice_style_live --live --source /tmp/new-agent-voice-report.agent.jsonl --output /tmp/new-style-report.jsonl
```

两者必须显式 `--live` 且使用新输出文件，内部在导入服务模块前设置临时数据库。它们会真实调用当前配置供应商并产生费用；没有麦克风或音频播放行为。RunReport 阻断网页／知识写入，不能证明这些工具的成功。

## 增补：全量回归与恢复／续接的语音因果绑定

通过 `DASHSCOPE_API_KEY='' bash agent-service/run-controlled.sh` 完成全量隔离后端回归：**910 passed、4 skipped、365 subtests passed，耗时 208.15 秒**。该脚本先验证五组离线案例清单，再清空凭证、用临时 SQLite 库运行全部测试，没有日常服务／供应商调用。四项跳过来自既有 `ActualBrowserTests` 的显式 Chrome opt-in 条件，未启用浏览器；五条警告为既有 FastAPI/Starlette 弃用提示。完整日志：[backend-full-controlled.log](backend-full-controlled.log)。

随后只读复查 Mac 协调器，发现实际缺口：一次语音“继续”会产生控制 Run，并恢复另一个旧 Run 输出真正答案；话题保存／稍后继续也可能派生独立 Run。仅按用户消息自身的 runID 选播会漏掉这些因果明确的答案。经确认增加独立 `voice_input_ids`，不改变供模型理解请求的 `input_ids`：

- 新语音输入绑定其当前消息 ID；新的 text 补充清除旧语音播放授权；队列拆分各自恢复实际渠道与因果 ID。
- 暂停后通过语音继续，把本次语音输入 ID 赋予被恢复的旧 Run，同时保留旧 Run 原始 prompt input_ids。
- 话题稍后／跳过／保存操作在 offer 中保存本次触发操作的渠道与语音因果 ID；异步保存 ACK 后创建续接 Run 时继承它，不能回退到旧话题 anchor 误判是哪次语音触发。
- `public_run`、Session events 的 `runs`、GET Run 与恢复 checkpoint 原样公开此数组；原生端只能播放与当前语音输入集合相交的 Run，不能放宽为任意同 Session 回复。

本次修复后执行新旧语音、渠道、conversation、topic_capture 定向回归：**105 passed、5 subtests passed，耗时 44.53 秒**，包含恢复旧 Run、保持 prompt 语义、话题保存延迟 ACK、队列拆分与公开序列化合同。日志：[backend-voice-lineage-controlled.log](backend-voice-lineage-controlled.log)。全量 910 项是该小幅因果绑定增补前的结果，增补后使用上述 105 项定向覆盖；没有重复调用真实模型或把原三轮 synthetic 音频报告说成覆盖新恢复分支。
