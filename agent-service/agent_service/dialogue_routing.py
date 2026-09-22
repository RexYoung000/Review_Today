"""Clarification is a justified dialogue action, never an uncertain topic label."""
from agent_service.schemas import IntentDecision

LEGACY_QUESTION = '你希望继续刚才的内容，还是开始一个新的学习问题？'
LOCAL_QUESTIONS = {'question', 'followup', 'example', 'hint'}
POLICY_VERSION = 'dialogue-goals-1'


def current_learning_goal(data):
    """Legacy focus_goal may contain a chat question, not a learning commitment."""
    task = data.get('tasks', {}).get(data.get('active_task_id'))
    if task and task.get('status') not in {'cancelled', 'terminal_failed'}:
        return task['content']
    return (data.get('goal_clarification') or {}).get('goal', '')


def conversational_goal(decision):
    return (set(decision.intents) <= {'goal', 'social', 'greeting', 'thanks'}
            and 'goal' in decision.intents and decision.scope == 'conversation'
            and not (decision.workflow or decision.direct_teaching or decision.proposed_actions
                     or decision.requested_mode or decision.continuation_evidence or decision.answer_evidence)
            and decision.understanding == 'unknown'
            and decision.programming_boundary == decision.resource_boundary == 'none')


def ordinary_question(data, decision, last):
    """A workflow/scope suggestion alone cannot authorize a learning task."""
    substantive = set(decision.intents) - {'social', 'greeting', 'thanks'}
    return (data['mode'] == 'auto' and bool(substantive)
            and substantive <= LOCAL_QUESTIONS
            and not (last.get('operation') or decision.proposed_actions or decision.requested_mode
                     or decision.direct_teaching or decision.is_jd or decision.continuation_evidence)
            and decision.programming_boundary == 'none')


def normalize(data, decision, last):
    if conversational_goal(decision) and not last.get('operation') and not (
            decision.needs_verification or decision.refresh_sources or decision.cross_check_sources
            or decision.conversation_repair or decision.reply_feedback != 'none' or decision.topic_closure):
        # A goal label cannot overrule the LLM's explicit conversation-only scope.
        return decision.model_copy(update={'conversation_kind': 'background', 'intents': ['social'],
            'target_task_id': '', 'workflow': None, 'answer_only': True, 'session_tags': [], 'memory_selections': []})
    if ordinary_question(data, decision, last):
        return decision.model_copy(update={'scope': 'conversation', 'workflow': None, 'answer_only': True})
    return decision


def retire_misrouted_task(harness, sid, rid, rev):
    """Retire only proven conversation-only misroutes with no learning progress."""
    with harness.store.transaction(sid, rid, rev) as data:
        run = data['runs'][rid]
        task = harness._task(data, run)
        if not task or task['stage'] != 'clarify_goal' or task['status'] != 'awaiting_user':
            return
        context = task['context']
        if any(context.get(k) for k in ('learning_plan', 'sources', 'draft', 'check_question', 'learning_outcome')):
            return
        origin = data['runs'].get(context.get('origin_run_id'), {})
        raw = origin.get('intent')
        original = next((m for m in data['messages'] if m['message_id'] == task['client_message_id']), None)
        if not raw or not original or origin.get('decision_mode') != 'auto':
            return
        prior = IntentDecision.model_validate(raw)
        location_only = (conversational_goal(prior) and origin.get('resolved_input') == task['content']
                         and (original.get('operation') or {}).get('kind') == 'continue_session')
        if not (ordinary_question({'mode': 'auto'}, prior, original) or location_only):
            return
        task.update(status='cancelled', stage='routing_corrected', required_action=None,
                    user_summary='已取消误建的学习任务')
        context['routing_corrected'] = True
        harness._project_event(data, run, task)
        if data.get('active_task_id') == task['task_id']:
            data['active_task_id'] = None
            if data.get('focus_goal') in {task['content'], original['content']}:
                data['focus_goal'] = ''
        if run.get('task_id') == task['task_id']:
            run['task_id'] = None


def intent_context(context):
    # Cross-session retrieval content must not determine current-session intent.
    return {k: v for k, v in context.items() if k not in {
        'memory_candidates', 'related_knowledge', 'related_learning', 'continuation_candidates'}}


def handle(harness, sid, rid, rev, decision, last):
    data, run = harness._snapshot(sid, rid, rev)
    if last.get('operation') or set(decision.intents) & {'stop', 'pause', 'cancel', 'defer', 'queue'}:
        return False
    if (decision.reply_feedback == 'response_only' and not decision.conversation_repair
            and set(decision.intents) <= {'question', 'followup', 'correction', 'social', 'greeting', 'thanks'}
            and not (decision.proposed_actions or decision.requested_mode or decision.continuation_evidence
                     or decision.direct_teaching or decision.clarification or decision.is_jd
                     or decision.needs_verification or decision.refresh_sources or decision.cross_check_sources)
            and decision.programming_boundary == decision.resource_boundary == 'none'):
        from agent_service.social_dialogue import bounded_reply
        reply = bounded_reply(decision.light_reply, '抱歉，刚才的回应没接住你的意思。我会回应你问的内容，避免机械重复。')
        with harness.store.transaction(sid, rid, rev) as current:
            active = current['runs'][rid]
            active.update(intent=decision.model_dump(), decision_input_ids=list(active['input_ids']),
                          decision_mode=current['mode'], dialogue_only=True, task_id=None,
                          reply_feedback_handled=True, search_state='not_called',
                          learning_concepts=[], activity_candidate=None)
            harness.store.event(current, active, 'intent_decided', '已接收回复反馈',
                                detail=decision.rationale, payload={'intent': decision.model_dump()})
        harness._publish(sid, rid, rev, reply)
        return True
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
        retire_misrouted_task(harness, sid, rid, rev)
        with harness.store.transaction(sid, rid, rev) as current:
            active = current['runs'][rid]
            active.update(intent=decision.model_dump(), dialogue_only=True)
            if original:
                active['resolved_input'] = original['content']
            current.pop('dialogue_clarification', None)
        local = IntentDecision(intents=['question'], relation='continuation', scope='conversation', answer_only=True,
                               rationale='核对会话反馈，局部回答原问题，不修改学习状态。')
        harness._respond(sid, rid, rev, local,
            '用户指出了会话上下文或流程判断问题。先用一句话纠正误解，再直接回答 current_inputs 的原问题；普通概念简短说明定义、作用和一个例子，正文尽量控制在 400 个汉字内。无领域依据先区分常见含义，不能替用户认定领域。不要再问学习目标或继续/新话题，不评价知识掌握、不修改真实学习计划。', node='answer')
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
