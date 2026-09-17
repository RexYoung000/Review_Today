# A010：普通问答被误建为学习任务

## 真实问题与根因

Auto 会话“你好”→“我不知道”→“harness是什么，它有什么作用”。第三轮意图输出 question，但同时是 learning/topic_exploration/answer_only=false。旧 Harness 用 scope 判断 full_goal，创建 clarify_goal 学习任务，回复固定的学习用途问题；该轮没有搜索事件。模型还无依据把 harness 定为测试领域。此前的举例追问偶发误建任务也是同类问题。

## 修复

- Auto 中单纯 question/followup/example/hint 由程序规范为 conversation/answer_only，不因模型 scope/workflow 启动课程；有目标/操作/明确继续教学/模式选择的混合请求保留各自流程。
- 显式 goal、真实任务继续、非 Auto 学习模式或明确直接教学才可进入完整目标流程。局部新主题直接回答，不强迫创建会话；新主题不沿用旧主题证据，后续追问也不能拿旧来源充数。
- 对话纠错回到真实原问题；取消历史误建任务必须同时满足：Auto、原始意图只有普通问题、仍停在 clarify_goal、无学习计划/成果/来源/草稿。仅把错误任务记为 cancelled/routing_corrected 并解除活动绑定，不删除历史、不动真正的学习目标或已学进度。真实用户库不会被脚本批量修改，在用户下次纠错或提问时按条件处理。
- 多义术语先区分含义，不凭空认定领域。基础问题简短说明；追问不复述背景，要一个例子就给一个，不展开整套课程。长度是生成提示，未做硬截断。

## 受控验证

419 tests / 69 subtests 通过；只有既有 FastAPI 弃用警告。输出见 `controlled-summary.txt`。

执行 `PYTHONPATH=/tmp/review-today-topic-test-deps-20260915 bash agent-service/run-controlled.sh`。

覆盖三轮复现、首次提问、同概念举例、旧错误任务继续提问/纠错、显式学习目标保护、真实学习进度保护、非 Auto 模式、实际对象澄清、局部换题与证据隔离。修正旧测试中“举例就应建任务”的错误期望，保留来源复用断言；会话边界测试改为明确系统学习新目标，继续验证原有绑定操作。

## 真实回放

在 agent-service 运行 `.venv/bin/python -m tests.ordinary_question_real_smoke --live`。临时库隔离，不改用户聊天；第一部分意图、网页搜索/读取及回答均真实，第二部分仅注入历史误建任务初态，随后纠错使用真实模型。脚本不输出密钥。

`initial-verbose-replay.jsonl`：流程修复通过，但人工复核发现初答冗长、类比请求扩展出多个例子；据此加强局部回答指令。最终 `live-replay.jsonl` 通过：普通问题实际核验并回答，无任务；类比只给一个主体例子且未重搜；真实纠错回到原问题、历史误建任务变为 cancelled/routing_corrected。回答长度仍为软约束，不能保证每次都满足建议字数。

## Rex 验收

新会话输入“你好”“我不知道”“harness是什么，它有什么作用”，应直接解释，不出现“明确一个学习目标”卡片。再说“举个生活类比就好”，应局部回答。原有受影响会话可说“我只是问它是什么，先回答问题”，错误任务应取消并回到原问题；历史消息仍保留。明确说“带我系统学习”应继续支持正常学习任务。

应用已重启加载修复；重启前确认无运行中的会话，健康检查见 `runtime-health.json`。用户原聊天未改写。

本轮不改原生布局；新会话和历史会话最终体验待 Rex 验收，不宣称覆盖所有模型表达。
