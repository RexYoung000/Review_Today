"""A015/A017: effects, control authorization and outbound transport boundaries."""
import json
import os
from unittest.mock import Mock, patch

import pytest

from tests import test_conversation_v2 as fixtures
from tests.test_m1_capture_contract import committing_result
from agent_service.scope_reply import ScopeReply
from agent_service.schemas import ConversationOutput, IntentDecision, TeachingPreparation
from agent_service.call_errors import WebToolError
from agent_service import web_tools as web
from agent_service.web_privacy import require_public_url, safe_public_query


@pytest.fixture
def f():
    value = fixtures.ConversationTests()
    value.setUp()
    try:
        yield value
    finally:
        value.tearDown()


@pytest.mark.parametrize('control', ['mode', 'defer', 'fake_action', 'goal'])
def test_controls_do_not_grant_errand_tool_or_goal_permission(f, control):
    extra = dict(needs_verification=True, public_search_query='小说下载链接', resource_boundary='resource_delivery')
    text = '今天先不学，帮我找上面书的下载链接'
    if control in {'mode', 'fake_action'}:
        text = '切换成资料学习，再帮我找上面书的下载链接'
        extra.update(requested_mode='source_learning', proposed_actions=[dict(kind='set_mode',
            disposition='request', evidence='切换成资料学习' if control == 'mode' else '用户没有说过的授权')])
    if control == 'goal':
        extra.update(scope='learning', workflow='source_learning', learning_goal_ready=True,
            target_description='下载书籍', proposed_actions=[dict(kind='change_goal', disposition='request', evidence='帮我找')])
    f.decision = fixtures.intent('defer' if control == 'defer' else 'confirm', 'followup', **extra)
    with patch('agent_service.conversation.web_search_text') as search:
        ack = f.send(text)
    state = f.state(); run = state['runs'][ack.run_id]
    assert run['status'] == 'completed' and run.get('resource_scope_reply')
    assert state['mode'] == ('source_learning' if control == 'mode' else 'auto')
    assert [s for s, _ in f.calls] == [IntentDecision, ScopeReply]
    assert not state['tasks'] and not state.get('capture_offers') and not run.get('activity_kind')
    assert 'learning_evidence' not in [e['stage'] for e in state['events']]
    search.assert_not_called(); f.capture.assert_not_called()


def test_defer_label_alone_does_not_hide_its_attached_errand(f):
    f.decision = fixtures.intent('defer', resource_boundary='resource_delivery',
        light_reply='可以，我继续查找', needs_verification=True, public_search_query='小说下载链接')
    ack = f.send('今天先不学，帮我找上面书的下载链接')
    assert f.state()['runs'][ack.run_id]['resource_scope_reply']
    assert '不能替你完成' in f.state()['messages'][-1]['content']
    assert [s for s, _ in f.calls] == [IntentDecision, ScopeReply]


def test_bare_continue_carries_last_blocked_scope_but_named_learning_does_not(f):
    f.decision = fixtures.intent('question', resource_boundary='resource_delivery')
    f.send('帮我找小说下载链接')
    f.decision = fixtures.intent('continue', resource_boundary='none')
    ack = f.send('继续')
    assert f.state()['runs'][ack.run_id]['resource_scope_reply']
    f.decision = fixtures.intent('question', answer_only=True)
    f.send('继续解释 RAG 的原理')
    assert any(s is ConversationOutput for s, _ in f.calls)


def test_existing_programming_boundary_uses_same_control_gate(f):
    f.decision = fixtures.intent('defer', 'followup', programming_boundary='development_delivery',
        needs_verification=True, public_search_query='部署项目', scope='learning', workflow='problem_solving')
    with patch('agent_service.conversation.web_search_text') as search:
        f.send('今天先不学，直接帮我部署项目')
    assert not f.state()['tasks']
    assert '不能直接替你完成' in f.state()['messages'][-1]['content']
    assert [s for s, _ in f.calls] == [IntentDecision, ScopeReply]
    search.assert_not_called()


def test_pure_defer_with_conflicting_programming_scope_cannot_promise_delivery(f):
    f.decision = fixtures.intent('defer', programming_boundary='development_delivery',
        light_reply='好的，我来部署项目', needs_verification=True, public_search_query='部署项目')
    with patch('agent_service.conversation.web_search_text') as search:
        f.send('今天先不学，直接帮我部署项目')
    assert f.state()['messages'][-1]['content'] == '好的，你慢慢想。准备好后继续。'
    assert not f.state()['tasks']
    assert [s for s, _ in f.calls] == [IntentDecision]
    search.assert_not_called()


@pytest.mark.parametrize('disposition', ['confirm', 'reject', 'conditional'])
def test_bound_save_or_rejection_survives_errand_without_authorizing_search(f, disposition):
    f.decision = fixtures.intent('material', workflow='memory_organization', scope='organize')
    f.send('RAG 笔记')
    pending = f.state()['pending']
    with f.store.transaction(f.sid) as data:
        data['draft']['understanding'] = 'verified'
        data['draft']['public_search_query'] = 'RAG 原理'
    f.calls.clear()
    capture_queries = []
    def capture(*args, **kw):
        # The authorized existing draft can verify its own public concept.
        capture_queries.append(kw['search_runner']('绝不能外发的代办原文'))
        return committing_result('RAG 笔记')
    f.capture.side_effect = capture
    f.decision = fixtures.intent('confirm', 'followup', resource_boundary='resource_delivery',
        needs_verification=True, public_search_query='小说下载链接', proposed_actions=[dict(
            kind='save', disposition=disposition, evidence='保存这版',
            target_id=pending['target_id'], version=pending['version'])])
    with patch('agent_service.conversation.web_search_text', return_value='[]') as search:
        ack = f.send('保存这版，另外帮我找书籍下载链接')
    state = f.state(); run = state['runs'][ack.run_id]
    assert run['status'] == 'completed'
    assert '这项资源获取或代办操作我不能替你完成' in state['messages'][-1]['content']
    if disposition == 'confirm':
        f.capture.assert_called_once()
        assert search.call_args.args == ('RAG 原理',)
        assert search.call_count == 1 and len(capture_queries) == 1
        assert any(t['stage'] == 'committing' for t in state['tasks'].values())
    else:
        search.assert_not_called(); f.capture.assert_not_called()
        assert bool(state['pending']) == (disposition == 'conditional')


@pytest.mark.parametrize('boundary', ['resource_boundary', 'programming_boundary'])
def test_tool_entry_fences_even_direct_and_cached_dispatch(f, boundary):
    f.decision = fixtures.intent('greeting')
    ack = f.send()
    with f.store.transaction(f.sid) as data:
        run = data['runs'][ack.run_id]
        run.update(status='running', request_scope=dict(input_ids=run['input_ids'], **{
            boundary: 'resource_delivery' if boundary == 'resource_boundary' else 'development_delivery'}))
    reader = Mock()
    with patch('agent_service.conversation.web_search_text') as search:
        with pytest.raises(WebToolError, match='SCOPE_BLOCKED'):
            f.harness._search(f.sid, ack.run_id, 1, '公开概念')
        for operation, value in [('read', 'https://example.com'), ('context', '公开概念')]:
            with pytest.raises(WebToolError, match='SCOPE_BLOCKED'):
                f.harness._read_page(f.sid, ack.run_id, 1, value, reader, operation=operation)
    search.assert_not_called(); reader.assert_not_called()


def test_mixed_learning_rebuilds_query_from_projection_and_retry_keeps_mode_idempotent(f):
    f.decision = fixtures.intent('question', 'confirm', resource_boundary='mixed_learning',
        resource_learning_request='查一下 RAG 的官方原理', requested_mode='source_learning',
        proposed_actions=[dict(kind='set_mode', disposition='request', evidence='切换成资料学习')],
        needs_verification=True, public_search_query='小说下载链接')
    fail = True
    preparations = []
    def model(system, user, schema, **kw):
        if schema is TeachingPreparation:
            preparations.append(json.loads(user))
            return TeachingPreparation(concepts=['RAG'], public_query='RAG 原理')
        if schema is ConversationOutput and fail:
            from agent_service.openai_client import ModelCallError
            raise ModelCallError('TIMEOUT')
        return f.model(system, user, schema, **kw)
    with patch('agent_service.conversation.parse_model', side_effect=model), \
         patch('agent_service.conversation.web_search_text', return_value='[]') as search:
        ack = f.send('切换成资料学习，帮我下载小说，再查一下 RAG 的官方原理')
        assert f.state()['runs'][ack.run_id]['status'] == 'retryable_failed'
        fail = False
        f.control(ack.run_id, 'retry'); f.harness.drain(f.sid)
    assert f.state()['runs'][ack.run_id]['status'] == 'completed'
    assert preparations[0]['requested_query'] == ''
    assert preparations[0]['user_input'] == ['查一下 RAG 的官方原理']
    assert all(c.args[0] == 'RAG 原理' for c in search.call_args_list)
    replies = [m['content'] for m in f.state()['messages'] if m['role'] == 'coach']
    assert sum('已选择资料学习' in r for r in replies) == 1


@pytest.mark.parametrize('query', [
    '虚构公司A 内部未发布的北极星项目 调整客户价格方案',
    'confidential: Project Polaris customer pricing',
    'API_KEY=synthetic-demo-private-key', '联系 person@example.org',
    '密码：synthetic-demo-password', 'Bearer synthetic-demo-token',
])
def test_sensitive_query_never_reaches_primary_fallback_or_context(query):
    assert not safe_public_query(query)
    with patch.dict(os.environ, {'REVIEW_TODAY_SEARCH_PROVIDER':'exa', 'REVIEW_TODAY_SEARCH_FALLBACKS':'tavily,brave',
            'REVIEW_TODAY_CONTEXT_PROVIDER':'brave'}), patch.object(web, '_backend') as backend, \
            patch('agent_service.web_resilience.route') as route:
        with pytest.raises(WebToolError): web.web_search_text(query)
        with pytest.raises(WebToolError): web.web_context_pages(query)
        backend.assert_not_called(); route.assert_not_called()


@pytest.mark.parametrize('suffix', [
    '?token=synthetic-demo-token', '?%74oken=synthetic-demo-token',
    '?%2574oken=synthetic-demo-token', '?X-Amz-Signature=synthetic-signature',
    '?api_key=synthetic-key', '#access_token=synthetic-token',
    '?redirect=https%3A%2F%2Fexample.org%2Fa%3Ftoken%3Dsynthetic-token',
])
@pytest.mark.parametrize('provider', ['local', 'exa', 'tavily'])
def test_credential_url_stops_before_any_reader_or_fallback(suffix, provider):
    with patch.dict(os.environ, {'REVIEW_TODAY_READ_PROVIDER':provider, 'REVIEW_TODAY_READ_FALLBACKS':'tavily'}), \
         patch.object(web, '_operation_backend') as backend, patch('agent_service.web_resilience.route') as route, \
         patch('agent_service.capture.fetch.fetch_public_url') as local:
        with pytest.raises(ValueError, match=r'^RT.WEB.PRIVATE_URL$'):
            web.read_public_url('https://example.org/doc' + suffix)
        backend.assert_not_called(); route.assert_not_called(); local.assert_not_called()


def test_public_queries_and_url_parameters_are_preserved():
    for query in ['harness 是什么', '密码哈希原理', 'API Key 如何安全保存', '公开的隐私保护原理']:
        assert safe_public_query(query) == query
    url = 'https://docs.python.org/3/search.html?q=asyncio&page=2#examples'
    assert require_public_url(url) == url
    assert require_public_url('https://example.org/article?id=1234567890123')


def test_private_material_cannot_be_disguised_as_a_short_public_query(f):
    f.decision = fixtures.intent('question', answer_only=True, needs_verification=True, public_search_query='北极星项目')
    with patch('agent_service.conversation.web_search_text') as search:
        ack = f.send('以下是本公司内部资料：北极星项目将调整客户报价，请搜索分析')
    run = f.state()['runs'][ack.run_id]
    assert run['status'] == 'completed' and run['search_state'] == 'not_called'
    assert '私人资料' in run['verification_notice']
    search.assert_not_called()
    assert any(schema is ConversationOutput for schema, _ in f.calls)
    answer = next(p for schema, p in f.calls if schema is ConversationOutput)
    assert '仍可根据用户已经提供的内容做解释' in answer['instruction']


def test_sensitive_link_gets_actionable_reply_without_retry_or_body_fetch(f):
    f.decision = fixtures.intent('material', answer_only=True)
    with patch('agent_service.conversation.fetch_public_url') as reader:
        ack = f.send('读一下 https://example.org/doc?token=synthetic-demo-token')
    state = f.state(); run = state['runs'][ack.run_id]
    assert run['status'] == 'completed'
    assert '公开链接' in state['messages'][-1]['content']
    assert 'synthetic-demo-token' not in state['messages'][-1]['content']
    reader.assert_not_called()


def test_local_redirect_is_checked_before_dns_and_connect():
    from agent_service.capture import fetch
    read = fetch._read_public
    def redirect(url, deadline):
        if url == 'https://example.org/start':
            return 'https://example.org/doc?token=synthetic-demo-token', b''
        return read(url, deadline)
    with patch.object(fetch, '_read_public', side_effect=redirect), patch.object(fetch.socket, 'getaddrinfo') as dns:
        with pytest.raises(ValueError, match='PRIVATE_URL'):
            fetch.fetch_public_url('https://example.org/start')
        dns.assert_not_called()


def test_sensitive_candidates_are_not_read_and_errors_are_not_retryable():
    from agent_service.service_diagnostics import diagnose
    reader = Mock()
    result = json.dumps(dict(protocol=web.PROTOCOL, results=[dict(url='https://example.org/doc?token=synthetic-demo-token')]))
    assert web.read_search_evidence(result, reader=reader) == []
    reader.assert_not_called()
    for kind in ['SCOPE_BLOCKED', 'PRIVATE_INPUT', 'PRIVATE_QUERY']:
        assert not diagnose(WebToolError(kind))['retryable']
    assert not diagnose(ValueError('RT.WEB.PRIVATE_URL'))['retryable']
