"""A014–A016: in-flight controls, learning scope, usage and bounded work."""
import copy
import json
import threading
import time
import uuid
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pytest

from tests import test_conversation_v2 as fixtures
from agent_service.schemas import SessionMessageRequest, RunActionRequest, ConversationOutput, IntentDecision
from agent_service import run_accounting as accounting
from agent_service.execution_policy import budget_scope
from agent_service.interruptible_call import CallPool
from agent_service.openai_client import _report_usage, parse_model
from agent_service.source_projection import answer_sources


@pytest.fixture
def f():
    value = fixtures.ConversationTests()
    value.setUp()
    try:
        yield value
    finally:
        value.tearDown()


@pytest.mark.parametrize('initial,target', [('smart', 'deep'), ('deep', 'smart')])
@pytest.mark.parametrize('streaming', [False, True])
def test_switch_during_request_keeps_current_run_and_next_turn_uses_preference(f, initial, target, streaming):
    f.decision = fixtures.intent('question')
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    strengths = []
    def model(system, user, schema, **kw):
        strengths.append(kw.get('reasoning_effort'))
        if schema is ConversationOutput:
            kw['on_cancel_handle'](closed.set)
            if streaming: kw['on_partial']({'message': '正在解释'})
            entered.set()
            assert release.wait(3)
        return f.model(system, user, schema, **kw)
    ack = f.harness.accept(f.sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content='RAG 是什么', thinking_strength=initial))
    with patch('agent_service.conversation.parse_model', side_effect=model):
        worker = threading.Thread(target=f.harness.drain, args=(f.sid,))
        worker.start()
        try:
            assert entered.wait(2)
            for choice in [target, initial, target]:
                f.harness.action(ack.run_id, RunActionRequest(action_id=str(uuid.uuid4()), action='set_thinking', thinking_strength=choice))
            run = f.state()['runs'][ack.run_id]
            assert run['revision'] == 1 and run['status'] == 'running'
            assert run['thinking_strength'] == initial
            assert not closed.is_set()
        finally:
            release.set(); worker.join(3)
        assert not worker.is_alive()
        assert set(strengths) == ({'high'} if initial == 'deep' else {None})
        assert f.state()['runs'][ack.run_id]['attempt'] == 1
        strengths.clear()
        next_run = f.send('再解释一次')
        assert f.state()['runs'][next_run.run_id]['thinking_strength'] == target
        assert set(strengths) == ({'high'} if target == 'deep' else {None})


@pytest.mark.parametrize('action', ['steer', 'stop'])
def test_uncooperative_old_request_does_not_hold_session_or_publish_late_text(f, action):
    entered, release, exited, closed = [threading.Event() for _ in range(4)]
    f.decision = fixtures.intent('question')
    calls = 0
    def model(system, user, schema, **kw):
        nonlocal calls
        if schema is not ConversationOutput: return f.model(system, user, schema, **kw)
        calls += 1
        if calls == 1:
            kw['on_cancel_handle'](closed.set)
            entered.set()
            try:
                assert release.wait(4)  # deliberately ignores transport close
                kw['on_usage'](dict(response_id='late', input_tokens=50, output_tokens=7))
                kw['on_partial']({'message': '迟到的旧内容'})
                return ConversationOutput(message='迟到的旧内容')
            finally: exited.set()
        return ConversationOutput(message='补充后的回答')
    with patch('agent_service.conversation.parse_model', side_effect=model):
        ack = f.send('原问题', drain=False)
        worker = threading.Thread(target=f.harness.drain, args=(f.sid,)); worker.start()
        try:
            assert entered.wait(2)
            if action == 'steer': f.send('请补充一个例子', drain=False)
            else: f.control(ack.run_id, 'stop')
            worker.join(1)
            assert not worker.is_alive(), 'old socket must not hold orchestration'
            assert not release.is_set() and closed.wait(.5)
            replies = [m['content'] for m in f.state()['messages'] if m['role'] == 'coach']
            assert replies == (['补充后的回答'] if action == 'steer' else [])
        finally:
            release.set(); assert exited.wait(2); worker.join(2)
    # Usage survives stale-result fencing, without publishing that old reply.
    ledger = f.state()['runs'][ack.run_id]['model_calls']
    assert any(c['usage'] and c['usage'][0]['response_id'] == 'late' for c in ledger)
    assert all('迟到' not in m['content'] for m in f.state()['messages'])


def test_bounded_pool_rejects_more_detached_work_until_real_exit():
    pool = CallPool(limit=1, per_run=1)
    entered, release, stopped = [threading.Event() for _ in range(3)]
    errors = []
    def check():
        if stopped.is_set(): raise RuntimeError('cancelled')
    def caller():
        try:
            with budget_scope(seconds=1) as budget:
                pool.invoke('run', lambda: (entered.set(), release.wait(3)), check=check, budget=budget)
        except RuntimeError as exc: errors.append(str(exc))
    t = threading.Thread(target=caller); t.start(); assert entered.wait(1)
    stopped.set(); t.join(1)
    try:
        assert not t.is_alive() and errors == ['cancelled']
        assert sum(pool.active.values()) == 1
        with budget_scope(seconds=.05) as budget, pytest.raises(RuntimeError):
            pool.invoke('other', lambda: None, check=lambda: None, budget=budget)
    finally: release.set()


@pytest.mark.parametrize('kind,text', [
    ('capability_question', '你能帮我找资源然后下载吗'),
    ('resource_delivery', '那只给上面的书籍下载链接吧'),
    ('resource_delivery', '继续'),
])
def test_resource_delivery_never_reaches_tools_goals_capture_or_learning(f, kind, text):
    f.decision = fixtures.intent('question', resource_boundary=kind, needs_verification=True,
        public_search_query='小说下载', scope='learning', workflow='topic_exploration')
    with patch('agent_service.conversation.web_search_text') as search:
        ack = f.send(text)
    state = f.state(); run = state['runs'][ack.run_id]
    assert run['status'] == 'completed'
    assert '不承接寻找下载资源' in state['messages'][-1]['content']
    assert [s for s, _ in f.calls] == [IntentDecision]
    assert not state['tasks'] and not state.get('capture_offers') and not run['activity_kind']
    assert 'learning_evidence' not in [e['stage'] for e in state['events']]
    search.assert_not_called(); f.capture.assert_not_called()


def test_resource_mixed_keeps_only_explicit_learning_without_changing_existing_goal(f):
    f.decision = fixtures.intent('question', scope='learning', workflow='problem_solving')
    f.send('学习 RAG', mode='problem_solving')
    before = copy.deepcopy(f.state()['tasks'])
    f.decision = fixtures.intent('question', resource_boundary='mixed_learning',
        resource_learning_request='解释下载和流式读取的区别', answer_only=True)
    f.calls.clear()
    ack = f.send('帮我下载书籍，再解释下载和流式读取的区别')
    answer = next(p for schema, p in f.calls if schema is ConversationOutput)
    assert answer['context']['current_inputs'] == ['解释下载和流式读取的区别']
    assert f.state()['tasks'] == before
    assert f.state()['runs'][ack.run_id]['intent']['target_description'] == '解释下载和流式读取的区别'


@pytest.mark.parametrize('text', ['解释下载是怎么工作的', '不要下载，解释 RAG', '解释这句话：“帮我下载电子书”'])
def test_knowledge_and_quoted_download_text_are_not_keyword_blocked(f, text):
    f.decision = fixtures.intent('question', resource_boundary='none', answer_only=True)
    f.send(text)
    assert any(s is ConversationOutput for s, _ in f.calls)


@pytest.mark.parametrize('intent', ['stop', 'defer', 'reject'])
def test_real_controls_are_not_swallowed_by_resource_boundary(f, intent):
    f.decision = fixtures.intent(intent, resource_boundary='resource_delivery')
    ack = f.send({'stop':'停止', 'defer':'晚点再学', 'reject':'不要保存'}[intent])
    assert not f.state()['runs'][ack.run_id].get('resource_scope_reply')


def test_usage_is_actual_optional_and_reported_before_invalid_output():
    client = Mock()
    client.responses.parse.return_value = NS(id='response', status='incomplete', usage=NS(
        input_tokens=100, output_tokens=20, total_tokens=120,
        input_tokens_details=NS(cached_tokens=80), output_tokens_details=NS(reasoning_tokens=10)))
    rows=[]
    with patch('agent_service.openai_client._client', return_value=client), pytest.raises(RuntimeError):
        parse_model('system', 'user', ConversationOutput, on_usage=rows.append)
    assert rows == [dict(response_id='response', input_tokens=100, output_tokens=20,
        total_tokens=120, cached_input_tokens=80, reasoning_output_tokens=10)]
    _report_usage(NS(usage=None), rows.append)
    assert len(rows) == 1


def test_ledger_survives_ack_deduplicates_and_does_not_revive_deleted_session(f):
    ack=f.send('你好'); run=f.state()['runs'][ack.run_id]; call=run['model_calls'][0]
    assert call['usage_state'] == 'unavailable' and not call['usage']
    usage=dict(response_id='one', input_tokens=60, output_tokens=8)
    for _ in range(2): accounting.record(f.harness, f.sid, ack.run_id, call['id'], usage=usage)
    with f.store.transaction(f.sid) as data:
        data['last_acked_seq']=f.store.last_seq(data); f.store.compact_acknowledged(data)
    assert f.state()['runs'][ack.run_id]['model_calls'][0]['usage'] == [usage]
    f.harness.session_action(f.sid, str(uuid.uuid4()), 'archive', 1)
    f.harness.session_action(f.sid, str(uuid.uuid4()), 'delete', 2)
    accounting.record(f.harness, f.sid, ack.run_id, call['id'], usage=usage)
    assert f.store.get(f.sid) is None


@pytest.mark.parametrize('limit', ['calls', 'input', 'time'])
def test_turn_budget_stops_before_more_work_and_retry_keeps_ledger(f, limit):
    f.decision = fixtures.intent('question')
    ack = f.send('解释 RAG', drain=False)
    with f.store.transaction(f.sid) as data:
        r=data['runs'][ack.run_id]; accounting.begin(r)
        b=r['execution_budget']
        b[{'calls':'attempts','input':'estimated_input_tokens','time':'started'}[limit]] = {
            'calls':accounting.MODEL_ATTEMPTS, 'input':accounting.ESTIMATED_INPUT_LIMIT, 'time':time.time()-181}[limit]
    f.harness.drain(f.sid)
    assert f.state()['runs'][ack.run_id]['status'] == 'retryable_failed'
    assert f.state()['runs'][ack.run_id]['error_code'].startswith('RT.RUN.BUDGET')
    assert not f.calls
    f.control(ack.run_id, 'retry'); f.harness.drain(f.sid)
    assert f.state()['runs'][ack.run_id]['status'] == 'completed'


def test_endpoint_fallback_is_another_budgeted_input(f):
    ack=f.send('你好', drain=False)
    with f.store.transaction(f.sid) as data: data['runs'][ack.run_id]['status']='running'
    call=accounting.reserve(f.harness,f.sid,ack.run_id,1,node='intent',model='test',estimated_input=10)
    for _ in range(2): accounting.request(f.harness,f.sid,ack.run_id,1,call)
    run=f.state()['runs'][ack.run_id]
    assert run['execution_budget']['attempts']==2
    assert run['execution_budget']['estimated_input_tokens']==20
    assert run['model_calls'][0]['transport_requests']==2
    accounting.record(f.harness,f.sid,ack.run_id,call,usage=dict(response_id='fallback',input_tokens=10,output_tokens=2))
    assert f.state()['runs'][ack.run_id]['model_calls'][0]['usage_state']=='partial'


@pytest.mark.parametrize('stream', [False, True])
def test_exhausted_step_never_counts_a_transport_request(stream):
    sent = Mock()
    with patch('agent_service.openai_client._client', return_value=Mock()), \
         budget_scope(seconds=1, limit=0), pytest.raises(RuntimeError):
        parse_model('system', 'user', ConversationOutput, on_request=sent,
                    **({'on_partial': lambda _: None} if stream else {}))
    sent.assert_not_called()


def test_answer_source_projection_is_bounded_and_keeps_durable_originals():
    sources=[dict(type='public_source',url=f'https://example.com/{i}',content='知识'*5000) for i in range(4)]
    sources.append(dict(type='user_material',content='用户约束'*5000))
    original=copy.deepcopy(sources); projection=answer_sources(sources)
    assert sources == original
    assert sum(len(s['content']) for s in projection if s['type']=='public_source')<=12000
    assert projection[-1]==sources[-1]
    assert all(s['content_excerpted'] for s in projection[:-1])


def test_budget_and_busy_diagnostics_do_not_request_automatic_provider_retry():
    from agent_service.service_diagnostics import diagnose
    from agent_service.call_errors import ModelCallError
    for error, recovery in [(accounting.RunBudgetError('BUDGET_INPUT'), 'reduce_scope_or_explicit_retry'),
                            (ModelCallError('BUSY'), 'wait_for_capacity')]:
        result = diagnose(error)
        assert result['retryable'] is False
        assert result['recovery'] == recovery
