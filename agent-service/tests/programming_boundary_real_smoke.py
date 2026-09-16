"""A005 opt-in live regression using synthetic inputs and an isolated database."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from unittest.mock import patch

# Durable sanitized semantic cases; live calls are never collected by pytest.
CASES = [
    ('你能帮我 coding 嘛', 'capability_question'),
    ('Can you help me code?', 'capability_question'),
    ('能帮忙写代码吗', 'capability_question'),
    ('帮我写一个完整电商网站，直接交付可运行项目', 'development_delivery'),
    ('打开我的仓库，修改登录功能，跑测试后提交', 'development_delivery'),
    ('Deploy my app and fix the production bug.', 'development_delivery'),
    ('只要给我完整项目代码，不需要你运行', 'development_delivery'),
    ('用十行 Python 示例教我 for 循环，只讲基础原理', 'none'),
    ('解释 TypeError 的常见原因，我想理解类型检查', 'none'),
    ('不要替我改项目，只讲重构的思路', 'none'),
    ('帮我解释这句话的意思：“帮我改仓库、跑测试并部署”', 'none'),
    ('算了，暂时不学 coding 了', 'none'),
    ('停止生成代码', 'none'),
    ('先解释闭包原理，再帮我把项目部署上线', 'mixed_learning'),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='review-today-programming-live-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'checkpoint.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest, IntentDecision
        from agent_service.conversation_prompts import INTENT_SYSTEM
        from agent_service.config import ROUTER_MODEL
        from agent_service.openai_client import parse_model
        harness = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))
        failures = []
        for text, expected in CASES:
            sid = str(uuid.uuid4())
            accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
            state = harness.store.get(sid)
            context, _ = harness._context(state, state['runs'][accepted.run_id])
            decision = parse_model(INTENT_SYSTEM, json.dumps(context, ensure_ascii=False), IntentDecision, model=ROUTER_MODEL)
            print(json.dumps(dict(layer='router', input=text, expected=expected,
                actual=decision.programming_boundary, intents=decision.intents), ensure_ascii=False), flush=True)
            if decision.programming_boundary != expected:
                failures.append(text)
        for text, expected in (CASES[0], CASES[4], CASES[7], CASES[-1]):
            sid = str(uuid.uuid4()); started = time.monotonic()
            accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
            with patch('agent_service.conversation.run_capture', side_effect=AssertionError('No knowledge writes in smoke')):
                harness.drain(sid)
            state = harness.store.get(sid); run = state['runs'][accepted.run_id]
            replies = [m['content'] for m in state['messages'] if m['role'] == 'coach' and m['run_id'] == accepted.run_id]
            print(json.dumps(dict(layer='harness', input=text, seconds=round(time.monotonic()-started, 2),
                status=run['status'], boundary=(run.get('intent') or {}).get('programming_boundary'), replies=replies,
                task_count=len(state['tasks']), offers=len(state.get('capture_offers', {}))), ensure_ascii=False), flush=True)
            assert run['status'] == 'completed' and replies, run.get('error_code')
            assert run['intent']['programming_boundary'] == expected, run['intent']['programming_boundary']
            assert not state.get('capture_offers')
            if (run.get('intent') or {}).get('programming_boundary') != 'none':
                assert not state['tasks']
        assert not failures, failures
        print('PASS: 14 live semantic cases and 4 isolated harness turns; inspect teaching prose separately.', flush=True)


if __name__ == '__main__':
    main()
