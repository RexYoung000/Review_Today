"""Opt-in synthetic contextual boundary reply replay with real models and an isolated DB."""
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
    with tempfile.TemporaryDirectory(prefix='review-today-scope-') as folder:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(folder) / 'unused.sqlite3')
        os.environ['REVIEW_TODAY_JEV_TEST'] = '0'
        from agent_service import conversation
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.jev_client import JevClient
        from agent_service.judgments import JudgmentEngine
        from agent_service.schemas import SessionMessageRequest
        from tests.case_library.recording import RunReport

        cases = [
            ('greeting', '你好'),
            ('model', '你现在用的是什么模型？'),
            ('svg', '你能帮我用 SVG 画一只鹈鹕骑单车吗，用 HTML 表现，直接给完整作品'),
            ('followup', '意思是你做不到？'),
            ('repeat', '那就是不能直接给我成品，对吧？'),
            ('mixed', '先解释 SVG 的 viewBox 是什么，再帮我做好完整网页作品。解释只要一句话，不用联网'),
            ('support', '我复习时间很少，给我一个简短建议，不用制定课程'),
            ('burden', '不想这么麻烦'),
            ('resource', '帮我找这本书的电子版下载链接'),
            ('resource_followup', '所以这个你也不能帮我找？'),
        ]
        planned = [variant + '/' + name for variant in ('baseline', 'jev') for name, _ in cases]

        class Report(RunReport):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
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
                    real_intent=any(c['schema'] in {'IntentDecision', 'IntentRemainder'} and 'output' in c
                                    for c in record['model_calls']),
                    no_blocked_tool_attempt=not record['tool_attempts'])
                row = dict(type='result', id=identity, **record, checks=checks,
                    automatic_result='PASS' if all(checks.values()) else 'FAIL', language_review='pending')
                self.records.append(row)
                self.write(row)
                print(json.dumps(dict(id=identity, checks=checks, replies=record['replies'],
                    elapsed_ms=record['run'].get('elapsed_ms')), ensure_ascii=False), flush=True)

        with Report(args.output, layer='live_generated_flow', planned=planned,
            fixture=dict(cases=cases, history='generated replies; separate sessions for support and resource pairs',
                purpose='contextual limits and followups; not a calibrated accuracy estimate')) as report:
            key_file = Path(os.environ.get('REVIEW_TODAY_JEV_KEY_FILE', str(Path.home() / '.codex/mcp/jev/credentials.json')))
            key = json.loads(key_file.read_text())['api_key']
            for variant in ('baseline', 'jev'):
                client = JevClient(key) if variant == 'jev' else None
                engine = JudgmentEngine(client, observer=lambda event: report.write(dict(event, type='jev_transport'))) if client else None
                harness = ConversationHarness(ConversationStore(HarnessStore(str(Path(folder) / (variant + '.sqlite3')))), judgments=engine)
                flow = str(uuid.uuid4())
                support = str(uuid.uuid4())
                resource = str(uuid.uuid4())
                try:
                    for name, text in cases:
                        sid = support if name in {'support', 'burden'} else resource if name in {'resource', 'resource_followup'} else flow
                        record = report.turn(harness, sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
                        before, after, run = record['before'], record['after'], record['run']
                        reply = '\n'.join(record['replies'])
                        checks = dict(history_preserved=after['messages'][:len(before['messages'])] == before['messages'],
                            no_task=not after['tasks'], no_pending=after['pending'] is None,
                            no_capture=not after.get('capture_offers'), no_goal=not after.get('focus_goal'),
                            no_learning_activity=name in {'mixed', 'support'} or not run.get('activity_kind'),
                            other_sessions_preserved=record['other_sessions_before'] == record['other_sessions_after'])
                        if name in {'svg', 'followup', 'repeat', 'resource', 'resource_followup'}:
                            checks.update(scope_handled=bool(run.get('scope_reply')),
                                short=len(reply) <= 240, no_reintroduced_identity='学习教练' not in reply and 'Review Today' not in reply,
                                no_teaching=not any(c['node'] in {'answer', 'lesson', 'teaching_preparation'} for c in run.get('model_calls', [])))
                        if name == 'model':
                            from agent_service.config import ROUTER_MODEL
                            checks['actual_model_configuration'] = ROUTER_MODEL in reply
                        if name == 'burden':
                            checks.update(feedback_handled=bool(run.get('reply_feedback_handled')),
                                short=len(reply) <= 120, no_extra_advice_call=not any(c['node'] == 'answer' for c in run.get('model_calls', [])))
                        if name == 'mixed':
                            checks['isolated_learning'] = bool((run.get('request_scope') or {}).get('learning_request'))
                            checks['answers_concept'] = 'viewBox' in reply
                            checks['brief_explanation'] = len(reply) <= 240
                        report.add(variant + '/' + name, record, checks)
                finally:
                    if client:
                        client.close()
        raise SystemExit(not report.passed)


if __name__ == '__main__':
    main()
