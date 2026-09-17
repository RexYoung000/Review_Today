"""Runtime scope survives dialogue projection; tools recheck before dispatch."""
from agent_service.call_errors import WebToolError
from agent_service.web_privacy import sensitive_material, require_public_query, require_public_url

BOUNDARIES = ('resource_boundary', 'programming_boundary')


def remember(h, sid, rid, rev, decision):
    with h.store.transaction(sid, rid, rev) as data:
        run = data['runs'][rid]
        previous = run.get('request_scope', {})
        # A retry of the isolated learning part must not erase the original scope.
        if previous.get('input_ids') != run['input_ids'] or any(getattr(decision, b) != 'none' for b in BOUNDARIES):
            run['request_scope'] = dict(input_ids=list(run['input_ids']),
                **{b: getattr(decision, b) for b in BOUNDARIES})


def allows_answer(run):
    policy = run.get('request_scope') or run.get('intent') or {}
    if 'input_ids' in policy and policy['input_ids'] != run['input_ids']:
        return False
    boundaries = [policy.get(b, 'none') for b in BOUNDARIES if policy.get(b, 'none') != 'none']
    if not boundaries:
        return True
    return (all(b == 'mixed_learning' for b in boundaries)
            and bool(policy.get('learning_request'))
            and policy['learning_request'] == run.get('resolved_input'))


def check_web(h, sid, rid, rev, value, *, operation, purpose='answer'):
    data, run = h._snapshot(sid, rid, rev)
    if purpose == 'confirmed_capture':
        # This exception is bound to a real save already admitted by _save_memory.
        offer = data.get('capture_offers', {}).get(run.get('capture_offer_id'), {})
        task = data['tasks'].get(offer.get('save_task_id'), {})
        if (offer.get('status') != 'saving' or not task
                or task.get('context', {}).get('origin_run_id') != rid):
            raise WebToolError('SCOPE_BLOCKED')
        texts = [(data.get('draft') or {}).get('content', ''), task.get('content', '')]
    else:
        if not allows_answer(run):
            raise WebToolError('SCOPE_BLOCKED')
        texts = [m['content'] for m in data['messages'] if m['message_id'] in run['input_ids']]
        if (run.get('intent') or {}).get('relation') != 'new_topic':
            task = h._task(data, run)
            prior = task['context'] if task else data.get('teaching_context', {})
            texts += [s.get('content', '') for s in prior.get('sources', []) if s.get('type') == 'user_material']
    if any(sensitive_material(text) for text in texts):
        raise WebToolError('PRIVATE_INPUT')
    if operation == 'read':
        require_public_url(value)
    else:
        require_public_query(value)
