# A006 / A007 验证记录

## A006

2026-09-17，使用合成输入与临时数据库；未向正常用户会话写入测试消息。

- 服务：`PYTHONPATH=/tmp/review-today-topic-test-deps-20260915 bash agent-service/run-controlled.sh`：324 passed，34 subtests passed。
- 原生：`bash tests/mac/run-contracts.sh`：20 套执行契约及真实本地 SSE 通过；通用问句词不误召回知识卡片。
- 模型：`cd agent-service && .venv/bin/python -m tests.dialogue_routing_real_smoke --live`：2 轮通过，输出见 live-a006.jsonl。首问直接回答；第二轮模拟历史错误后正确修复。
- 原生界面端到端与 Rex 体验验收未完成；不能仅凭模型文本通过标记产品验收。

## A007

实施中；尚未记录通过。
