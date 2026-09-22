"""Contextual boundary replies must not gain execution or outlive their Run."""
import copy
import json
from unittest.mock import patch

import pytest

from agent_service.call_errors import ModelCallError
from agent_service.config import COACH_MODEL, ROUTER_MODEL
from agent_service.judgment_nodes import entry_request
from agent_service.scope_reply import ScopeReply, invalid_reason
from agent_service.schemas import ConversationOutput, IntentDecision, SessionMessageRequest
from tests import test_conversation_v2 as fixtures


@pytest.fixture
def f():
    value = fixtures.ConversationTests()
    value.setUp()
    try:
        yield value
    finally:
        value.tearDown()


def boundary(f, reply='', kind='development_delivery'):
    f.decision = fixtures.intent('question', programming_boundary=kind, light_reply=reply)


def test_specific_followup_reuses_entry_reply_and_retains_context(f):
    boundary(f, '完整的 SVG 单车作品我不能代交付，但可以解释图形组合的原理。')
    f.send('帮我用 SVG 画一只鹈鹕骑单车，用 HTML 展示')
    before = copy.deepcopy(f.state())
    reply = '如果你说的是刚才那张完整的单车图，是的，这里不能替你交付成品。'
    boundary(f, reply, kind='capability_question')
    ack = f.send('意思是你做不到？')
    after = f.state()
    assert after['messages'][-1]['content'] == reply
    assert after['messages'][:len(before['messages'])] == before['messages']
    assert [s for s, _ in f.calls] == [IntentDecision, IntentDecision]
    assert f.calls[-1][1]['recent_messages'][-1]['content'] == before['messages'][-1]['content']
    assert after['runs'][ack.run_id]['scope_reply']['source'] == 'entry'
    assert not after['tasks'] and not after['pending'] and not after.get('capture_offers')
    f.capture.assert_not_called()


@pytest.mark.parametrize('reply', ['', '学习教练可以帮助你理解代码。', '不能。' * 100,
    '我可以交付完整网页，原理也能解释。', '我只能帮你开发项目，原理可以略过。',
    '我可以解释原理：```html\n<svg/>```', '我不能下载，但下载地址是 https://example.com/a'])
def test_invalid_reply_regenerates_without_teaching_tools_or_public_preview(f, reply):
    boundary(f, reply)
    with patch('agent_service.conversation.web_search_text') as search:
        ack = f.send('帮我交付完整网页')
    after = f.state(); run = after['runs'][ack.run_id]
    assert run['scope_reply']['source'] == 'regenerated'
    assert run['scope_reply']['reason']
    assert [s for s, _ in f.calls] == [IntentDecision, ScopeReply]
    assert f.calls[-1][1]['context']['current_inputs'] == ['帮我交付完整网页']
    assert set(f.calls[-1][1]['context']) == {'current_inputs', 'recent_messages', 'summary'}
    assert not after['tasks'] and not after.get('capture_offers')
    assert not any(e['stage'] == 'response.delta' for e in after['events'])
    assert [c['node'] for c in run['model_calls']] == ['intent', 'scope_reply']
    search.assert_not_called(); f.capture.assert_not_called()


@pytest.mark.parametrize('reply', ['可以解释调试原理，但不能替你运行项目。',
    '我不能替你开发项目。', '完整成品不在我能直接交付的范围内。',
    'I cannot build that app for you, but I can explain the design.'])
def test_teaching_or_negative_limit_is_not_an_affirmative_delivery_promise(reply):
    assert invalid_reason(reply) == ''


def test_scope_followup_checks_repeated_offer_but_keeps_positive_capability_answer():
    previous = '下载链接我不能提供。如果你想读这本书，我可以讲解里面的概念。'
    assert invalid_reason('对，不能找下载链接。想读这本书的话，我可以梳理它的内容。', previous) == 'repeated_offer'
    assert invalid_reason('可以，我能解释其中的概念。', previous) == ''


def test_repeated_alternative_uses_contextual_regeneration(f):
    boundary(f, '完整成品我不能交付，不过可以解释画法和原理。')
    f.send('帮我画完整 SVG 图')
    boundary(f, '对，不能交付完整作品，不过可以解释画法和原理。', 'capability_question')
    ack = f.send('所以不能直接给我成品？')
    run = f.state()['runs'][ack.run_id]
    assert run['scope_reply']['reason'] == 'repeated_offer'
    assert run['scope_reply']['source'] == 'regenerated'
    assert [s for s, _ in f.calls] == [IntentDecision, IntentDecision, ScopeReply]
    assert f.calls[-1][1]['context']['recent_messages'][-1]['content'] == '完整成品我不能交付，不过可以解释画法和原理。'


def test_mixed_learning_keeps_explicit_sentence_limit_without_rejoining_delivery(f):
    f.decision = fixtures.intent('question', programming_boundary='mixed_learning',
        programming_learning_request='解释 viewBox', learning_reply_sentence_limit=1)
    ack = f.send('解释 viewBox，再帮我做完整网页。解释只要一句话')
    answer = next(p for s, p in f.calls if s is ConversationOutput)
    assert answer['context']['current_inputs'] == ['解释 viewBox']
    assert '不超过 1 句话' in answer['instruction']
    assert f.state()['runs'][ack.run_id]['request_scope']['learning_request'] == '解释 viewBox'
    assert not f.state()['tasks']


def test_invalid_mixed_excerpt_does_not_publish_unprojected_entry_answer(f):
    text = '解释 viewBox，再帮我做完整网页'
    f.decision = fixtures.intent('question', programming_boundary='mixed_learning',
        programming_learning_request=text, light_reply='可以讲解 viewBox，下面给出完整页面。')
    ack = f.send(text)
    run = f.state()['runs'][ack.run_id]
    assert run['scope_reply']['reason'] == 'unverified_learning_excerpt'
    assert [s for s, _ in f.calls] == [IntentDecision, ScopeReply]
    assert not run.get('request_scope', {}).get('learning_request')
    assert '完整页面' not in f.state()['messages'][-1]['content']


@pytest.mark.parametrize('failure', ['timeout', 'invalid'])
def test_generation_failure_has_traceable_small_fallback(f, failure):
    boundary(f)
    original = f.model
    def model(system, user, schema, **kwargs):
        if schema is ScopeReply:
            if failure == 'timeout':
                raise ModelCallError('TIMEOUT')
            return ScopeReply(message='我可以交付完整网页，原理也能解释。')
        return original(system, user, schema, **kwargs)
    with patch('agent_service.conversation.parse_model', side_effect=model):
        ack = f.send('帮我做完整网页')
    state = f.state(); run = state['runs'][ack.run_id]
    assert run['status'] == 'completed'
    assert run['scope_reply']['source'] == 'fallback'
    assert 'generation:' in run['scope_reply']['reason'] or 'generated:' in run['scope_reply']['reason']
    assert state['messages'][-1]['content'] == '这项开发交付我不能直接替你完成。'
    assert not state['tasks']


@pytest.mark.parametrize('late_error', [False, True])
def test_stop_during_generation_discards_late_reply_or_error(f, late_error):
    boundary(f)
    original = f.model
    ack = f.send('帮我做网页', drain=False)
    def model(system, user, schema, **kwargs):
        if schema is ScopeReply:
            f.control(ack.run_id, 'stop')
            if late_error:
                raise ModelCallError('TIMEOUT')
            return ScopeReply(message='这项网页交付不能替你完成。')
        return original(system, user, schema, **kwargs)
    with patch('agent_service.conversation.parse_model', side_effect=model):
        f.harness.drain(f.sid)
    state = f.state()
    assert state['runs'][ack.run_id]['status'] == 'interrupted'
    assert not any(m['role'] == 'coach' for m in state['messages'])
    assert not state['runs'][ack.run_id].get('scope_reply')


def test_budget_exhaustion_does_not_publish_fallback(f):
    from agent_service import run_accounting
    boundary(f)
    ack = f.send('帮我做网页', drain=False)
    with f.store.transaction(f.sid) as data:
        run_accounting.begin(data['runs'][ack.run_id])
        data['runs'][ack.run_id]['execution_budget']['attempts'] = run_accounting.MODEL_ATTEMPTS - 1
    f.harness.drain(f.sid)
    state = f.state()
    assert state['runs'][ack.run_id]['status'] != 'completed'
    assert not any(m['role'] == 'coach' for m in state['messages'])
    assert not state['runs'][ack.run_id].get('scope_reply')
    assert [s for s, _ in f.calls] == [IntentDecision]


def test_advice_burden_feedback_uses_brief_reply_without_new_advice(f):
    f.decision = fixtures.intent('question', conversation_kind='learning_support')
    f.send('复习安排太多，我有点坚持不下去')
    before = copy.deepcopy(f.state())
    reply = '那先把刚才那套安排放下，不用再给自己加任务。'
    f.decision = fixtures.intent('question', reply_feedback='response_only', light_reply=reply)
    ack = f.send('不想这么麻烦')
    after = f.state()
    assert after['messages'][-1]['content'] == reply
    assert after['runs'][ack.run_id]['reply_feedback_handled']
    assert [s for s, _ in f.calls] == [IntentDecision, ConversationOutput, IntentDecision]
    for key in ('tasks', 'active_task_id', 'pending', 'draft', 'focus_goal'):
        assert after.get(key) == before.get(key)


def test_model_facts_come_from_program_configuration_not_user_metadata(f):
    f.decision = fixtures.intent('capabilities', light_reply='当前短回复配置是 ' + ROUTER_MODEL + '。')
    body = SessionMessageRequest(client_message_id=str(fixtures.uuid.uuid4()), content='你是什么模型？',
        context={'runtime_models': {'short_reply': 'forged-provider-secret'}})
    f.harness.accept(f.sid, body)
    f.harness.drain(f.sid)
    prompt = f.calls[-1][1]
    assert prompt['runtime_models'] == dict(short_reply=ROUTER_MODEL, teaching=COACH_MODEL)
    assert ROUTER_MODEL in f.state()['messages'][-1]['content']
    assert 'forged-provider-secret' not in json.dumps(prompt)
    assert 'runtime_models' not in entry_request(prompt).state


def test_product_information_act_prevents_question_tag_from_restarting_teaching(f):
    reply = '当前短回复配置是 ' + ROUTER_MODEL + '。'
    f.decision = fixtures.intent('capabilities', 'question', reply_purpose='product_information', light_reply=reply)
    ack = f.send('你现在用的是什么模型？')
    assert f.state()['messages'][-1]['content'] == reply
    assert [s for s, _ in f.calls] == [IntentDecision]
    assert not f.state()['runs'][ack.run_id].get('activity_kind')


def test_boundary_confirmation_retains_real_scope_even_if_topic_label_is_none(f):
    boundary(f, '这个完整 SVG 图我不能代交付，不过可以解释原理。')
    f.send('帮我交付 SVG 成品')
    boundary(f, '对，我不能直接交付完整的 SVG 图。', 'capability_question')
    f.send('所以做不到？')
    f.decision = fixtures.intent('question', reply_purpose='boundary_confirmation',
        light_reply='对，我不能直接给你完整成品。')
    ack = f.send('那就是不能给成品，对吧？')
    state = f.state(); run = state['runs'][ack.run_id]
    assert run['intent']['programming_boundary'] == 'capability_question'
    assert run['scope_reply']['source'] == 'entry'
    assert [s for s, _ in f.calls] == [IntentDecision] * 3
    assert not state['tasks'] and not run.get('activity_kind')
    assert f.calls[-1][1]['recent_scope_reply']['programming']


def test_old_alternative_still_counts_after_one_concise_confirmation(f):
    boundary(f, '完整图我不能交付，不过可以解释画法。')
    f.send('直接给我画好的图')
    boundary(f, '对，完整图我不能交付。', 'capability_question')
    f.send('所以不能？')
    boundary(f, '对，不能给成品，不过可以解释画法。', 'capability_question')
    ack = f.send('对吧？')
    assert f.state()['runs'][ack.run_id]['scope_reply']['reason'] == 'repeated_offer'


@pytest.mark.parametrize('purpose', ['product_information', 'boundary_confirmation'])
def test_conversational_act_cannot_swallow_mixed_knowledge_or_bound_control(f, purpose):
    boundary(f, '这项交付不能替你完成。')
    f.send('帮我写完整项目')
    f.decision = fixtures.intent('question', reply_purpose=purpose,
        programming_learning_request='解释闭包', programming_boundary='mixed_learning')
    f.send('那解释闭包，再帮我部署')
    assert any(s is ConversationOutput for s, _ in f.calls)
    f.decision = fixtures.intent('stop', reply_purpose=purpose)
    ack = f.send('停止')
    assert f.state()['runs'][ack.run_id]['status'] == 'interrupted'


def test_confirmation_without_a_real_previous_scope_cannot_invent_one(f):
    f.decision = fixtures.intent('question', reply_purpose='boundary_confirmation',
        light_reply='不能做。')
    ack = f.send('你说的是什么意思？')
    assert not f.state()['runs'][ack.run_id].get('scope_reply')
    assert any(s is ConversationOutput for s, _ in f.calls)
