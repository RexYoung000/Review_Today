"""Question-aware public excerpts; durable reading sources stay untouched.

The selector ranks local text overlap, not factual support. Each page contributes
one contiguous window so a quoted span always exists in the delivered original.
"""
from copy import deepcopy
import hashlib
import json
import math
import re

VERSION = 1
TOTAL_CHARS = 12_000
PER_SOURCE = 4_000
_STOP = set('a an the and or is are was were be been to of in on for from with this that it its how what when where why please explain about can could would should do does tell me'.split())
_CN_STOP = set('什么 怎么 如何 哪些 为什么 请问 请你 一下 这个 那个 刚才 继续 解释 资料 内容 具体 问题 能否 是否'.split())


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _terms(query):
    words = re.findall(r'[a-z0-9_][a-z0-9_+.-]*|[\u3400-\u9fff]+', query.lower())
    terms = set()
    for word in words:
        if re.fullmatch(r'[\u3400-\u9fff]+', word):
            terms.update(word[i:i + 2] for i in range(len(word) - 1) if word[i:i + 2] not in _CN_STOP)
        elif word not in _STOP and len(word) > 1:
            terms.add(word.rstrip('.'))
    return sorted(terms, key=lambda item: (-len(item), item))[:128]


def _window(text, terms, allowance):
    if not terms or not text or allowance <= 0:
        return 0, 0.0
    lower = text.lower()
    # Small overlapping anchors find a relevant passage even in a single long
    # paragraph. Score distinct terms, so repeating one word cannot dominate.
    width = min(240, allowance)
    stride = max(1, width // 2)
    anchors = [(start, lower[start:start + width]) for start in range(0, len(text), stride)]
    frequencies = {term: sum(term in part for _, part in anchors) for term in terms}
    weights = {term: math.log(1 + len(anchors) / (1 + count)) for term, count in frequencies.items() if count}
    best_score, best_start = 0.0, 0
    for start, part in anchors:
        score = sum(weight for term, weight in weights.items() if term in part)
        if score > best_score:
            best_score, best_start = score, start
    if not best_score:
        return 0, 0.0
    # Keep adjacent explanation and qualifications rather than emitting keywords.
    start = max(0, min(best_start - max(0, allowance - width) // 2, len(text) - allowance))
    return start, best_score


def answer_sources(sources, *, query='', total_chars=TOTAL_CHARS, per_source=PER_SOURCE):
    projected = _unique_sources(sources)
    terms = _terms(query)
    remaining = max(0, total_chars)
    per_source = max(0, per_source)
    ranked = []
    for index, source in enumerate(projected):
        if source.get('type') == 'public_source':
            _, score = _window(source.get('content', ''), terms, min(per_source, remaining))
            ranked.append((index, score))
    # Relevant later sources can use the budget before unrelated earlier ones.
    for index, _ in sorted(ranked, key=lambda item: (-item[1], item[0])):
        source = projected[index]
        original = source.get('content', '')
        allowance = min(per_source, remaining)
        start, score = _window(original, terms, allowance)
        end = min(len(original), start + allowance)
        if not allowance:
            reason = 'budget_exhausted'
        elif len(original) <= allowance:
            start, end, reason = 0, len(original), 'full'
        elif score:
            reason = 'query_match'
        else:
            reason = 'no_match_fallback' if terms else 'no_query_fallback'
        source['content'] = original[start:end]
        selected = end - start
        source['source_selection'] = dict(version=VERSION, content_hash=_hash(original), query_hash=_hash(query),
            original_chars=len(original), selected_chars=selected, projected_chars=selected,
            omitted_chars=len(original) - selected, reason=reason,
            ranges=[dict(start=start, end=end, reason=reason)] if selected else [])
        if selected < len(original):
            source['content_excerpted'] = True
        remaining -= selected
    return projected


def manifest(sources):
    return [dict(source_id=s.get('source_id'), source_version=s.get('version'), url=s.get('url', ''),
                 **s['source_selection']) for s in sources if 'source_selection' in s]


def _identity(source):
    return str(source.get('source_id') or source.get('url') or source.get('id') or _hash(source.get('content', '')))


def _unique_sources(sources):
    """One current body per public identity; copy each object independently."""
    result, positions = [], {}
    for source in sources:
        identity = _identity(source)
        if source.get('type') == 'public_source':
            if identity in positions:
                index = positions[identity]
                if (source.get('version') or 0) >= (result[index].get('version') or 0):
                    result[index] = deepcopy(source)
                continue
            positions[identity] = len(result)
        result.append(deepcopy(source))
    return result


def _key(source):
    return _hash(json.dumps([_identity(source), source.get('version'), _hash(source.get('content', ''))], ensure_ascii=False))


def project_for_run(h, sid, rid, rev, sources, *, stage, query=''):
    """Freeze per-source selections within one revision, across model stages.

    Later stages may add sources using the remaining public budget. A retry of
    unchanged inputs reuses the packet; a supplement starts a fresh selection.
    Raw source caches are never overwritten.
    """
    data, run = h._snapshot(sid, rid, rev)
    sources = _unique_sources(sources)
    context, _ = h._context(data, run)
    input_signature = _hash(json.dumps([run.get('input_ids', []), context['current_inputs']], ensure_ascii=False))
    packet = deepcopy(run.get('source_selection_packet', {}))
    if packet.get('input_signature') != input_signature:
        packet = dict(input_signature=input_signature, query=query or '\n'.join(context['current_inputs']), entries={})
    packet['revision'] = rev
    entries = packet['entries']
    # A refreshed body replaces the old version's allocation, not its evidence.
    for source in sources:
        if source.get('type') == 'public_source':
            identity, key = _identity(source), _key(source)
            for old_key, value in list(entries.items()):
                if value['source_id'] == identity and old_key != key:
                    del entries[old_key]
    new = [s for s in sources if s.get('type') == 'public_source' and _key(s) not in entries]
    remaining = max(0, TOTAL_CHARS - sum(v['selection']['projected_chars'] for v in entries.values()))
    for original, source in zip(new, answer_sources(new, query=packet['query'], total_chars=remaining)):
        entries[_key(original)] = dict(source_id=_identity(source), selection=source['source_selection'])
    projected = deepcopy(sources)
    for source in projected:
        if source.get('type') != 'public_source':
            continue
        selection = deepcopy(entries[_key(source)]['selection'])
        original = source.get('content', '')
        source['content'] = ''.join(original[item['start']:item['end']] for item in selection['ranges'])
        source['source_selection'] = selection
        if selection['omitted_chars']:
            source['content_excerpted'] = True
    record = manifest(projected)
    with h.store.transaction(sid, rid, rev) as current:
        active = current['runs'][rid]
        active['source_selection_packet'] = packet
        previous = active.setdefault('source_selection_records', {}).get(stage)
        active['source_selection_records'][stage] = record
        if record and previous != record:
            h.store.event(current, active, 'source_selection', '已整理本轮资料片段',
                          payload={'source_selection': dict(stage=stage, sources=record,
                              public_chars=sum(s['projected_chars'] for s in record), budget=TOTAL_CHARS)})
    return projected


def align_evidence(evidence, sources):
    """A previous assessment can support only the same delivered source spans."""
    value = deepcopy(evidence)
    if value.get('state') not in {'supported', 'scoped'}:
        return value
    previous = value.get('source_selection', [])
    current = manifest(sources)
    def signature(item):
        return (item.get('source_id'), item.get('source_version'), item.get('content_hash'),
                tuple((span['start'], span['end']) for span in item.get('ranges', [])))
    covered = {signature(item) for item in previous if item.get('selected_chars')}
    cited = set(value.get('sources', []))
    relevant = [item for item in current if item['url'] in cited]
    if not cited or not relevant or any(not item['selected_chars'] or signature(item) not in covered for item in relevant) or cited - {s['url'] for s in relevant}:
        value.update(state='unverified', summary='本轮资料片段与此前核验范围不同，不能沿用此前的核验结论。',
                     sources=[], source_selection=current, selection_changed=True)
    return value
