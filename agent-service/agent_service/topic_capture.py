"""Topic closure is a versioned Harness decision, never streamed model prose.

Offers retain immutable source snapshots independently of the current draft.
Only an explicit bound action can save one; continuation is consumed atomically.
"""
from copy import deepcopy
import hashlib
import uuid

from agent_service.learning_memory import merge_references
from agent_service.learning_progress import current_step, record_understanding, advance
from agent_service import capture_preview

LIMITED_COVERAGE_NOTE = '部分旧题反馈未能与讲解核对，暂仅整理已确认的讲解；可先补讲再完整整理。'


def source_transparent(run):
    """These local explanations do not replace the current knowledge anchor."""
    if run.get('knowledge_status_reply') or run.get('reply_feedback_handled') and run.get('dialogue_only'):
        return True
    intent = run.get('intent') or {}
    intents = set(intent.get('intents', []))
    # Before dedicated card status existed, those questions went through the
    # product-information route. Recognize that complete, side-effect-free
    # contract; a capabilities label alone must never skip a real topic.
    return bool(run.get('status') == 'completed' and not run.get('task_id')
                and intent.get('reply_purpose') == 'product_information'
                and intent.get('scope') == 'conversation' and intent.get('relation') == 'continuation'
                and 'capabilities' in intents and intents <= {'capabilities', 'greeting', 'thanks'}
                and not any(run.get(key) for key in ('activity_kind', 'activity_candidate', 'learning_concepts',
                    'teaching_step_id', 'teaching_plan_version', 'evaluated_step_id', 'evaluation_message_id',
                    'capture_offer_id', 'capture_continuation'))
                and 'evaluated_binding' not in run
                and not any(intent.get(key) for key in ('workflow', 'proposed_actions', 'topic_closure',
                    'target_task_id', 'target_description', 'direct_teaching',
                    'answer_evidence', 'continuation_evidence', 'requested_mode', 'conversation_repair',
                    'needs_verification', 'refresh_sources', 'cross_check_sources', 'is_jd')))


def offers(data):
    return data.setdefault('capture_offers', {})


def emit(h, data, run, offer):
    h.store.event(data, run, 'capture_offer', '知识收尾状态已更新', payload={'capture_offer': public(offer)})


def public(offer):
    value = {k: deepcopy(offer[k]) for k in ('id', 'version', 'title', 'anchor_message_id', 'status', 'next_request', 'continuation_consumed', 'save_task_id', 'action_input_id', 'error', 'knowledge_ids', 'trigger', 'scope_summary') if k in offer}
    value.update(capture_preview.public(offer))
    return value


def interrupt(data):
    # New text supersedes deferred automatic teaching, but not already saved data.
    for offer in offers(data).values():
        offer['continuation_consumed'] = True
        if offer['status'] == 'offered' and offer.get('trigger') != 'verified_check':
            offer['status'] = 'dismissed'


def invalidate(h, data, run):
    task = h._task(data, run)
    step = current_step(task) if task else None
    last_answer = next((m for m in reversed(data['messages']) if m['role'] == 'coach'), {})
    for offer in offers(data).values():
        matches = (step and offer.get('step_id') == step['id']) or last_answer.get('message_id') in offer.get('message_ids', [])
        if offer.get('trigger') == 'verified_check':
            matches = last_answer.get('message_id') in offer.get('message_ids', [])
        if matches and offer['status'] in {'offered', 'dismissed', 'deferred', 'failed'}:
            if offer.get('trigger') == 'verified_check':
                offer.update(status_before_correction=offer['status'], correction_pending=True,
                             correction_run_id=run['run_id'],
                             version=offer['version'] + 1)
                capture_preview.clear(offer)
            offer.update(status='invalidated', continuation_consumed=True, error='内容已修正，请在新的话题收尾处确认。')
            if offer.get('trigger') == 'verified_check':
                offer['error'] = '正在核对纠正后的保存范围，完成前暂不能录入。'
            emit(h, data, run, offer)


def _source_run_valid(h, data, message, run):
    if (run.get('status') != 'completed' or not h._memory_run_valid(run)
            or run.get('session_id', data['session_id']) != data['session_id']):
        return False
    # Retained events bind a delivered message to its actual run revision.
    event = next((event for event in reversed(data.get('events', []))
                  if (event.get('message') or {}).get('message_id') == message['message_id']), None)
    return not event or event.get('revision') == run.get('revision')


def _evaluation_for(task, run):
    """Require a real evaluation record; an `answer` routing label is not one."""
    ctx = (task or {}).get('context', {})
    binding = run.get('evaluated_binding')
    if not binding or binding.get('plan_version') != (ctx.get('learning_plan') or {}).get('version'):
        return None
    answer_id = run.get('evaluation_message_id')
    if answer_id not in run.get('input_ids', []):
        return None
    return next((entry.get('evaluation') for entry in reversed(ctx.get('practice', []))
                 if entry.get('message_id') == answer_id and entry.get('run_id') == run.get('run_id')
                 and entry.get('revision') == run.get('revision') and entry.get('binding') == binding
                 and entry.get('evaluation')), None)


def collect_source(h, data, task=None, *, message_ids=None, include_captured=False):
    """Freeze the current learning segment without treating user answers as facts.

    New runs use explicit step/version bindings. Old completed teaching can be
    recovered from the step's delivered-message list, but unbound evaluations
    cannot silently become authoritative corrections or mastery evidence.
    """
    ctx = (task or {}).get('context', {})
    if ctx.get('memory_invalidated') or (task and task.get('session_id') != data['session_id']):
        return None
    task_id = (task or {}).get('task_id')
    step = current_step(task) if task else None
    plan = ctx.get('learning_plan') or {}
    step_id = (step or {}).get('id')
    mastered = bool(ctx.get('transfer_passed') and ctx.get('draft') and task and task.get('status') == 'completed')
    messages = data.get('messages', [])
    positions = {message['message_id']: index for index, message in enumerate(messages)}
    coaches = [message for message in messages if message.get('role') == 'coach'
               and not source_transparent(data['runs'].get(message.get('run_id'), {}))]
    if not coaches:
        return None
    latest = coaches[-1]
    requested = list(dict.fromkeys(message_ids or [latest['message_id']]))
    if latest['message_id'] not in requested:
        return None
    # A model may select only the last feedback message. Reconstruct its actual
    # teaching source, rather than dropping it or using the feedback alone.
    boundary = max((positions.get(mid, -1) for offer in data.get('capture_offers', {}).values()
                    if offer.get('trigger') != 'verified_check'
                    for mid in offer.get('message_ids', []) + offer.get('draft', {}).get('excluded_unbound_feedback_ids', [])), default=-1)
    if include_captured:
        matching = next((offer for offer in reversed(list(data.get('capture_offers', {}).values()))
                         if latest['message_id'] in offer.get('message_ids', []) + offer.get('draft', {}).get('excluded_unbound_feedback_ids', [])
                         and offer.get('origin_task_id') == task_id), None)
        if matching:
            draft = matching.get('draft') or {}
            if (matching.get('status') == 'invalidated' or draft.get('invalidated')
                    or matching.get('lifecycle_revision', 0) != data.get('lifecycle_revision', 0)
                    or not h.store.memory_valid(draft.get('memory_references', []))):
                return None
            if set(requested) <= set(matching.get('message_ids', []) + draft.get('excluded_unbound_feedback_ids', [])):
                return dict(content=draft['content'], message_ids=list(matching['message_ids']),
                            memory_references=deepcopy(draft.get('memory_references', [])),
                            sources=deepcopy(matching.get('sources', [])), source_type=draft.get('source_type', 'agent_generated'),
                            draft_id=draft['id'], draft_version=draft['version'], source_key=matching.get('source_key', ''),
                            excluded_unbound_feedback_ids=list(draft.get('excluded_unbound_feedback_ids', [])))
    selected, source_runs, taught, unbound_feedback = [], [], False, []
    for message in coaches:
        if positions[message['message_id']] <= boundary:
            continue
        run = data['runs'].get(message.get('run_id'), {})
        owner = run.get('task_id')
        if owner != task_id:
            # Never traverse another task to recover an older segment.
            selected, source_runs, taught, unbound_feedback = [], [], False, []
            continue
        if not _source_run_valid(h, data, message, run):
            selected, source_runs, taught, unbound_feedback = [], [], False, []
            continue
        if (run.get('intent') or {}).get('relation') == 'new_topic':
            selected, source_runs, taught, unbound_feedback = [], [], False, []
        evaluation = _evaluation_for(task, run) if task else None
        bound_step = run.get('teaching_step_id') or (run.get('evaluated_binding') or {}).get('step_id')
        bound_version = run.get('teaching_plan_version') if run.get('teaching_step_id') else (run.get('evaluated_binding') or {}).get('plan_version')
        if not mastered and bound_step and (bound_step != step_id or bound_version != plan.get('version')):
            selected, source_runs, taught, unbound_feedback = [], [], False, []
            continue
        teaching = bool(run.get('learning_concepts') or run.get('activity_kind') in {'knowledge_answer', 'lesson_step'})
        continuing_explanation = (taught and (run.get('intent') or {}).get('relation') == 'continuation'
                                  and set((run.get('intent') or {}).get('intents', [])) & {'question', 'followup', 'example', 'correction'})
        if teaching and task and step and not bound_step and message['message_id'] not in step.get('message_ids', []) and not continuing_explanation:
            # Legacy step membership is only a conservative teaching fallback.
            teaching = False
        if not teaching and not evaluation:
            # A legacy grading turn may anchor the user's explicit closure,
            # but its unbound feedback is excluded from the factual source.
            if taught and 'answer' in (run.get('intent') or {}).get('intents', []) and any(
                    entry.get('message_id') in run.get('input_ids', []) and entry.get('evaluation')
                    for entry in ctx.get('practice', [])):
                unbound_feedback.append(message['message_id'])
            continue
        if evaluation and not (taught or mastered):
            continue
        if teaching:
            taught = True
        selected.append(message)
        source_runs.append(run)
    ids = [message['message_id'] for message in selected]
    allowed_anchors = set(ids + unbound_feedback)
    if not ids or not set(requested) <= allowed_anchors or latest['message_id'] not in allowed_anchors:
        return None
    if mastered:
        # Problem-solving keeps its independently checked reference draft. The
        # answer's raw wording and generic success feedback are not new facts.
        content = ctx['draft']['content']
    else:
        parts = []
        for message, run in zip(selected, source_runs):
            if _evaluation_for(task, run):
                feedback = _evaluation_for(task, run).get('feedback', '').strip()
                if feedback:
                    parts.append('答题反馈中的解释与纠正（不把用户答案或评分描述当作知识事实）：\n' + feedback)
            else:
                parts.append(message['content'])
        content = '\n\n'.join(parts)
    if not content.strip():
        return None
    references = merge_references(*(run.get('memory_references', []) for run in source_runs),
                                  ctx.get('draft', {}).get('memory_references', []) if mastered else [])
    sources = {(source['source_id'], source.get('version', 1)): deepcopy(source)
               for run in source_runs for source in run.get('answer_sources', [])}
    return dict(content=content, message_ids=ids, memory_references=references,
                sources=list(sources.values()) or deepcopy(ctx.get('sources', [])),
                source_type=source_runs[-1].get('answer_source_type', ctx.get('source_type', 'agent_generated')),
                excluded_unbound_feedback_ids=unbound_feedback,
                source_key=hashlib.sha256(('\n'.join(ids) + content).encode()).hexdigest())


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
        source = collect_source(h, data, task, message_ids=closure.message_ids)
        if not source:
            return False
        ids, content, key = source['message_ids'], source['content'], source['source_key']
        if any(o.get('source_key') == key for o in offers(data).values()):
            return False
        next_request = closure.next_request.strip()
        if next_request and (next_request not in last['content'] or not h._explicit({'evidence': next_request}, last['content'])):
            next_request = ''
        identity = str(uuid.uuid4())
        step = current_step(task) if task else None
        draft = dict(id=identity, version=1, content=content, understanding=understood,
                     source_type=source['source_type'], memory_references=source['memory_references'],
                     source_message_ids=ids, answer_sources=source['sources'],
                     excluded_unbound_feedback_ids=source.get('excluded_unbound_feedback_ids', []),
                     public_search_query=ctx.get('public_search_query', ''))
        limited = bool(draft['excluded_unbound_feedback_ids'])
        offer = dict(id=identity, version=1, title=closure.title + ('（暂仅已确认讲解，旧题反馈待核对）' if limited else ''), anchor_message_id=last['message_id'],
                     message_ids=ids, source_key=key, draft=draft, sources=source['sources'],
                     coverage_note=LIMITED_COVERAGE_NOTE if limited else '',
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
    if offer.get('trigger') == 'verified_check' or offer.get('continuation_consumed'):
        return
    offer['continuation_consumed'] = True
    if not offer.get('next_request') or data.get('status') != 'active' or data.get('paused') or data.get('lifecycle_revision', 0) != offer['lifecycle_revision']:
        return
    task = data['tasks'].get(offer.get('origin_task_id'))
    if task and (current_step(task) or {}).get('id') == offer.get('step_id'):
        advance(task)
    from agent_service.conversation import _new_run
    run = _new_run(data['session_id'], offer['anchor_message_id'], 'queued', input_channel=offer.get('continuation_input_channel', 'text'))
    # The prompt still refers to the original topic boundary. Playback belongs
    # to the later explicit continue/save operation, including delayed ACKs.
    run['voice_input_ids'] = list(offer.get('continuation_voice_input_ids', []))
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
        offer['continuation_input_channel'] = run.get('input_channel', 'text')
        offer['continuation_voice_input_ids'] = list(run.get('voice_input_ids', []))
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
    from agent_service.knowledge_invitation import pause_refresh
    pause_refresh(h, data, run)
    offer = offers(data).get(run.get('capture_offer_id'))
    if offer and offer['status'] == 'saving':
        offer.update(status='failed', error=error)
        data['active_task_id'] = offer.get('resume_task_id', offer.get('origin_task_id'))
        emit(h, data, run, offer)


def interrupt_unstarted_save(h, data, run):
    """Revoke a stopped save attempt even when it retains an earlier task ID."""
    offer = offers(data).get(run.get('capture_offer_id'))
    task = data['tasks'].get((offer or {}).get('save_task_id'), {})
    if (offer and offer['status'] == 'saving'
            and not task.get('context', {}).get('commit_claimed') and task.get('status') != 'completed'):
        offer.update(status='failed', continuation_consumed=True, error='录入已中断，尚未保存，可重试。')
        if (data.get('pending') or {}).get('target_id') == offer['id']:
            data['pending'] = None
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
    matching = next((value for value in offers(data).values()
                     if value.get('draft', {}).get('id') == draft['id']
                     and value.get('draft', {}).get('version') == draft['version']), None)
    identity = matching['id'] if matching else str(uuid.uuid5(uuid.UUID(data['session_id']), f"explicit:{draft['id']}:{draft['version']}"))
    offer = offers(data).get(identity)
    if not offer:
        ctx = (task or {}).get('context', {})
        latest = next((m for m in reversed(data['messages']) if m['role'] == 'coach'), None)
        limited = bool(draft.get('excluded_unbound_feedback_ids'))
        offer = dict(id=identity, version=draft['version'], title='本次确认的知识' + ('（暂仅已确认讲解，旧题反馈待核对）' if limited else ''),
                     anchor_message_id=run['input_ids'][-1], message_ids=draft.get('source_message_ids', [latest['message_id']] if latest else []), draft=deepcopy(draft),
                     coverage_note=LIMITED_COVERAGE_NOTE if limited else '',
                     sources=deepcopy(draft.get('answer_sources', ctx.get('sources', []))), origin_task_id=(task or {}).get('task_id'),
                     lifecycle_revision=data.get('lifecycle_revision', 0), status='saving', next_request='',
                     continuation_consumed=True, error='', knowledge_ids=[])
        offers(data)[identity] = offer
    if offer['status'] != 'saved':
        offer.update(status='saving', action_input_id=run['input_ids'][-1], error='')
        offer['continuation_input_channel'] = run.get('input_channel', 'text')
        offer['continuation_voice_input_ids'] = list(run.get('voice_input_ids', []))
    run['capture_offer_id'] = identity
    emit(h, data, run, offer)
    return offer
