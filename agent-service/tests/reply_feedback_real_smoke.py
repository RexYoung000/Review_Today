"""Opt-in A012 greeting/feedback replay; synthetic data and new evidence only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('a new evidence file is required')
    with tempfile.TemporaryDirectory(prefix='review-today-reply-feedback-') as folder:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(folder) / 'unused.sqlite3')
        os.environ['REVIEW_TODAY_JEV_TEST'] = '0'
        from agent_service import conversation
        from agent_service.conversation import ConversationHarness, _new_run
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore, now_iso
        from agent_service.jev_client import JevClient
        from agent_service.judgments import JudgmentEngine
        from agent_service.schemas import SessionMessageRequest
        from tests.case_library.recording import RunReport

        cases = ['greeting', 'how_are_you', 'really', 'flow_feedback', 'repeated_feedback',
                 'mixed_question', 'quoted_feedback', 'initial_how_are_you', 'capabilities', 'mixed_greeting']
        planned = [variant + '/' + case for variant in ('baseline', 'jev') for case in cases]

        class Report(RunReport):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.lock, self.prompts = threading.Lock(), set()

            def write(self, row):
                with self.lock:
                    super().write(row)

            def __enter__(self):
                super().__enter__()
                observed = conversation.parse_model

                def capture(system, user, schema, **kwargs):
                    identity = hashlib.sha256((system + schema.__name__).encode()).hexdigest()
                    if identity not in self.prompts:
                        self.prompts.add(identity)
                        self.write(dict(type='prompt', system=system, schema=schema.model_json_schema()))
                    return observed(system, user, schema, **kwargs)

                self.stack.enter_context(patch('agent_service.conversation.parse_model', side_effect=capture))
                return self

            def add(self, identity, record, checks):
                checks.update(completed=record['run']['status'] == 'completed' and bool(record['replies']),
                    real_intent=any(c['schema'] in {'IntentDecision', 'IntentRemainder'} and 'output' in c for c in record['model_calls']),
                    no_blocked_tool_attempt=not record['tool_attempts'])
                row = dict(type='result', id=identity, **record, checks=checks,
                           automatic_result='PASS' if all(checks.values()) else 'FAIL', language_review='pending')
                self.records.append(row)
                self.write(row)
                print(json.dumps(dict(id=identity, passed=all(checks.values()), checks=checks,
                    feedback=record['run'].get('intent', {}).get('reply_feedback'), replies=record['replies'],
                    elapsed_ms=record['run'].get('elapsed_ms')), ensure_ascii=False), flush=True)

        def seed(harness):
            sid = str(uuid.uuid4())
            with harness.store.transaction(sid) as data:
                for text in ('你好', '你好吗'):
                    mid = str(uuid.uuid4())
                    run = _new_run(sid, mid, 'completed')
                    run.update(dialogue_only=True, social_reply_kind='social')
                    data['runs'][run['run_id']] = run
                    for role, body in [('user', text), ('coach', '你好。')]:
                        data['messages'].append(dict(message_id=mid if role == 'user' else str(uuid.uuid4()),
                            role=role, content=body, content_type='text', created_at=now_iso(),
                            run_id=run['run_id'], task_id=None, context={}, operation=None))
            return sid

        with Report(args.output, layer='live_generated_flow', planned=planned,
                    fixture=dict(cases=cases, fixed_prefix=[['你好', '你好。'], ['你好吗', '你好。']],
                                 purpose='A012 first greeting orientation and reply feedback; not confidence calibration')) as report:
            key_file = Path(os.environ.get('REVIEW_TODAY_JEV_KEY_FILE', str(Path.home() / '.codex/mcp/jev/credentials.json')))
            key = json.loads(key_file.read_text())['api_key']
            for variant in ('baseline', 'jev'):
                client = JevClient(key) if variant == 'jev' else None
                engine = JudgmentEngine(client, observer=lambda event: report.write(dict(event, type='jev_transport'))) if client else None
                h = ConversationHarness(ConversationStore(HarnessStore(str(Path(folder) / (variant + '.sqlite3')))), judgments=engine)
                flow = str(uuid.uuid4())
                try:
                    for name, text, expected in [
                        ('greeting', '你好', 'none'),
                        ('how_are_you', '你好吗', 'none'),
                        ('really', '真的吗', 'none'),
                        ('flow_feedback', '为什么你只会回我这句话', 'response_only'),
                        ('repeated_feedback', '为什么你只会回我这句话', 'response_only'),
                        ('mixed_question', '别再机械重复了，请用一句话解释 RAG，不需要联网。', 'with_request'),
                        ('quoted_feedback', '“为什么你只会回我这句话”这句话中的“只会”表达了什么意思？请解释这句话，不是在评价你。', 'none'),
                        ('initial_how_are_you', '你好吗？？？', 'none'),
                        ('capabilities', '你是谁，能帮我做什么？', 'none'),
                        ('mixed_greeting', '你好，请用一句话解释 RAG，不需要联网。', 'none'),
                    ]:
                        sid = flow if name in cases[:4] or name == 'capabilities' else seed(h) if name in {'repeated_feedback', 'mixed_question'} else str(uuid.uuid4())
                        record = report.turn(h, sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
                        before, after, run = record['before'], record['after'], record['run']
                        calls = run.get('model_calls', [])
                        reply = '\n'.join(record['replies'])
                        checks = dict(feedback=run.get('intent', {}).get('reply_feedback') == expected,
                            no_task=not after['tasks'], history_preserved=after['messages'][:len(before['messages'])] == before['messages'],
                            no_capture=not after.get('capture_offers'),
                            no_blame=not any(x in reply for x in ('没给我可回', '没有信息量', '没必要展开成闲聊')))
                        if name in cases[:5] or name in {'initial_how_are_you', 'capabilities'}:
                            checks.update(bounded=len(reply) <= 120,
                                no_teaching=not any(c['node'] in {'answer', 'teaching_preparation', 'lesson'} for c in calls),
                                no_general_chat_invitation=not any(x in reply for x in ('随便聊', '想聊', '八卦', '吐槽')),
                                no_invented_motive='偷懒' not in reply)
                        if name in {'how_are_you', 'really'}:
                            checks['no_repeated_introduction'] = 'Review Today' not in reply and '学习教练' not in reply
                            checks['no_repeated_start_invitation'] = not any(x in reply for x in ('随时发', '发给我', '直接提问'))
                            checks['no_unrelated_fallback'] = reply != '嗯，按自己的节奏来就好。'
                        if expected == 'response_only':
                            checks['no_feedback_introduction'] = 'Review Today' not in reply and '学习教练' not in reply
                        if name in {'how_are_you', 'initial_how_are_you'}:
                            checks['not_fixed_greeting'] = reply.strip('。！! ') != '你好'
                        if name in {'greeting', 'initial_how_are_you', 'capabilities'}:
                            checks['identity_and_capabilities'] = ('Review Today' in reply and '学习教练' in reply
                                and any(x in reply for x in ('理解', '弄懂', '讲清', '解释'))
                                and any(x in reply for x in ('资料', '材料', '知识')))
                        if name in {'greeting', 'initial_how_are_you'}:
                            checks['how_to_start'] = ('直接' in reply and any(x in reply for x in ('问', '发'))) or any(x in reply for x in ('发给我', '发来'))
                        if name in {'mixed_question', 'mixed_greeting'}:
                            checks['answered_actual_request'] = any(c['node'] == 'answer' for c in calls) and '检索' in reply
                            checks['requested_brief_reply'] = len(reply) <= 120 and '\n' not in reply
                            checks['no_unrelated_introduction'] = '学习教练' not in reply and 'Review Today' not in reply
                        report.add(variant + '/' + name, record, checks)
                finally:
                    if client:
                        client.close()
        raise SystemExit(not report.passed)


if __name__ == '__main__':
    main()
