"""Clarification is a justified dialogue action, never an uncertain topic label."""
from agent_service.schemas import IntentDecision

LEGACY_QUESTION = '你希望继续刚才的内容，还是开始一个新的学习问题？'


def intent_context(context):
    # Cross-session retrieval content must not determine current-session intent.
    return {k: v for k, v in context.items() if k not in {
        'memory_candidates', 'related_knowledge', 'related_learning', 'continuation_candidates'}}


def handle(harness, sid, rid, rev, decision, last):
    data, run = harness._snapshot(sid, rid, rev)
    if last.get('operation') or set(decision.intents) & {'stop', 'pause', 'cancel', 'defer', 'queue'}:
        return False
    pending = data.get('dialogue_clarification')
    earlier = [m for m in data['messages'] if m['message_id'] not in run['input_ids']]
    if not pending and earlier and earlier[-1]['role'] == 'coach' and earlier[-1]['content'] == LEGACY_QUESTION:
        original = next((m for m in reversed(earlier[:-1]) if m['role'] == 'user'), None)
        if original:
            pending = dict(message_id=original['message_id'], content=original['content'], kind='resume_target', question=LEGACY_QUESTION)
    if decision.conversation_repair:
        identified = next((dict(content=m['content'], message_id=m['message_id']) for m in earlier
            if m['role'] == 'user' and m['message_id'] == decision.repair_target_message_id), None)
        # Recover the original question even after one extra legacy rephrase.
        # A model-provided ID must refer to an actual user message in this session.
        if not identified and not pending and len(earlier) >= 4 and earlier[-3]['content'] == LEGACY_QUESTION and earlier[-4]['role'] == 'user':
            identified = dict(content=earlier[-4]['content'], message_id=earlier[-4]['message_id'])
        original = identified or pending or next((dict(content=m['content'], message_id=m['message_id']) for m in reversed(earlier) if m['role'] == 'user'), None)
        with harness.store.transaction(sid, rid, rev) as current:
            active = current['runs'][rid]
            active.update(intent=decision.model_dump(), dialogue_only=True)
            if original:
                active['resolved_input'] = original['content']
            current.pop('dialogue_clarification', None)
        local = IntentDecision(intents=['question'], relation='continuation', scope='conversation', answer_only=True,
                               rationale='核对会话反馈，局部回答原问题，不修改学习状态。')
        harness._respond(sid, rid, rev, local,
            '用户指出了会话上下文判断问题。根据当前会话的实际消息核对并简短纠正此前不成立的前提，再回答 current_inputs 的原问题；没有证据不声称之前聊过。不要重复询问继续还是新话题，不评价知识掌握、不修改计划。', node='answer')
        return True
    # Uncertain state-changing requests need a concrete object before routing.
    if decision.relation == 'uncertain' and (set(decision.intents) & {'goal', 'confirm'} or decision.proposed_actions) and not decision.answer_only and not decision.clarification:
        harness._publish(sid, rid, rev, '你希望学习或操作的具体内容是什么？请提供对象，我再继续。')
        return True
    kind = decision.clarification_kind
    if kind == 'resume_target' and not decision.continuation_evidence:
        return False
    if not decision.clarification or (decision.clarification == LEGACY_QUESTION and not harness._task(data, run)):
        return False
    if pending and pending['kind'] == kind:
        # An operation remains unexecuted; explanations cannot confer consent.
        if kind == 'operation':
            harness._publish(sid, rid, rev, '目前还不能确定你指的操作对象，因此尚未执行。请提供具体的内容或版本。')
        else:
            with harness.store.transaction(sid, rid, rev) as current:
                current['runs'][rid].update(intent=decision.model_dump(), dialogue_only=True)
                current.pop('dialogue_clarification', None)
            local = decision.model_copy(update={'intents':['question'], 'scope':'conversation', 'answer_only':True, 'proposed_actions':[], 'clarification':''})
            harness._respond(sid, rid, rev, local,
                '上一轮已经澄清过，不能重复同一问题。结合原问题 '+pending['content']+' 先解释可以确定的部分；确实缺少具体对象时说明缺少什么及原因，不猜测对象、不执行操作。', node='answer')
        return True
    with harness.store.transaction(sid, rid, rev) as current:
        current['dialogue_clarification'] = dict(message_id=last['message_id'], content=last['content'],
            kind=kind, question=decision.clarification)
        current['runs'][rid]['intent'] = decision.model_dump()
    harness._publish(sid, rid, rev, decision.clarification, required={'type':'respond','prompt':decision.clarification,'options':[]})
    return True
