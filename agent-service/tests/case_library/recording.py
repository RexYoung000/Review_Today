"""Append-only evidence for fixed replays and generated multi-turn flows."""
from __future__ import annotations

from contextlib import ExitStack
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from .schema import ROOT, digest


def code_version(root=ROOT):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
    # Includes uncommitted new replay tooling; HEAD alone is not the tested code.
    paths = sorted((root / 'agent-service/agent_service').rglob('*.py'))
    paths += sorted((root / 'agent-service/tests').rglob('*.py'))
    paths += sorted((root / 'agent-service/tests/fixtures/agent_cases').glob('*.json'))
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return dict(commit=git('rev-parse', 'HEAD'), dirty=bool(git('status', '--porcelain')),
                source_sha256=digest(hashes), files=hashes)


def state_snapshot(data):
    keys = ('session_id', 'mode', 'thinking_strength', 'paused', 'active_task_id', 'tasks',
            'pending', 'draft', 'summary', 'messages', 'capture_offers', 'focus_goal',
            'runs', 'summary_version', 'summarized_message_ids', 'teaching_context',
            'continuation_selection', 'dialogue_clarification')
    return copy.deepcopy({k: data.get(k) for k in keys})


class RunReport:
    """Never rewrites past evidence or translates absent results into PASS.

    Model calls remain real. Web and knowledge writes are deliberately blocked
    for these dialogue baselines, with attempts captured as failures.
    """
    def __init__(self, output, *, layer, planned, fixture):
        if layer not in {'live_fixed_context', 'live_generated_flow'}:
            raise ValueError('declare a supported verification layer')
        if not planned or len(planned) != len(set(planned)):
            raise ValueError('a nonempty unique execution plan is required')
        self.output, self.layer = Path(output), layer
        self.planned, self.fixture = planned, fixture
        self.records, self.calls, self.tool_attempts = [], [], []
        self.stack = ExitStack()
        self.file = None

    def write(self, record):
        self.file.write(json.dumps(record, ensure_ascii=False) + '\n')
        self.file.flush()

    def __enter__(self):
        from agent_service import config
        from agent_service import conversation
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.output.open('x', encoding='utf-8')
        self.write(dict(type='header', schema_version=1, layer=self.layer,
            started_at=datetime.now(timezone.utc).isoformat(), planned=self.planned,
            fixture=self.fixture, code=code_version(),
            models=dict(provider=config.PROVIDER, router=config.ROUTER_MODEL,
                        coach=config.COACH_MODEL, risk=config.RISK_MODEL),
            isolation='temporary synthetic database', blocked=['web_search', 'web_read', 'knowledge_write'],
            limitations=['模型路由与回答真实；网页与知识写入被阻断，不能证明这些工具成功。',
                         '结构化断言不是自然度判定；模型可调用性探测不计入记录的语义调用数。']))
        actual_parse = conversation.parse_model

        def observe(system, user, schema, **kwargs):
            try:
                model_input = json.loads(user)
            except json.JSONDecodeError:
                model_input = user
            call = dict(schema=schema.__name__, model=kwargs.get('model'),
                        reasoning_effort=kwargs.get('reasoning_effort'),
                        system_sha256=hashlib.sha256(system.encode()).hexdigest(),
                        schema_sha256=digest(schema.model_json_schema()),
                        input_sha256=hashlib.sha256(user.encode()).hexdigest(), input=model_input)
            self.calls.append(call)
            try:
                value = actual_parse(system, user, schema, **kwargs)
                call['output'] = value.model_dump()
                return value
            except Exception as exc:
                call['error_type'] = type(exc).__name__  # no upstream bodies/keys
                raise

        def blocked(name):
            def fail(*args, **kwargs):
                self.tool_attempts.append(name)
                raise RuntimeError('CASE_LIBRARY.BLOCKED_TOOL')
            return fail

        self.stack.enter_context(patch('agent_service.conversation.parse_model', side_effect=observe))
        for target, name in [
            ('agent_service.conversation.web_search_text', 'web_search'),
            ('agent_service.conversation.web_search_capability', 'web_search'),
            ('agent_service.conversation.fetch_public_url', 'web_read'),
            ('agent_service.conditional_teaching.fetch_public_url', 'web_read'),
            ('agent_service.conversation.run_capture', 'knowledge_write'),
        ]:
            self.stack.enter_context(patch(target, side_effect=blocked(name)))
        return self

    def turn(self, harness, sid, body):
        database = harness.store.tasks.path.resolve()
        if not any(database.is_relative_to(root.resolve()) for root in (Path(tempfile.gettempdir()), Path('/tmp'))):
            raise ValueError('replays require a temporary database, never the daily app database')
        def other_sessions():
            with harness.store.tasks._connection() as connection:
                ids = [row[0] for row in connection.execute('SELECT session_id FROM agent_sessions_v2') if row[0] != sid]
            return {key: dict(state=state_snapshot(harness.store.get(key)), policy=harness.store.memory_policy(key))
                    for key in ids}
        before = copy.deepcopy(harness.store.get(sid) or harness.store.empty(sid))
        other_before = other_sessions()
        start_calls, start_tools = len(self.calls), len(self.tool_attempts)
        accepted = harness.accept(sid, body)
        harness.drain(sid)
        after = harness.store.get(sid)
        run = after['runs'][accepted.run_id]
        events = [e for e in after['events'] if e['run_id'] == accepted.run_id]
        replies = [m['content'] for m in after['messages']
                   if m['role'] == 'coach' and m['run_id'] == accepted.run_id]
        return dict(input=body.model_dump(), before=state_snapshot(before), after=state_snapshot(after),
                    other_sessions_before=other_before, other_sessions_after=other_sessions(),
                    run=copy.deepcopy(run), events=copy.deepcopy(events), replies=replies,
                    model_calls=copy.deepcopy(self.calls[start_calls:]),
                    tool_attempts=self.tool_attempts[start_tools:])

    def add(self, identity, record, checks):
        if identity not in self.planned or any(r['id'] == identity for r in self.records):
            raise ValueError('unexpected or duplicate result')
        if not checks or any(type(v) is not bool for v in checks.values()):
            raise ValueError('nonempty boolean check results required')
        calls = record.get('model_calls', [])
        checks = dict(checks,
            completed=record['run']['status'] == 'completed' and bool(record['replies']),
            real_intent=any(c['schema'] == 'IntentDecision' and 'output' in c for c in calls),
            no_blocked_tool_attempt=not record['tool_attempts'])
        result = dict(type='result', id=identity, **record, checks=checks,
                      automatic_result='PASS' if all(checks.values()) else 'FAIL',
                      language_review='pending', rex_acceptance='pending')
        self.records.append(result)
        self.write(result)

    def __exit__(self, exc_type, exc, traceback):
        try:
            missing = [identity for identity in self.planned if not any(r['id'] == identity for r in self.records)]
            failed = [r['id'] for r in self.records if r['automatic_result'] != 'PASS']
            self.passed = not (exc_type or missing or failed) and bool(self.records)
            self.write(dict(type='summary', automatic_result='PASS' if self.passed else 'FAIL',
                            executed=len(self.records), planned=len(self.planned), missing=missing, failed=failed,
                            error_type=exc_type.__name__ if exc_type else None,
                            language_review='pending', rex_acceptance='pending'))
        finally:
            self.stack.close()
            self.file.close()
        return False
