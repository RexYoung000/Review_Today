"""Topic closure is a versioned Harness decision, never streamed model prose.

Offers retain immutable source snapshots independently of the current draft.
Only an explicit bound action can save one; continuation is consumed atomically.
"""
from copy import deepcopy
import hashlib
import uuid

from agent_service.learning_memory import merge_references
from agent_service.learning_progress import current_step, record_understanding, advance


def offers(data):
    return data.setdefault('capture_offers', {})


def emit(h, data, run, offer):
    h.store.event(data, run, 'capture_offer', '知识收尾状态已更新', payload={'capture_offer': public(offer)})


def public(offer):
    return {k: deepcopy(offer[k]) for k in ('id', 'version', 'title', 'anchor_message_id', 'status', 'next_request', 'continuation_consumed', 'save_task_id', 'action_input_id', 'error', 'knowledge_ids') if k in offer}


def interrupt(data):
    # New text supersedes deferred automatic teaching, but not already saved data.
    for offer in offers(data).values():
        offer['continuation_consumed'] = True
        if offer['status'] == 'offered':
            offer['status'] = 'dismissed'


def invalidate(h, data, run):
    task = h._task(data, run)
    step = current_step(task) if task else None
    last_answer = next((m for m in reversed(data['messages']) if m['role'] == 'coach'), {})
    for offer in offers(data).values():
        matches = (step and offer.get('step_id') == step['id']) or last_answer.get('message_id') in offer.get('message_ids', [])
        if matches and offer['status'] in {'offered', 'dismissed', 'deferred', 'failed'}:
            offer.update(status='invalidated', continuation_consumed=True, error='内容已修正，请在新的话题收尾处确认。')
            emit(h, data, run, offer)


def maybe_offer(h, sid, rid, rev, decision, last):
    closure = decision.topic_closure
    if not closure or last.get('operation') or decision.proposed_actions:
        return False
    if set(decision.intents) & {'defer', 'stop', 'pause', 'cancel', 'reject', 'correction', 'followup', 'hint', 'example', 'skip_check'}:
        return False
    if not h._explicit({'evidence': closure.evidence}, last['content']):
        return False
    with h.store.transaction(sid, rid, rev) as data:
        run = data['runs'][rid]
        if run.get('capture_continuation'):
            return False
        task = data['tasks'].get(decision.target_task_id or data.get('active_task_id'))
        ctx = (task or {}).get('context', {})
        understood = decision.understanding if decision.understanding == 'self_reported' else ctx.get('understanding', 'unknown')
        if understood == 'unknown' or (ctx.get('requires_mastery') and not ctx.get('transfer_passed')):
            return False
        ids = list(dict.fromkeys(closure.message_ids))
        messages = [m for m in data['messages'] if m['message_id'] in ids and m['role'] == 'coach']
        if not ids or len(messages) != len(ids):
            return False
        source_runs = [data['runs'].get(m.get('run_id'), {}) for m in messages]
        if any(r.get('status') != 'completed' or not h._memory_run_valid(r) for r in source_runs):
            return False
        # A closing turn can only refer to the current completed learning segment.
        latest = next((m for m in reversed(data['messages']) if m['role'] == 'coach'), None)
        if not latest or latest['message_id'] not in ids:
            return False
        mastered_closure = bool(ctx.get('transfer_passed') and ctx.get('draft') and task and task['status'] == 'completed' and all(r.get('task_id') == task['task_id'] for r in source_runs))
        if not mastered_closure and any(not r.get('learning_concepts') and r.get('activity_kind') not in {'knowledge_answer', 'lesson_step'} for r in source_runs):
            return False
        positions = {m['message_id']: i for i, m in enumerate(data['messages'])}
        boundary = max((positions.get(mid, -1) for o in offers(data).values() for mid in o.get('message_ids', [])), default=-1)
        if any(positions[mid] <= boundary for mid in ids):
            return False
        content = ctx['draft']['content'] if mastered_closure else '\n\n'.join(m['content'] for m in messages)
        key = hashlib.sha256(('\n'.join(ids) + content).encode()).hexdigest()
        if any(o.get('source_key') == key for o in offers(data).values()):
            return False
        next_request = closure.next_request.strip()
        if next_request and (next_request not in last['content'] or not h._explicit({'evidence': next_request}, last['content'])):
            next_request = ''
        identity = str(uuid.uuid4())
        step = current_step(task) if task else None
        references = merge_references(*(r.get('memory_references', []) for r in source_runs), ctx.get('draft', {}).get('memory_references', []) if mastered_closure else [])
        source_map = {(s['source_id'], s.get('version', 1)): deepcopy(s) for r in source_runs for s in r.get('answer_sources', [])}
        sources = list(source_map.values()) or deepcopy(ctx.get('sources', []))
        draft = dict(id=identity, version=1, content=content, understanding=understood,
                     source_type=source_runs[-1].get('answer_source_type', ctx.get('source_type', 'agent_generated')), memory_references=references,
                     public_search_query=ctx.get('public_search_query', ''))
        offer = dict(id=identity, version=1, title=closure.title, anchor_message_id=last['message_id'],
                     message_ids=ids, source_key=key, draft=draft, sources=sources,
                     origin_task_id=(task or {}).get('task_id'), step_id=(step or {}).get('id'),
                     requires_mastery=ctx.get('requires_mastery', False), transfer_passed=ctx.get('transfer_passed', False),
                     lifecycle_revision=data.get('lifecycle_revision', 0), status='offered',
                     next_request=next_request, continuation_consumed=False, error='', knowledge_ids=[])
        offers(data)[identity] = offer
        if task and decision.understanding == 'self_reported' and ctx.get('understanding') != 'verified':
            ctx['understanding'] = 'self_reported'
            record_understanding(task, 'self_reported')
        data['pending'] = None if (data.get('pending') or {}).get('kind') == 'save' else data.get('pending')
        run.update(intent=decision.model_dump(), decision_input_ids=list(run['input_ids']), decision_mode=data['mode'], execution_complete=True)
        emit(h, data, run, offer)
    return True


def queue_next(h, data, offer):
    if offer.get('save_task_id') and data.get('active_task_id') == offer['save_task_id']:
        data['active_task_id'] = offer.get('resume_task_id', offer.get('origin_task_id'))
    if offer.get('continuation_consumed'):
        return
    offer['continuation_consumed'] = True
    if not offer.get('next_request') or data.get('status') != 'active' or data.get('paused') or data.get('lifecycle_revision', 0) != offer['lifecycle_revision']:
        return
    task = data['tasks'].get(offer.get('origin_task_id'))
    if task and (current_step(task) or {}).get('id') == offer.get('step_id'):
        advance(task)
    from agent_service.conversation import _new_run
    run = _new_run(data['session_id'], offer['anchor_message_id'], 'queued')
    run.update(resolved_input=offer['next_request'], capture_continuation=True,
               lifecycle_revision=data.get('lifecycle_revision', 0), task_id=offer.get('origin_task_id'))
    data['runs'][run['run_id']] = run
    offer['continuation_run_id'] = run['run_id']
    data['active_task_id'] = offer.get('origin_task_id')
    h.store.event(data, run, 'queued', '继续刚才提出的下一话题')


def handle_action(h, sid, rid, rev, last):
    action = last.get('operation') or {}
    if action.get('kind') not in {'capture_save', 'capture_later', 'capture_skip'}:
        return False
    with h.store.transaction(sid, rid, rev) as data:
        run = data['runs'][rid]
        offer = offers(data).get(action['target_id'])
        if not offer or action['version'] != offer['version']:
            raise ValueError('RT.CAPTURE.STALE_OFFER')
        if offer['status'] in {'saved', 'skipped', 'saving'}:
            return True
        if offer['status'] == 'invalidated' or not h.store.memory_valid(offer['draft'].get('memory_references', [])):
            offer.update(status='invalidated', continuation_consumed=True, error='关联内容已变化，请在新的话题收尾处确认。')
            emit(h, data, run, offer)
            return True
        if action['kind'] == 'capture_later' and offer['status'] == 'deferred':
            return True
        if run.get('paused_entry'):
            data['paused'] = False  # explicit retry/skip resumes only this user-selected operation
        if action['kind'] != 'capture_save':
            offer['status'] = 'deferred' if action['kind'] == 'capture_later' else 'skipped'
            queue_next(h, data, offer)
            emit(h, data, run, offer)
            return True
        task = data['tasks'].get(offer.get('origin_task_id'))
        if task and task['context'].get('memory_invalidated'):
            offer.update(status='invalidated', continuation_consumed=True, error='关联内容已变化，请在新的话题收尾处确认。')
            emit(h, data, run, offer)
            return True
        offer.update(status='saving', action_input_id=last['message_id'], error='', resume_task_id=data.get('active_task_id'))
        run.update(task_id=offer.get('origin_task_id'), capture_offer_id=offer['id'])
        data['draft'] = deepcopy(offer['draft'])
        data['pending'] = dict(kind='save', target_id=offer['id'], version=offer['version'])
        emit(h, data, run, offer)
    from agent_service.schemas import IntentDecision
    decision = IntentDecision(intents=['confirm'], relation='continuation', scope='conversation', rationale='用户确认当前话题版本')
    h._save_memory(sid, rid, rev, decision)
    with h.store.transaction(sid, rid, rev) as data:
        run = data['runs'][rid]; offer = offers(data)[action['target_id']]
        task = h._task(data, run)
        if task and task['status'] == 'committing':
            offer['save_task_id'] = task['task_id']
            task['context']['capture_offer_id'] = offer['id']
        else:
            offer.update(status='failed', error='尚未保存，请检查理解条件或内容核验结果。')
        if offer['status'] == 'failed':
            data['active_task_id'] = offer.get('resume_task_id', offer.get('origin_task_id'))
        emit(h, data, run, offer)
    return True


def failed(h, data, run, error):
    offer = offers(data).get(run.get('capture_offer_id'))
    if offer and offer['status'] == 'saving':
        offer.update(status='failed', error=error)
        data['active_task_id'] = offer.get('resume_task_id', offer.get('origin_task_id'))
        emit(h, data, run, offer)


def acknowledged(h, data, task, knowledge_ids):
    offer = offers(data).get(task['context'].get('capture_offer_id'))
    if not offer or offer['status'] == 'saved':
        return False
    offer.update(status='saved', knowledge_ids=knowledge_ids, error='')
    queue_next(h, data, offer)
    origin = data['runs'].get(task['context'].get('origin_run_id'))
    if origin:
        emit(h, data, origin, offer)
    return bool(offer.get('continuation_run_id'))


def cancel_unclaimed(h, data, task, run):
    offer = offers(data).get(task['context'].get('capture_offer_id'))
    if offer and offer['status'] == 'saving' and not task['context'].get('commit_claimed'):
        offer.update(status='failed', continuation_consumed=True, error='录入已暂停，内容尚未保存。')
        data['active_task_id'] = offer.get('resume_task_id', offer.get('origin_task_id'))
        emit(h, data, run, offer)


def adopt_explicit(h, data, run, draft, task):
    """An already-authorized direct save also gets an inline result, without an offer prompt."""
    existing = offers(data).get(run.get('capture_offer_id'))
    if existing:
        return existing
    identity = str(uuid.uuid5(uuid.UUID(data['session_id']), f"explicit:{draft['id']}:{draft['version']}"))
    offer = offers(data).get(identity)
    if not offer:
        ctx = (task or {}).get('context', {})
        latest = next((m for m in reversed(data['messages']) if m['role'] == 'coach'), None)
        offer = dict(id=identity, version=draft['version'], title='本次确认的知识',
                     anchor_message_id=run['input_ids'][-1], message_ids=[latest['message_id']] if latest else [], draft=deepcopy(draft),
                     sources=deepcopy(ctx.get('sources', [])), origin_task_id=(task or {}).get('task_id'),
                     lifecycle_revision=data.get('lifecycle_revision', 0), status='saving', next_request='',
                     continuation_consumed=True, error='', knowledge_ids=[])
        offers(data)[identity] = offer
    if offer['status'] != 'saved':
        offer.update(status='saving', action_input_id=run['input_ids'][-1], error='')
    run['capture_offer_id'] = identity
    emit(h, data, run, offer)
    return offer
