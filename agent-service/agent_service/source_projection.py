"""Bound repeated public-page text in answer prompts; retain durable originals."""
from copy import deepcopy


def answer_sources(sources, *, total_chars=12_000, per_source=4_000):
    projected = deepcopy(sources)
    remaining = total_chars
    for source in projected:
        if source.get('type') != 'public_source':
            continue  # user-provided material is never silently trimmed
        text = source.get('content', '')
        allowance = min(per_source, remaining)
        if len(text) > allowance:
            source['content'] = text[:allowance]
            source['content_excerpted'] = True
        remaining -= len(source.get('content', ''))
    return projected
