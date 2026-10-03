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


def facts(data, *, related_knowledge=None):
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
    current_offer = capture_offers[-1] if capture_offers else None
    latest_position = positions.get((latest or {}).get('message_id'), -1)
    if current_offer:
        covered_position = max((positions.get(mid, -1) for mid in current_offer.get('message_ids', [])), default=-1)
        # Saved/deferred prior segments cannot label newly discussed material.
        if latest_position > covered_position and (latest or {}).get('message_id') not in current_offer.get('message_ids', []):
            current_offer = None
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
    current_cards = {}
    for identity, task in tasks.items():
        if not receipts.get(identity):
            continue
        for card in (task.get('memory_package') or {}).get('knowledge', []):
            if card.get('id') in knowledge_ids:
                title = (card.get('title') or card.get('learning_goal') or '').strip()
                current_cards[card['id']] = dict(id=card['id'], title=title)
    return dict(stage=stage, current_knowledge_ids=knowledge_ids, current_cards=list(current_cards.values())[:8],
                session_saved_knowledge_ids=saved_ids,
                latest_learning_message_id=(latest or {}).get('message_id'),
                capture_offer=({key: deepcopy(current_offer[key]) for key in ('id', 'version', 'title', 'status')
                                if key in current_offer} if current_offer else None),
                related_library_card_count=len(related_knowledge or []), error=error,
                coverage_note=(current_offer or {}).get('coverage_note', ''),
                steps=['讲解和作答会留下聊天与学习记录，但不会自动生成知识卡',
                       '明确要求把刚才内容整理成知识卡，或在收尾面板选择录入知识',
                       '按确认的内容整理、核验并保存到本机知识库',
                       '确认保存成功后才显示已写入知识库'])


def reply(state):
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
    }
    text = messages[stage]
    if stage == 'saved':
        titles = [' '.join(card['title'].split()) for card in state.get('current_cards', []) if card.get('title')]
        if titles:
            text += ' 内容包括：' + '；'.join(title[:120] + ('…' if len(title) > 120 else '') for title in titles) + '。'
    if stage in {'none', 'unorganized', 'skipped'}:
        text += '你可以明确说「把刚才内容整理成知识卡」。系统会按确认的内容整理、核验并保存到本机知识库；确认保存成功后才算完成。'
    if stage != 'saved' and state.get('session_saved_knowledge_ids'):
        text += f' 这段聊天此前有 {len(state["session_saved_knowledge_ids"])} 张已确认写入的卡，但不能据此说刚才这段也已保存。'
    if state.get('related_library_card_count'):
        text += ' 上下文中引用的知识库旧卡只是参考，不代表本轮新生成的卡。'
    if state.get('coverage_note'):
        text += ' ' + state['coverage_note']
    return text
