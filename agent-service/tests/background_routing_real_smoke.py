"""Opt-in synthetic background/goal replay with real models and an isolated DB."""
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
    with tempfile.TemporaryDirectory(prefix='review-today-background-') as folder:
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
            ('greeting', '嘿'),
            ('identity', '你知道我是谁吗'),
            ('background', '我在准备ai产品经理的面试'),
            ('mixed_question', '先解释一下面试里常见的 RAG，用一句话就好，不用联网'),
            ('first_learning', '请带我学习 RAG 的检索和生成两部分，先讲检索，不用搜索也不用出题'),
            ('additional_background', '补充一下，我以前主要做用户增长'),
            ('different_goal', '换个学习目标，请带我学习吉他和弦'),
            ('clarify_learning', '请帮我安排 AI 产品经理面试的学习，先确定要准备哪块'),
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
            fixture=dict(cases=cases, history='generated replies within each variant; clarification uses a fresh session',
                purpose='background versus explicit learning; not a calibrated accuracy estimate')) as report:
            key_file = Path(os.environ.get('REVIEW_TODAY_JEV_KEY_FILE', str(Path.home() / '.codex/mcp/jev/credentials.json')))
            key = json.loads(key_file.read_text())['api_key']
            for variant in ('baseline', 'jev'):
                client = JevClient(key) if variant == 'jev' else None
                engine = JudgmentEngine(client, observer=lambda event: report.write(dict(event, type='jev_transport'))) if client else None
                harness = ConversationHarness(ConversationStore(HarnessStore(str(Path(folder) / (variant + '.sqlite3')))), judgments=engine)
                flow = str(uuid.uuid4())
                try:
                    for name, text in cases:
                        sid = str(uuid.uuid4()) if name == 'clarify_learning' else flow
                        record = report.turn(harness, sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
                        before, after, run = record['before'], record['after'], record['run']
                        reply = '\n'.join(record['replies'])
                        checks = dict(history_preserved=after['messages'][:len(before['messages'])] == before['messages'],
                            no_capture=not after.get('capture_offers'),
                            no_generic_purpose_prompt='你最希望学完后能够做什么' not in reply)
                        if name in {'greeting', 'identity', 'background', 'mixed_question'}:
                            checks.update(no_task=not after['tasks'], no_session_choice=after['pending'] is None,
                                no_chat_as_goal=not after.get('focus_goal'))
                        if name in {'background', 'additional_background'}:
                            checks.update(background_route=run.get('social_reply_kind') == 'background',
                                no_teaching_preparation=not any(c['node'] in {'teaching_preparation', 'lesson', 'clarify_goal'}
                                    for c in run.get('model_calls', [])), no_learning_activity=not run.get('activity_kind'))
                        if name == 'additional_background':
                            checks['progress_preserved'] = all(before.get(k) == after.get(k)
                                for k in ('tasks', 'active_task_id', 'focus_goal', 'pending', 'draft'))
                        if name == 'mixed_question':
                            checks['answered_question'] = '检索' in reply
                        if name == 'first_learning':
                            checks.update(task_created=len(after['tasks']) == 1,
                                no_session_choice=after['pending'] is None,
                                teaching=any(c['node'] == 'lesson' for c in run.get('model_calls', [])))
                        if name == 'different_goal':
                            checks.update(actual_goal_boundary=(after.get('pending') or {}).get('kind') == 'new_session',
                                progress_preserved=before['tasks'] == after['tasks'])
                        report.add(variant + '/' + name, record, checks)
                finally:
                    if client:
                        client.close()
        raise SystemExit(not report.passed)


if __name__ == '__main__':
    main()
