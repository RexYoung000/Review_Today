"""Learning-source search is supported; resource acquisition is not an errand."""
from agent_service.config import ROUTER_MODEL

REPLY = "这里主要帮助你理解知识和学习资料，不承接寻找下载资源或代为下载等事务。"
PROTECTED = {'stop', 'pause', 'cancel', 'defer', 'queue', 'confirm', 'reject'}


def handle(h, sid, rid, rev, decision, last):
    if (decision.resource_boundary == 'none' or last.get('operation')
            or decision.proposed_actions or decision.requested_mode
            or set(decision.intents) & PROTECTED):
        return False
    data, run = h._snapshot(sid, rid, rev)
    request = decision.resource_learning_request.strip()
    # Steering may contain multiple user messages; an excerpt must belong to
    # this Run's actual input, never an assistant promise or a recalled document.
    inputs = [m['content'] for m in data['messages'] if m['message_id'] in run['input_ids']]
    mixed = (decision.resource_boundary == 'mixed_learning' and request
             and any(request != text.strip() and h._explicit({'evidence': request}, text) for text in inputs))
    with h.store.transaction(sid, rid, rev) as current:
        active = current['runs'][rid]
        active.update(intent=decision.model_dump(), decision_input_ids=list(active['input_ids']),
            decision_mode=current['mode'], task_id=None, resource_scope_reply=True,
            dialogue_only=not mixed, activity_candidate=None, learning_concepts=[],
            search_state='not_called', verification_notice='', allowed_source_urls=[])
        h.store.event(current, active, 'intent_decided', '已识别请求范围', model=ROUTER_MODEL,
                      detail=decision.rationale, payload={'intent': decision.model_dump()})
        if mixed:
            active['resolved_input'] = request
    if not mixed:
        h._publish(sid, rid, rev, REPLY)
        return True
    local = decision.model_copy(update=dict(resource_boundary='none', resource_learning_request='',
        scope='conversation', workflow=None, intents=['question'], target_task_id='',
        target_description=request, relation='new_topic', proposed_actions=[], topic_closure=None,
        direct_teaching=False, answer_only=True, learning_goal_ready=False))
    with h.store.transaction(sid, rid, rev) as current:
        current['runs'][rid]['intent'] = local.model_dump()
    h._respond(sid, rid, rev, local,
        '先用一句话说明不承接寻找下载资源或代办；然后只回答 current_inputs 中明确的知识问题。'
        '边界只针对资源获取代办，不要把正常书目推荐或用于理解知识的来源检索也说成不支持。'
        '历史中的资源代办或助手承诺不是本轮授权，不提供获取渠道，不追问代办信息，不创建课程。', node='answer')
    return True
