"""Visible, versioned source selections made after a grounded understanding check.

An invitation is not an extracted card or a save grant. Only capture_save freezes
the displayed version for the existing generation/verification/commit pipeline.
"""
from copy import deepcopy
import hashlib
import uuid

from agent_service.learning_memory import merge_references
from agent_service.learning_progress import _visible_quote


UPDATE_INSTRUCTION = """\n本轮 capture_candidates 是尚未保存的知识点邀请，不是已生成卡片。
本次回答有效补充或纠正其中同一个知识点时，必须返回 capture_update：原样选择 offer_id/version，
retained_fragment_ids 只保留仍成立且属于该知识点的旧来源片段 ID；evidence_quotes 从本轮 message
逐字连续摘录该知识点的新解释。纠正时排除已推翻的旧片段，不将旧错误与新结论一起保留。
scope_summary 用一句简短的具体知识概括更新后内容，包含本次补充的要点；不重复标题，不写“对应讲解、有效纠正、保存范围”等流程词，不宣称已保存或已掌握。
同一知识点的适用条件、限制、反例和时效边界都是对原内容的补充，已经解释这些内容时必须更新，不能返回 null。
范围只能属于原 concepts；其他新知识点即使同属一节也不合并。没有对应的有效补充时 capture_update=null。
这只是选择来源与说明范围，不生成知识卡，不改写已保存内容，不重发新增知识邀请。
"""

EDITABLE = {'offered', 'deferred', 'dismissed', 'failed'}


def unoffered_concepts(data, task_id, binding):
    covered = {c for offer in data.get('capture_offers', {}).values()
               if offer.get('trigger') == 'verified_check' and offer.get('origin_task_id') == task_id
               for c in offer.get('concepts', [])}
    return [c for c in (binding or {}).get('concepts', []) if c not in covered]


def validate_update(update, message, candidates):
    from agent_service.openai_client import ModelCallError
    candidate = next((o for o in candidates if o['id'] == update.get('offer_id')
                      and o['version'] == update.get('version')), None)
    retained = update.get('retained_fragment_ids', [])
    quotes = update.get('evidence_quotes', [])
    if (not candidate or len(set(retained)) != len(retained)
            or not set(retained) <= {f['id'] for f in (candidate or {}).get('fragments', [])}
            or not quotes or any(not q.strip() or _visible_quote(q.strip()) not in _visible_quote(message) for q in quotes)):
        raise ModelCallError('SCHEMA', 'field=capture_update; select an existing invitation version and real source excerpts only')


def candidates(h, data, run, decision=None):
    if decision and (decision.relation == 'new_topic' or decision.proposed_actions):
        return []
    result = []
    for offer in data.get('capture_offers', {}).values():
        if (offer.get('trigger') != 'verified_check' or offer.get('origin_task_id') != run.get('task_id')
                or offer['status'] not in EDITABLE | {'invalidated'}
                or offer['status'] == 'invalidated' and not offer.get('correction_pending')
                or offer.get('lifecycle_revision') != data.get('lifecycle_revision', 0)
                or not h.store.memory_valid(offer['draft'].get('memory_references', []))):
            continue
        result.append(dict(id=offer['id'], version=offer['version'], concepts=offer['concepts'],
                           scope_summary=offer['scope_summary'], correction_pending=offer.get('correction_pending', False),
                           fragments=[{k: f[k] for k in ('id', 'text')} for f in offer['fragments']]))
    return result


def _fragment(message, run, text, kind):
    return dict(id=str(uuid.uuid4()), text=text, message_id=message['message_id'], run_id=run['run_id'], kind=kind,
                memory_references=deepcopy(run.get('memory_references', [])),
                sources=deepcopy(run.get('answer_sources', [])), source_type=run.get('answer_source_type', 'agent_generated'))


def pause_refresh(h, data, run):
    from agent_service import topic_capture
    for offer in data.get('capture_offers', {}).values():
        if offer.get('correction_run_id') == run['run_id'] and offer.get('correction_pending'):
            offer['error'] = '修正后的保存范围尚未确认，请继续澄清后再录入。'
            topic_capture.emit(h, data, run, offer)


def _sync_source(offer):
    fragments = offer['fragments']
    ids = list(dict.fromkeys(f['message_id'] for f in fragments))
    references = merge_references(*(f['memory_references'] for f in fragments))
    sources = {(s['source_id'], s.get('version', 1)): deepcopy(s) for f in fragments for s in f['sources']}
    content = ('仅整理以下知识范围：' + '、'.join(offer['concepts']) + '\n本次可见范围：' + offer['scope_summary']
               + '\n\n当前有效来源选段（不将答题评价或掌握描述当作知识事实）：\n'
               + '\n\n'.join(f['text'] for f in fragments))
    # The answer feedback identifies the invitation, even when its grading prose
    # is excluded from the factual excerpts passed to generation.
    offer['message_ids'] = list(dict.fromkeys(ids + [offer['anchor_message_id']]))
    offer['sources'] = list(sources.values())
    offer['source_key'] = hashlib.sha256(content.encode()).hexdigest()
    offer['draft'] = dict(id=offer['id'], version=offer['version'], content=content, understanding='unknown',
                         source_type='mixed' if len({f['source_type'] for f in fragments}) > 1 else fragments[0]['source_type'],
                         source_message_ids=ids, answer_sources=offer['sources'], memory_references=references,
                         public_search_query=offer.get('public_search_query', ''))


def published(h, data, run, message):
    """Called inside the final reply transaction, so recovery cannot lose an offer."""
    from agent_service import topic_capture
    if run.get('capture_scope_update'):
        update = run['capture_scope_update']
        offer = data.get('capture_offers', {}).get(update['offer_id'])
        current = candidates(h, data, run)
        validate_update(update, message['content'], current)
        kept = [f for f in offer['fragments'] if f['id'] in update['retained_fragment_ids']]
        added = [_fragment(message, run, quote.strip(), 'explanation') for quote in update['evidence_quotes']]
        offer.update(version=offer['version'] + 1, fragments=kept + added,
                     scope_summary=update['scope_summary'], error='',
                     status=offer.pop('status_before_correction', offer['status']))
        offer.pop('correction_pending', None)
        offer.pop('correction_run_id', None)
        _sync_source(offer)
        topic_capture.emit(h, data, run, offer)
        # The completed semantic selection identifies the corrected invitation.
        # Any different invitation provisionally paused by this input keeps its
        # source and state, while the newer version rejects its earlier buttons.
        for other in data.get('capture_offers', {}).values():
            if (other.get('correction_run_id') == run['run_id'] and other['id'] != offer['id']
                    and other['status'] == 'invalidated' and other.get('correction_pending')
                    and h.store.memory_valid(other['draft'].get('memory_references', []))):
                other.update(status=other.pop('status_before_correction'), error='')
                other.pop('correction_pending', None)
                other.pop('correction_run_id', None)
                _sync_source(other)
                topic_capture.emit(h, data, run, other)
    # A completed answer without a usable scope correction must not leave the
    # invitation claiming that a finished run is still checking it.
    pause_refresh(h, data, run)
    binding = run.get('evaluated_binding')
    concepts = run.get('verified_concepts', [])
    if not binding or not concepts:
        return
    task = data['tasks'].get(run.get('task_id'))
    if not task or task['context'].get('memory_invalidated'):
        return
    evaluation = topic_capture._evaluation_for(task, run)
    if not evaluation or not evaluation.get('passed') or evaluation.get('question_validity', 'valid') != 'valid':
        return
    concepts = unoffered_concepts(data, task['task_id'], binding)
    if not concepts:
        return
    key = hashlib.sha256((task['task_id'] + '\n'.join(sorted(concepts))).encode()).hexdigest()
    if any(o.get('check_scope_key') == key for o in topic_capture.offers(data).values()):
        return
    fragments = []
    fallback_allowed = binding.get('scope_source') != 'rubric_fallback' and concepts == binding['concepts']
    quotes = run.get('capture_quotes') or (binding['evidence_quotes'] if fallback_allowed else [])
    if not quotes:
        return
    for quote in quotes:
        source = next((m for m in reversed(data['messages']) if m['role'] == 'coach'
                       and m['message_id'] != message['message_id']
                       and _visible_quote(quote) in _visible_quote(m['content'])
                       and data['runs'].get(m.get('run_id'), {}).get('task_id') == task['task_id']
                       and topic_capture._source_run_valid(h, data, m, data['runs'][m['run_id']])), None)
        if not source:
            return
        fragments.append(_fragment(source, data['runs'][source['run_id']], quote, 'teaching'))
    for quote in run.get('capture_feedback_quotes', []):
        fragments.append(_fragment(message, run, quote, 'evaluation'))
    if not fragments:
        return
    identity = str(uuid.uuid4())
    offer = dict(id=identity, version=1, trigger='verified_check', title='、'.join(concepts), concepts=concepts,
                 scope_summary=run.get('capture_scope_summary') or '、'.join(concepts),
                 anchor_message_id=message['message_id'], fragments=fragments, check_scope_key=key,
                 origin_task_id=task['task_id'], step_id=binding['step_id'],
                 lifecycle_revision=data.get('lifecycle_revision', 0), status='offered', next_request='',
                 continuation_consumed=True, requires_mastery=False, error='', knowledge_ids=[],
                 public_search_query=task['context'].get('public_search_query', ''))
    _sync_source(offer)
    topic_capture.offers(data)[identity] = offer
    topic_capture.emit(h, data, run, offer)
