"""Handle existing resource/development scope without granting attached errands."""
from agent_service.config import ROUTER_MODEL

REPLY = "这里主要帮助你理解知识和学习资料，不承接寻找下载资源或代为下载等事务。"
PROTECTED = {'stop', 'pause', 'cancel', 'defer', 'queue', 'confirm', 'reject'}
BARE_CONTROLS = {'晚点再学', '算了晚点再学吧', '先不学了', '今天不学了', '稍后再学',
                 '不要保存', '不保存', '暂不保存', '先不保存', '好的', '确认', '排队'}


def normalize(data, decision, last):
    """A bare continuation inherits the latest blocked request, not an old goal."""
    text = last['content'].strip().rstrip('。！!').lower()
    if text not in {'继续', '继续吧', '接着', '那继续', 'continue', 'go on'} or last.get('operation'):
        return decision
    previous = next((m for m in reversed(data['messages']) if m['role'] == 'coach'), {})
    run = data['runs'].get(previous.get('run_id'), {})
    boundary = (run.get('request_scope') or run.get('intent') or {}).get('resource_boundary', 'none')
    if run.get('resource_scope_reply') and boundary in {'resource_delivery', 'capability_question'}:
        return decision.model_copy(update=dict(resource_boundary='resource_delivery',
            resource_learning_request='', proposed_actions=[], requested_mode=None,
            intents=['continue'], rationale='本轮仅要求继续，承接最近的资源代办请求；旧目标不扩大范围。'))
    return decision


def handle(h, sid, rid, rev, decision, last):
    from agent_service.request_scope import allows_answer
    data, run = h._snapshot(sid, rid, rev)
    policy = run.get('request_scope', {})
    if (decision.resource_boundary == decision.programming_boundary == 'none'
            and (run.get('resource_scope_reply') or run.get('programming_scope_reply'))
            and policy.get('learning_request') and allows_answer(run)):
        # Retry the already isolated knowledge answer through the same path;
        # generic new-topic routing would otherwise create a Session prompt.
        request = policy['learning_request']
        decision = decision.model_copy(update={b: policy.get(b, 'none') for b in
            ('resource_boundary', 'programming_boundary')} | dict(
                resource_learning_request=request, programming_learning_request=request))
    programming = decision.resource_boundary == 'none' and decision.programming_boundary != 'none'
    boundary = decision.programming_boundary if programming else decision.resource_boundary
    intents = set(decision.intents)
    bare = ''.join(c for c in last['content'].strip() if c not in '，。！？,!? ')
    if (boundary == 'none' or last.get('operation')
            or intents & {'stop', 'pause', 'cancel'}
            or programming and intents == {'defer'}
            or (bare in BARE_CONTROLS and intents <= PROTECTED
                and not decision.proposed_actions and not decision.requested_mode)):
        return False
    if 'queue' in intents and len(run['input_ids']) > 1:
        return False  # Split queued input first; each resulting run is checked again.
    # An explicit control can act on an existing object, but cannot authorize the
    # accompanying errand. New goals/source selection are not errand controls.
    controls = [op for op in decision.proposed_actions
                if op.kind in {'set_mode', 'save'} or op.disposition == 'reject']
    if controls:
        controlled = decision.model_copy(update={'proposed_actions': controls,
            'intents': [i for i in decision.intents if i not in {'followup', 'hint', 'example', 'correction'}] or ['confirm']})
        h._apply_operations(sid, rid, rev, controlled, last)
        data, run = h._snapshot(sid, rid, rev)
    request = (decision.programming_learning_request if programming else decision.resource_learning_request).strip()
    # Steering may contain multiple user messages; an excerpt must belong to
    # this Run's actual input, never an assistant promise or a recalled document.
    inputs = [m['content'] for m in data['messages'] if m['message_id'] in run['input_ids']]
    mixed = (boundary == 'mixed_learning' and request
             and any(request != text.strip() and h._explicit({'evidence': request}, text) for text in inputs))
    with h.store.transaction(sid, rid, rev) as current:
        active = current['runs'][rid]
        active.update(intent=decision.model_dump(), decision_input_ids=list(active['input_ids']),
            decision_mode=current['mode'], task_id=None,
            dialogue_only=not mixed, activity_candidate=None, learning_concepts=[],
            search_state='not_called', verification_notice='', allowed_source_urls=[])
        active['programming_scope_reply' if programming else 'resource_scope_reply'] = True
        h.store.event(current, active, 'intent_decided', '已识别请求范围', model=ROUTER_MODEL,
                      detail=decision.rationale, payload={'intent': decision.model_dump()})
        if mixed:
            active['resolved_input'] = request
            active.setdefault('request_scope', {})['learning_request'] = request
    if not mixed:
        reply = REPLY
        if programming:
            reply = ('我是 Review Today 学习教练，可以帮助你理解 coding 相关的知识，比如编程概念、代码逻辑和背后的原理。'
                if boundary == 'capability_question' else
                'Review Today 主要帮助你学习和理解知识，不承接项目代做、修改仓库、实际运行调试或测试、部署上线。可以帮你理解相关代码、报错原理或实现思路。')
        h._publish(sid, rid, rev, reply)
        return True
    local = decision.model_copy(update=dict(resource_boundary='none', resource_learning_request='',
        programming_boundary='none', programming_learning_request='',
        scope='conversation', workflow=None, intents=['question'], target_task_id='',
        target_description=request, relation='new_topic', proposed_actions=[], topic_closure=None,
        direct_teaching=False, answer_only=True, learning_goal_ready=False, requested_mode=None,
        public_search_query=''))
    with h.store.transaction(sid, rid, rev) as current:
        current['runs'][rid]['intent'] = local.model_dump()
    instruction = ('先简短说明不执行代做项目、改仓库、运行调试或部署等开发操作；再仅解释 current_inputs 中用户明确提出的学习问题，不创建课程或开发交付物。'
        if programming else '先用一句话说明不承接寻找下载资源或代办；然后只回答 current_inputs 中明确的知识问题。'
        '边界只针对资源获取代办，不要把正常书目推荐或用于理解知识的来源检索也说成不支持。'
        '历史中的资源代办或助手承诺不是本轮授权，不提供获取渠道，不追问代办信息，不创建课程。')
    h._respond(sid, rid, rev, local, instruction, node='answer')
    return True
