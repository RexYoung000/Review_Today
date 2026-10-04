"""Truthful, read-only knowledge-card status from local commit evidence.

Related library cards are references, never receipts for the current segment.
Only a completed memory task with a Mac persistence ACK can certify a write.
"""
from copy import deepcopy


def _task_receipt(data, task):
    if not task or task.get('session_id') != data.get('session_id') or task.get('status') != 'completed':
        return []
    if not any(event.get('node') == 'mac_ack' for event in task.get('events', [])):
        return []
    return list(dict.fromkeys(item['id'] for item in (task.get('memory_package') or {}).get('knowledge', [])
                             if item.get('id')))


def _is_learning(run):
    return (run.get('status') == 'completed' and not run.get('memory_invalidated')
            and not run.get('knowledge_status_reply')
            and bool(run.get('activity_kind') in {'knowledge_answer', 'lesson_step'}
                     or run.get('learning_concepts') or run.get('evaluated_binding')))


def _discussion_context(data, valid_run=None):
    """Identify the live discussion without borrowing a possibly stale plan title.

    Old evaluations can identify what was discussed, but are not promoted to
    verified knowledge or used as card facts by this read-only projection.
    """
    from agent_service.topic_capture import source_transparent
    sources, statuses, owner = [], [], None
    corrected = {run.get('knowledge_status_correction_message_id') for run in data.get('runs', {}).values()
                 if run.get('status') == 'completed'}
    delivered = {event['message']['message_id']: event.get('revision') for event in data.get('events', [])
                 if event.get('message')}
    for message in data.get('messages', []):
        if message.get('role') != 'coach':
            continue
        run = data.get('runs', {}).get(message.get('run_id'), {})
        intent = run.get('intent') or {}
        task = data.get('tasks', {}).get(run.get('task_id'), {})
        if (run.get('status') != 'completed' or run.get('memory_invalidated')
                or task.get('context', {}).get('memory_invalidated')
                or valid_run is not None and not valid_run(run)
                or message['message_id'] in delivered and delivered[message['message_id']] != run.get('revision')):
            sources, statuses, owner = [], [], None
            continue
        if source_transparent(run):
            if sources and not run.get('knowledge_status_reply') and message['message_id'] not in corrected:
                statuses.append(dict(message_id=message['message_id'], content=message['content']))
            continue
        feedback = ('answer' in intent.get('intents', []) and any(
            entry.get('message_id') in run.get('input_ids', []) and entry.get('evaluation')
            for entry in task.get('context', {}).get('practice', [])))
        if not (_is_learning(run) or feedback):
            sources, statuses, owner = [], [], None
            continue
        if intent.get('relation') == 'new_topic' or sources and owner != run.get('task_id'):
            sources = []
        # A previous save claim cannot refer to teaching delivered after it.
        statuses, owner = [], run.get('task_id')
        sources.append(dict(message_id=message['message_id'], content=message['content'],
                            concepts=list(run.get('learning_concepts') or []),
                            evidence_kind='discussion_only_feedback' if feedback else 'teaching'))
    return sources[-4:], statuses[-3:]


def _offer_covers_focus(offer, item):
    """A single-check invitation covers its excerpts, not the whole lesson."""
    if item.get('message_id') not in offer.get('message_ids', []):
        return False
    if offer.get('trigger') != 'verified_check' or item['message_id'] == offer.get('anchor_message_id'):
        return True
    from agent_service.learning_progress import _visible_quote
    quote = _visible_quote(item.get('quote', ''))
    return bool(quote and any(fragment.get('message_id') == item['message_id']
                            and quote in _visible_quote(fragment.get('text', ''))
                            for fragment in offer.get('fragments', [])))


def facts(data, *, related_knowledge=None, valid_run=None, status_context=None):
    """Return plain state for the intent/context projection; do not mutate it."""
    messages = data.get('messages', [])
    positions = {message['message_id']: index for index, message in enumerate(messages)}
    learning = [message for message in messages if message.get('role') == 'coach'
                and _is_learning(data.get('runs', {}).get(message.get('run_id'), {}))]
    latest = learning[-1] if learning else None
    tasks = data.get('tasks', {})
    receipts = {identity: _task_receipt(data, task) for identity, task in tasks.items()}
    saved_ids = list(dict.fromkeys(identity for ids in receipts.values() for identity in ids))
    capture_offers = list(data.get('capture_offers', {}).values())
    discussion, prior_statuses = _discussion_context(data, valid_run)
    current_offer = None
    scope_unconfirmed, scope_has_uncovered, scope_has_unconfirmed = False, False, False
    scope_saved_ids = []
    latest_position = positions.get((latest or {}).get('message_id'), -1)
    if status_context is not None:
        selected = validate_context(dict(discussion_sources=discussion), status_context)
        if selected['focus_labels']:
            value = status_context.model_dump() if hasattr(status_context, 'model_dump') else status_context
            current_offer = next((candidate for candidate in reversed(capture_offers)
                                  if all(_offer_covers_focus(candidate, item) for item in value['focus'])), None)
            if current_offer is None:
                covered, saved = set(), set()
                for candidate in capture_offers:
                    indices = {index for index, item in enumerate(value['focus']) if _offer_covers_focus(candidate, item)}
                    covered.update(indices)
                    receipt = receipts.get(candidate.get('save_task_id'), [])
                    if (indices and candidate.get('status') == 'saved' and receipt
                            and set(receipt) == set(candidate.get('knowledge_ids', []))):
                        saved.update(indices)
                        scope_saved_ids.extend(receipt)
                # Partial coverage or separate offers cannot certify one combined
                # scope, but their actual saved receipts must not be denied.
                scope_unconfirmed = bool(covered)
                scope_has_uncovered = len(covered) < len(value['focus'])
                scope_has_unconfirmed = len(saved) < len(value['focus'])
                scope_saved_ids = list(dict.fromkeys(scope_saved_ids))
    else:
        # An older invitation inserted last cannot hide the invitation covering
        # the latest explanation. Older saved/deferred segments stay separate.
        for candidate in reversed(capture_offers):
            covered_position = max((positions.get(mid, -1) for mid in candidate.get('message_ids', [])), default=-1)
            if latest_position <= covered_position:
                current_offer = candidate
                break
    stage, knowledge_ids, error = ('unorganized' if latest else 'none'), [], ''
    if current_offer:
        task = tasks.get(current_offer.get('save_task_id'))
        receipt = receipts.get(current_offer.get('save_task_id'), [])
        declared = current_offer.get('knowledge_ids', [])
        status = current_offer.get('status')
        if status == 'saved' and receipt and set(receipt) == set(declared):
            stage, knowledge_ids = 'saved', receipt
        elif status == 'invalidated' or current_offer.get('lifecycle_revision', 0) != data.get('lifecycle_revision', 0):
            stage = 'invalidated'
        elif status == 'failed' or (task and task.get('status') in {'needs_attention', 'retryable_failed', 'terminal_failed', 'cancelled'}):
            stage, error = 'failed', current_offer.get('error', '')
        elif status in {'saving', 'saved'}:
            # A declared success without its durable receipt stays unconfirmed.
            stage = 'saving'
        elif status == 'offered':
            stage = 'awaiting_confirmation'
        elif status == 'dismissed':
            stage = 'dismissed'
        elif status in {'deferred', 'skipped'}:
            stage = status
    else:
        draft = data.get('draft') or {}
        pending = data.get('pending') or {}
        # A previous mastery/organization draft is not the latest explanation.
        source_ids = draft.get('source_message_ids', [])
        if draft and not source_ids:
            draft_event = next((event for event in reversed(data.get('events', []))
                                if event.get('stage') == 'draft'
                                and (event.get('payload', {}).get('draft') or {}).get('id') == draft.get('id')
                                and (event.get('payload', {}).get('draft') or {}).get('version') == draft.get('version')), None)
            if draft_event:
                source_ids = [message['message_id'] for message in messages
                              if message.get('role') == 'coach' and message.get('run_id') == draft_event.get('run_id')]
        draft_current = bool(draft and (not latest or latest['message_id'] in source_ids))
        if draft_current and draft.get('invalidated'):
            stage = 'invalidated'
        elif draft_current and pending.get('kind') == 'save' and pending.get('target_id') == draft.get('id'):
            stage = 'awaiting_confirmation'
        # Legacy direct-save tasks may predate capture offers; still require ACK.
        for task in reversed(list(tasks.values())):
            if task.get('mode') != 'memory_organization' or task.get('session_id') != data.get('session_id'):
                continue
            ctx = task.get('context', {})
            if not ctx.get('conversation_managed') or ctx.get('capture_offer_id'):
                continue
            origin = data.get('runs', {}).get(ctx.get('origin_run_id'), {})
            origin_position = max((positions.get(mid, -1) for mid in origin.get('input_ids', [])), default=-1)
            if origin_position < latest_position:
                continue
            if receipts.get(task.get('task_id')):
                stage, knowledge_ids = 'saved', receipts[task['task_id']]
            elif task.get('status') in {'committing', 'running', 'accepted', 'queued'}:
                stage = 'saving'
            elif task.get('status') in {'needs_attention', 'retryable_failed', 'terminal_failed', 'cancelled'}:
                stage = 'failed'
            break
    if scope_unconfirmed:
        stage, knowledge_ids, error = 'scope_unconfirmed', [], ''
    current_cards = {}
    for identity, task in tasks.items():
        if not receipts.get(identity):
            continue
        for card in (task.get('memory_package') or {}).get('knowledge', []):
            if card.get('id') in knowledge_ids:
                title = (card.get('title') or card.get('learning_goal') or '').strip()
                current_cards[card['id']] = dict(id=card['id'], title=title)
    return dict(stage=stage, current_knowledge_ids=knowledge_ids, current_cards=list(current_cards.values())[:8],
                discussion_sources=discussion, prior_status_messages=prior_statuses,
                session_has_generated_package=any(task.get('memory_package') for task in tasks.values()
                    if task.get('session_id') == data.get('session_id')),
                session_saved_knowledge_ids=saved_ids,
                scope_saved_knowledge_ids=scope_saved_ids,
                scope_has_uncovered_focus=scope_unconfirmed and scope_has_uncovered,
                scope_has_unconfirmed_focus=scope_unconfirmed and scope_has_unconfirmed,
                latest_learning_message_id=(latest or {}).get('message_id'),
                capture_offer=({key: deepcopy(current_offer[key]) for key in ('id', 'version', 'title', 'status', 'trigger', 'scope_summary')
                                if key in current_offer} if current_offer else None),
                related_library_card_count=len(related_knowledge or []), error=error,
                coverage_note=(current_offer or {}).get('coverage_note', ''),
                steps=['讲解和作答会留下聊天与学习记录，但不会自动生成知识卡',
                       ('在这条答题反馈下选择新增知识，或选择稍后；点击前不会生成或保存知识卡'
                        if (current_offer or {}).get('trigger') == 'verified_check'
                        else '明确要求把刚才内容整理成知识卡，或在收尾面板选择录入知识'),
                       '按确认的内容整理、核验并保存到本机知识库',
                       '确认保存成功后才显示已写入知识库'])


def _claim_quote_keeps_context(content, quote):
    """Do not let a substring remove the sentence's negation or attribution.

    Whether the intact assertion is positive remains the same-call semantic
    judgment; a reference check alone cannot establish that meaning.
    """
    if not quote:
        return False
    start = content.find(quote)
    while start >= 0:
        prefix = content[:start].rstrip(' \t\r')
        suffix = content[start + len(quote):].lstrip(' \t\r')
        sentence_start = not prefix or prefix[-1] in '.!?。！？\n'
        clause_end = not suffix or suffix[0] in ',;:.!?，；：。！？\n' or quote[-1] in '.!?。！？'
        if sentence_start and clause_end:
            return True
        start = content.find(quote, start + 1)
    return False


def validate_context(state, proposal):
    """Validate the entire semantic selection without changing its scope.

    Topic summaries belong to the same-call semantic judgment, while message IDs
    and verbatim evidence are deterministic checks. Dropping a rejected primary
    reference would silently make an older secondary topic answer another query.
    """
    value = proposal.model_dump() if hasattr(proposal, 'model_dump') else proposal or {}
    sources = {source['message_id']: source for source in state.get('discussion_sources', [])}
    labels = []
    focus = value.get('focus') or []
    for item in (focus if len(focus) <= 3 else []):
        source = sources.get(item.get('message_id'), {})
        quote, label = item.get('quote', '').strip(), item.get('label', '').strip()
        if not (quote and len(quote) <= 300 and quote in source.get('content', '')
                and label and len(label) <= 60):
            labels = []
            break
        if label not in labels:
            labels.append(label)
    claim = value.get('prior_claim') or {}
    candidate = next((item for item in state.get('prior_status_messages', [])
                      if item['message_id'] == claim.get('message_id')), {})
    quote = claim.get('quote', '').strip()
    kind = claim.get('kind')
    # A real receipt anywhere in this session makes an old statement ambiguous;
    # do not falsely retract it just because the current segment is unsaved.
    correction = (bool(labels) and _claim_quote_keeps_context(candidate.get('content', ''), quote)
                  and not state.get('session_saved_knowledge_ids')
                  and kind in {'recorded', 'generated', 'saved'}
                  and not (kind == 'generated' and state.get('session_has_generated_package')))
    return dict(focus_labels=labels,
                correction_message_id=claim['message_id'] if correction else None,
                correction_quote=quote if correction else '')


def reply(state, status_context=None):
    """The visible status answer deliberately uses no free-form model claims."""
    stage = state['stage']
    messages = {
        'none': '这段聊天还没有可确认的新知识卡，也没有正在执行的录入。',
        'unorganized': '刚才的讲解和作答已留在聊天记录中，但这段内容还没有整理成知识卡。',
        'awaiting_confirmation': ('这段内容已有待确认的整理来源，尚未写入知识库。请在收尾面板选择「录入知识」；有后续话题时按钮会显示「录入并继续」。'
                                  if state.get('capture_offer') else '已有整理稿等待你确认，尚未写入知识库。确认内容后，可以明确回复「确认保存」。'),
        'dismissed': '这段内容的整理来源仍保留，但收尾提示已收起，也还没有写入知识库。可以明确说「把刚才内容整理成知识卡」。',
        'saving': '这段内容正在整理、核验或保存。目前还不能确认已经写入知识库。',
        'saved': f'这次确认的内容已成功写入 {len(state["current_knowledge_ids"])} 张知识卡。',
        'failed': '这次知识录入尚未完成，不能算作已保存。请查看收尾面板的原因，修订内容或选择「重试录入」。',
        'invalidated': '原整理来源或版本已经变化，旧版不能继续录入。需要先完成修订，再确认新的整理内容。',
        'deferred': '这段内容已选择「稍后录入」，来源仍保留，但还没有写入知识库。可以回到这段的收尾面板选择「录入知识」。',
        'skipped': '这段内容已跳过录入，聊天记录仍在，但没有因此生成知识卡。',
        'scope_unconfirmed': '这些内容的保存范围不完全一致，尚不能作为一个整体确认。',
    }
    invitation = state.get('capture_offer') or {}
    if invitation.get('trigger') == 'verified_check':
        messages.update(
            awaiting_confirmation='这次答题对应的知识范围已有邀请，还没有生成知识卡或写入知识库。请在这条答题反馈下点击「新增知识」；也可以选「稍后」或继续追问。',
            deferred='这次新增知识已选择「稍后」，来源仍保留，但还没有写入知识库。可以在待处理中打开这条邀请，点击「新增知识」。',
            dismissed='这次新增知识提示已收起，来源仍保留，也还没有写入知识库。可以明确说「把刚才内容整理成知识卡」。',
            failed='这次新增知识尚未完成，不能算作已保存。请在这条邀请中查看原因，修订内容或选择「重试录入」。',
            invalidated='这条新增知识邀请的范围或来源已经变化，旧版不能继续保存。需要先完成修订，再确认新的范围。')
    context = validate_context(state, status_context)
    text = ''
    if context['correction_quote']:
        text = '前面关于本轮知识卡的说法不准确；没有可确认的本轮知识卡保存记录。\n\n'
    if context['focus_labels']:
        text += '刚才讨论的是' + '、'.join(context['focus_labels']) + '。'
    text += messages[stage]
    if stage == 'scope_unconfirmed':
        if state.get('scope_saved_knowledge_ids'):
            text += '已保存的部分可以到知识库查看。'
        if state.get('scope_has_uncovered_focus'):
            text += '其余内容需要先明确保存范围。'
        elif state.get('scope_has_unconfirmed_focus'):
            text += '尚未确认的部分需要分别核对邀请范围和保存状态。'
        text += '请分别核对对应记录的保存范围。'
    if invitation.get('trigger') == 'verified_check' and invitation.get('scope_summary'):
        text += (' 原邀请范围：' if stage == 'invalidated' else ' 本次保存范围：') + invitation['scope_summary']
    if stage == 'saved':
        titles = [' '.join(card['title'].split()) for card in state.get('current_cards', []) if card.get('title')]
        if titles:
            text += ' 内容包括：' + '；'.join(title[:120] + ('…' if len(title) > 120 else '') for title in titles) + '。'
    if stage in {'none', 'unorganized', 'skipped'}:
        text += '你可以明确说「把刚才内容整理成知识卡」。系统会按确认的内容整理、核验并保存到本机知识库；确认保存成功后才算完成。'
    if stage not in {'saved', 'scope_unconfirmed'} and state.get('session_saved_knowledge_ids'):
        text += f' 这段聊天此前有 {len(state["session_saved_knowledge_ids"])} 张已确认写入的卡，但不能据此说刚才这段也已保存。'
    if state.get('related_library_card_count'):
        text += ' 上下文中引用的知识库旧卡只是参考，不代表本轮新生成的卡。'
    if state.get('coverage_note'):
        text += ' ' + state['coverage_note']
    return text
