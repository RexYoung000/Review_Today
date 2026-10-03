"""Opt-in synthetic knowledge-card closure, with real configured model calls.

Run from agent-service (PTY permits an answer after seeing the real question):
    .venv/bin/python -m tests.knowledge_closure_real_smoke --live --output /tmp/new.jsonl

--case ambiguity runs only the fixed ambiguous-question evaluation. The flow's
SQLite client is an explicit test fixture, NOT the native Mac persistence layer.
--case capture --capture-source prior.jsonl replays only its frozen closure draft.
"""
from __future__ import annotations

from contextlib import ExitStack
import argparse
import copy
from datetime import datetime, timezone
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from unittest.mock import patch


INITIAL = ("直接教我 RAG 中关键词检索与向量检索如何匹配内容，第一步就比较字词匹配和语义匹配，"
           "讲清一个小点后给一道理解检查题。先不要讲文档切块或生成阶段。这是稳定基础概念，不需要联网。")
STATE_QUERY = "刚才我回答的这些知识点有没有记录成知识卡片？如果没有，要怎么生成？"
CLOSURE = "这个知识点我明白了，这一段可以收尾。"
SAVED_QUERY = "现在刚才这段知识卡片保存成功了吗？具体保存了什么？"
AMBIGUOUS = dict(
    question="文档里写的是‘如何安装电池’，用户搜‘电池怎么装’。如果只用关键词检索，会怎样？",
    reference="关键词检索主要根据字词匹配查找内容。向量检索把内容和问题转成向量，利用语义相似性召回不同措辞但意思相关的内容。",
    answer="可能会找到一些其他电池相关的内容，因为‘电池’这个词仍然能匹配。没说明分词和匹配规则，不能确定一定找不到安装电池这一段。",
    learning_step=dict(id="synthetic-keyword-step", title="关键词与向量检索的匹配差异"),
    check_binding=None,
)


def active_task(state):
    return (state.get('tasks') or {}).get(state.get('active_task_id'), {})


def lesson_state(state):
    task = active_task(state)
    ctx = task.get('context', {})
    return {key: copy.deepcopy(ctx.get(key)) for key in (
        'learning_plan', 'check_question', 'check_binding', 'last_lesson', 'lesson_index',
        'understanding', 'understanding_by_lesson', 'independent_passed', 'transfer_passed')}


class ClosureReport:
    """Observe calls without blocking authorized real run_capture generation."""
    def __init__(self, output, planned, scratch, *, source_report=None):
        self.output, self.planned, self.scratch = output, planned, scratch
        self.source_report = source_report
        self.stack, self.lock = ExitStack(), threading.RLock()
        self.calls, self.tools, self.records = [], [], []
        self.phase = 'startup'

    def write(self, value):
        with self.lock:
            self.file.write(json.dumps(value, ensure_ascii=False) + '\n')
            self.file.flush()

    def __enter__(self):
        from agent_service import config, conversation
        from tests.case_library.recording import code_version
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.output.open('x', encoding='utf-8')
        self.write(dict(type='header', schema_version=1,
            started_at=datetime.now(timezone.utc).isoformat(), planned=self.planned,
            fixture=dict(synthetic=True, initial_input=INITIAL, jev=False,
                capture_source=(dict(name=self.source_report.name,
                    sha256=hashlib.sha256(self.source_report.read_bytes()).hexdigest(),
                    case='topic_closure', scope='Frozen source; original teaching and evaluation are not replayed')
                    if self.source_report else None),
                persistence='Temporary SQLite test client, reopened before simulated Mac ACK'),
            models=dict(provider=config.PROVIDER, router=config.ROUTER_MODEL,
                        coach=config.COACH_MODEL, risk=config.RISK_MODEL), code=code_version(),
            boundaries=dict(real=['entry/coach/evaluation models', 'run_capture card generation',
                                  'Harness commit claim and acknowledgement'],
                            simulated=['Mac client persistence and ACK sender'],
                            blocked=['web search and public page fetch'], daily_data_used=False),
            limitations=['No native SwiftData/App UI or microphone validation.',
                         'Structural checks do not establish explanation or card semantic quality.',
                         'Model capability probes are outside semantic-call usage counts.']))
        actual_parse = conversation.parse_model

        def observe(system, user, schema, **kwargs):
            started = time.monotonic()
            try:
                payload = json.loads(user)
            except json.JSONDecodeError:
                payload = user
            call = dict(phase=self.phase, schema=schema.__name__, model=kwargs.get('model'),
                system_sha256=hashlib.sha256(system.encode()).hexdigest(), input=payload,
                usage=[], transport_requests=0)
            with self.lock:
                self.calls.append(call)
            usage_callback, request_callback = kwargs.get('on_usage'), kwargs.get('on_request')

            def usage(value):
                call['usage'].append(copy.deepcopy(value))
                if usage_callback:
                    usage_callback(value)

            def requested():
                call['transport_requests'] += 1
                if request_callback:
                    request_callback()

            try:
                value = actual_parse(system, user, schema, **dict(kwargs, on_usage=usage, on_request=requested))
                call['output'] = value.model_dump()
                return value
            except Exception as error:
                call.update(error_type=type(error).__name__, error_code=getattr(error, 'code', None))
                raise
            finally:
                call['elapsed_ms'] = round((time.monotonic() - started) * 1000)
                self.write(dict(type='model_call', **copy.deepcopy(call)))

        def blocked(name):
            def fail(*_args, **_kwargs):
                self.tools.append(dict(phase=self.phase, tool=name))
                raise RuntimeError('KNOWLEDGE_CLOSURE.WEB_DISABLED')
            return fail

        self.stack.enter_context(patch('agent_service.conversation.parse_model', side_effect=observe))
        for target in ('agent_service.conversation.web_search_text', 'agent_service.conversation.fetch_public_url',
                       'agent_service.conditional_teaching.fetch_public_url', 'agent_service.capture.web_search_text',
                       'agent_service.capture.fetch_public_url'):
            self.stack.enter_context(patch(target, side_effect=blocked(target)))
        return self

    def add(self, identity, record, checks):
        if identity not in self.planned or any(item['id'] == identity for item in self.records):
            raise ValueError('unexpected or duplicate evidence case')
        result = dict(type='result', id=identity, **record, checks=checks,
            automatic_result='PASS' if all(checks.values()) else 'FAIL', semantic_review='pending')
        self.records.append(result)
        self.write(result)
        task = record.get('task_projection') or {}
        plan = task.get('learning_plan') or {}
        shown_task = {key: task.get(key) for key in ('task_id', 'stage', 'status', 'check_question',
                                                   'understanding', 'check_binding')}
        shown_task['current_step'] = next((step for step in plan.get('steps', [])
                                          if step['id'] == plan.get('current_step_id')), None)
        print(json.dumps(dict(case=identity, replies=record.get('replies'), checks=checks,
            task=shown_task if task else None, output=record.get('output'),
            automatic_result=result['automatic_result']), ensure_ascii=False), flush=True)
        return result

    def turn(self, harness, sid, identity, content, checks_for, *, operation=None):
        from agent_service.schemas import SessionMessageRequest
        if not harness.store.tasks.path.resolve().is_relative_to(self.scratch.resolve()):
            raise ValueError('synthetic harness database escaped this run directory')
        self.phase = identity
        before = copy.deepcopy(harness.store.get(sid) or harness.store.empty(sid))
        start_calls, start_tools = len(self.calls), len(self.tools)
        body = SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=content,
                                    mode_preset='source_learning', operation=operation)
        started = time.monotonic()
        accepted = harness.accept(sid, body)
        harness.drain(sid)
        after = copy.deepcopy(harness.store.get(sid))
        run = after['runs'][accepted.run_id]
        task = active_task(after)
        record = dict(input=body.model_dump(), before=before, after=after, run=run,
            replies=[m['content'] for m in after['messages'] if m['role'] == 'coach' and m.get('run_id') == accepted.run_id],
            elapsed_ms=round((time.monotonic() - started) * 1000),
            model_calls=copy.deepcopy(self.calls[start_calls:]), tool_attempts=copy.deepcopy(self.tools[start_tools:]),
            task_projection=dict(task_id=task.get('task_id'), stage=task.get('stage'),
                status=task.get('status'), **lesson_state(after)))
        checks = dict(checks_for(record), completed=run['status'] == 'completed',
            no_web_attempts=not record['tool_attempts'],
            prior_history_preserved=after['messages'][:len(before['messages'])] == before['messages'])
        self.add(identity, record, checks)
        if run['status'] != 'completed':
            raise RuntimeError('synthetic run did not complete; no automatic replay')
        return record

    def __exit__(self, exc_type, exc, traceback):
        try:
            missing = [name for name in self.planned if not any(item['id'] == name for item in self.records)]
            failed = [item['id'] for item in self.records if item['automatic_result'] != 'PASS']
            usages = [usage for call in self.calls for usage in call['usage']]
            self.passed = not (exc_type or missing or failed)
            self.write(dict(type='summary', automatic_result='PASS' if self.passed else 'FAIL',
                executed=len(self.records), missing=missing, failed=failed,
                error_type=exc_type.__name__ if exc_type else None,
                model_calls=len(self.calls), transport_requests=sum(c['transport_requests'] for c in self.calls),
                usage_totals={key: sum(u.get(key, 0) or 0 for u in usages)
                              for key in ('input_tokens', 'output_tokens', 'total_tokens', 'cached_input_tokens')},
                semantic_review='pending', native_persistence_verified=False, rex_acceptance='pending'))
        finally:
            self.stack.close()
            self.file.close()


def run_flow(report, harness, sid, answer):
    first = report.turn(harness, sid, 'first_lesson', INITIAL, lambda r: dict(
        one_learning_task=len(r['after']['tasks']) == 1,
        check_present=bool(active_task(r['after']).get('context', {}).get('check_question')),
        check_bound=bool(active_task(r['after']).get('context', {}).get('check_binding')),
        no_cards_before_consent=not r['after'].get('capture_offers')))
    if not active_task(first['after']).get('context', {}).get('check_question'):
        raise RuntimeError('real lesson has no question to answer; inspect evidence')
    if not active_task(first['after']).get('context', {}).get('check_binding'):
        raise RuntimeError('real lesson question lacks its binding; stop before further model calls')
    clarification = report.turn(harness, sid, 'question_clarification', '我不理解你的问题', lambda r: dict(
        question_and_progress_preserved=lesson_state(r['before']) == lesson_state(r['after']),
        no_new_task=set(r['before']['tasks']) == set(r['after']['tasks']),
        no_evaluation=not any(c['schema'].endswith('MasteryEvaluation') for c in r['model_calls']),
        no_new_lesson=not any(c['node'] == 'lesson' for c in r['run'].get('model_calls', []))))
    if answer is None:
        print('SYNTHETIC ANSWER to the actual question above (no personal data):', flush=True)
        answer = input().strip()
    if not answer:
        raise ValueError('a nonempty synthetic answer is required')
    if lesson_state(first['after']) != lesson_state(clarification['after']):
        raise RuntimeError('clarification changed the live question or progress; do not guess an answer')
    evaluation = report.turn(harness, sid, 'answer', answer, lambda r: dict(
        real_evaluation=any(c['schema'] == 'MasteryEvaluation' for c in r['model_calls']),
        graded_original_question=all(c['input'].get('question') == active_task(r['before'])['context']['check_question']
            for c in r['model_calls'] if c['schema'] == 'MasteryEvaluation'),
        evaluation_has_binding=bool(r['run'].get('evaluated_binding')),
        no_card_generated_from_answer=not r['after'].get('capture_offers')))
    report.turn(harness, sid, 'status_before_save', STATE_QUERY, lambda r: dict(
        status_route=bool(r['run'].get('knowledge_status_reply')),
        no_card_generated_by_question=not r['after'].get('capture_offers'),
        learning_state_preserved=lesson_state(r['before']) == lesson_state(r['after'])))
    closure = report.turn(harness, sid, 'topic_closure', CLOSURE, lambda r: dict(
        one_offer=len(r['after'].get('capture_offers', {})) == 1,
        no_committed_card=not any(task.get('memory_package') for task in r['after']['tasks'].values())))
    offers = list(closure['after'].get('capture_offers', {}).values())
    if len(offers) != 1 or offers[0]['status'] != 'offered':
        raise RuntimeError('closure did not produce exactly one actionable offer')
    offer = offers[0]
    lesson_message_ids = {m['message_id'] for m in first['after']['messages']
                          if m['role'] == 'coach' and m.get('run_id') == first['run']['run_id']}
    evaluation_ids = {m['message_id'] for m in evaluation['after']['messages']
                      if m['role'] == 'coach' and m.get('run_id') == evaluation['run']['run_id']}
    report.phase = 'source_coverage'
    report.add('source_coverage', dict(offer=offer, lesson_message_ids=sorted(lesson_message_ids),
        evaluation_message_ids=sorted(evaluation_ids)), dict(
        lesson_in_source=bool(lesson_message_ids & set(offer['message_ids'])),
        feedback_in_source=bool(evaluation_ids & set(offer['message_ids'])),
        current_answer_not_copied_as_fact=answer not in offer['draft']['content'],
        source_text_present=bool(offer['draft']['content'])))
    save_offer(report, harness, sid, offer)


def save_offer(report, harness, sid, offer):
    saved = report.turn(harness, sid, 'capture_save', '录入知识', lambda r: dict(
        real_card_generation=any(c['schema'] == 'ExtractPayload' for c in r['model_calls']),
        waits_for_client_commit=active_task(r['after']).get('status') == 'committing',
        generated_cards=bool((active_task(r['after']).get('memory_package') or {}).get('knowledge'))),
        operation=dict(kind='capture_save', target_id=offer['id'], version=offer['version']))
    commit = active_task(saved['after'])
    cards = (commit.get('memory_package') or {}).get('knowledge', [])
    if commit.get('status') != 'committing' or not cards:
        raise RuntimeError('card generation failed; no fixture write or ACK sent')
    report.phase = 'fixture_persist_and_ack'
    claim = harness.claim_commit(commit['task_id'])
    database = report.scratch / 'synthetic-client.sqlite3'
    with sqlite3.connect(database) as client:
        client.execute('CREATE TABLE knowledge (knowledge_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, card_json TEXT NOT NULL)')
        client.executemany('INSERT INTO knowledge VALUES (?, ?, ?)',
            [(card['id'], commit['task_id'], json.dumps(card, ensure_ascii=False)) for card in cards])
    with sqlite3.connect(database) as client:
        rows = client.execute('SELECT knowledge_id, card_json FROM knowledge ORDER BY knowledge_id').fetchall()
        integrity = client.execute('PRAGMA integrity_check').fetchone()[0]
    readback = {row[0]: json.loads(row[1]) for row in rows}
    exact = readback == {card['id']: card for card in cards}
    if not exact or integrity != 'ok':
        raise RuntimeError('fixture persistence did not read back; ACK withheld')
    receipt = harness.acknowledge_task(commit['task_id'], len(commit['events']), sorted(readback))
    after_ack = harness.store.get(sid)
    report.add('fixture_persist_and_ack', dict(layer='temporary SQLite client plus simulated Mac ACK',
        claim=claim, cards=cards, readback_cards=list(readback.values()), receipt=receipt,
        after=copy.deepcopy(after_ack)), dict(
        exact_card_readback=exact, integrity_ok=integrity == 'ok',
        task_completed=after_ack['tasks'][commit['task_id']]['status'] == 'completed',
        offer_saved=after_ack['capture_offers'][offer['id']]['status'] == 'saved'))
    report.turn(harness, sid, 'status_after_save', SAVED_QUERY, lambda r: dict(
        status_route=bool(r['run'].get('knowledge_status_reply')),
        receipt_preserved=r['after']['capture_offers'][offer['id']]['knowledge_ids'] == sorted(readback),
        no_duplicate_generation=not any(c['schema'] == 'ExtractPayload' for c in r['model_calls'])))


def run_capture_replay(report, harness, source):
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    if rows[0].get('type') != 'header' or rows[0].get('fixture', {}).get('synthetic') is not True:
        raise ValueError('only an explicitly synthetic report can provide a frozen draft')
    closure = next(row for row in rows if row.get('type') == 'result' and row.get('id') == 'topic_closure')
    state = copy.deepcopy(closure['after'])
    sid = state['session_id']
    offers = list((state.get('capture_offers') or {}).values())
    if len(offers) != 1 or offers[0].get('status') != 'offered' or not offers[0].get('draft', {}).get('content'):
        raise ValueError('source report must contain exactly one actionable frozen closure')
    with harness.store.transaction(sid) as data:
        data.clear()
        data.update(state)
    report.write(dict(type='frozen_capture_source', source_case='topic_closure',
        original_offer=offers[0], exact_source_sha256=hashlib.sha256(offers[0]['draft']['content'].encode()).hexdigest()))
    save_offer(report, harness, sid, offers[0])


def ambiguity_checks(output):
    # The question can be treated as an open-ended request for conditional
    # outcomes, or as underspecified. Neither route may force a wrong answer.
    return dict(accepts_answer_or_qualifies_question=(
        output.question_validity == 'valid' and output.passed or
        output.question_validity == 'ambiguous' and not output.passed),
        no_whole_step_claim=not output.step_completion_demonstrated,
        explains_judgment=bool(output.feedback.strip()))


def replay_ambiguity_progress(harness, output):
    """Replay the captured model result through state logic with zero network."""
    from agent_service.conversation import _new_run
    from agent_service.harness_store import HarnessTaskRecord, now_iso
    from agent_service.learning_progress import bind_check, current_step, set_plan
    from agent_service.schemas import IntentDecision
    results = []
    for scope in ('concept', 'step'):
        sid, tid, mid = [str(uuid.uuid4()) for _ in range(3)]
        task = asdict(HarnessTaskRecord(task_id=tid, session_id=sid, client_message_id=mid,
            content='关键词与向量匹配差异', content_type='text', primary_language='zh',
            mode_preset='source_learning', mode='source_learning', status='awaiting_user', stage='teaching',
            context=dict(conversation_managed=True, last_lesson=AMBIGUOUS['reference'],
                check_question=AMBIGUOUS['question'], understanding='unknown', source_type='agent_generated')))
        set_plan(task, ['关键词与向量匹配差异', '后续应用'], '理解检索',
                 step_conditions=['比较两种检索的召回机制和局限', '说明应用方案'])
        binding = bind_check(task, AMBIGUOUS['question'], dict(step_title='关键词与向量匹配差异',
            concepts=['关键词检索'], evidence_quotes=[AMBIGUOUS['reference']], scope=scope), ['关键词检索'])
        run = _new_run(sid, mid, 'running')
        run['task_id'] = tid
        message = dict(message_id=mid, role='user', content=AMBIGUOUS['answer'], content_type='text',
            created_at=now_iso(), run_id=run['run_id'], task_id=tid, context={}, operation=None)
        with harness.store.transaction(sid) as data:
            data['tasks'][tid] = task
            data['active_task_id'] = tid
            data['runs'][run['run_id']] = run
            data['messages'].append(message)
        with patch.object(harness, '_call', return_value=output.model_copy(deep=True)) as stub:
            harness._evaluate(sid, run['run_id'], 1,
                IntentDecision(intents=['answer'], relation='continuation', scope='continue_goal',
                               rationale='Replay a captured synthetic real evaluation without another model call'), message)
        after = harness.store.get(sid)
        progressed = after['tasks'][tid]
        step = current_step(progressed)
        results.append(dict(scope=scope, binding=binding,
            preserved_current_step=step['id'] == current_step(task)['id'],
            no_whole_step_verified=step['understanding'] != 'verified',
            no_task_completion=progressed['status'] != 'completed',
            no_card_draft=not after.get('draft'), evaluator_calls_intercepted=stub.call_count,
            step=step, practice=progressed['context'].get('practice'),
            replies=[m['content'] for m in after['messages'] if m['role'] == 'coach']))
    return results


def run_ambiguity(report, harness):
    from agent_service import conversation
    from agent_service.config import COACH_MODEL
    from agent_service.conversation_prompts import EVALUATION_SYSTEM
    from agent_service.schemas import MasteryEvaluation
    report.phase = 'ambiguous_question'
    output = conversation.parse_model(EVALUATION_SYSTEM, json.dumps(AMBIGUOUS, ensure_ascii=False),
                                      MasteryEvaluation, model=COACH_MODEL)
    replay = replay_ambiguity_progress(harness, output)
    report.add('ambiguous_question', dict(layer='fixed synthetic direct evaluation schema call',
        input=AMBIGUOUS, output=output.model_dump(), offline_progress_replay=replay), dict(
        **ambiguity_checks(output), no_unjustified_progress=all(
            item['preserved_current_step'] and item['no_whole_step_verified'] and
            item['no_task_completion'] and item['no_card_draft'] for item in replay)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--answer', help='Synthetic answer; omit to read from PTY after the actual question')
    parser.add_argument('--case', choices=('flow', 'ambiguity', 'capture', 'all'), default='all')
    parser.add_argument('--capture-source', type=Path, help='Synthetic flow report whose closure draft is frozen for capture-only replay')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('use a new evidence file; never overwrite a prior attempt')
    if args.case in {'flow', 'all'} and args.answer is None and not sys.stdin.isatty():
        parser.error('use a PTY or supply --answer')
    if (args.case == 'capture') != bool(args.capture_source):
        parser.error('--capture-source is required only for --case capture')
    if args.answer is not None and not args.answer.strip():
        parser.error('--answer must not be empty')
    with tempfile.TemporaryDirectory(prefix='review-today-knowledge-closure-') as folder:
        scratch = Path(folder)
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(scratch / 'synthetic-harness.sqlite3')
        os.environ['REVIEW_TODAY_JEV_TEST'] = '0'
        from agent_service.config import PROVIDER
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        if PROVIDER != 'deepseek':
            raise RuntimeError('current expected DeepSeek provider is not active; configuration left unchanged')
        harness = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))
        planned = ([] if args.case in {'ambiguity', 'capture'} else ['first_lesson', 'question_clarification', 'answer',
            'status_before_save', 'topic_closure', 'source_coverage', 'capture_save',
            'fixture_persist_and_ack', 'status_after_save'])
        if args.case == 'capture':
            planned += ['capture_save', 'fixture_persist_and_ack', 'status_after_save']
        if args.case in {'ambiguity', 'all'}:
            planned.append('ambiguous_question')
        with ClosureReport(args.output, planned, scratch, source_report=args.capture_source) as report:
            if args.case in {'flow', 'all'}:
                run_flow(report, harness, str(uuid.uuid4()), args.answer)
            if args.case == 'capture':
                run_capture_replay(report, harness, args.capture_source)
            if args.case in {'ambiguity', 'all'}:
                run_ambiguity(report, harness)
        raise SystemExit(0 if report.passed else 1)


if __name__ == '__main__':
    main()
