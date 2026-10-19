"""Whole-article coverage must survive limits, retry and mixed source packets."""
import copy

from agent_service.article_coverage import sections, notice
from agent_service.source_projection import answer_sources
from tests import test_source_projection as projection


def test_legacy_run_without_a_resolved_intent_keeps_focused_budget():
    harness = projection.InMemoryProjectionHarness()
    harness.data['runs']['run']['intent'] = None
    source = projection.SourceProjectionTests.public('公开资料。' * 2_000)
    result = harness.project([source])[0]
    assert len(result['content']) == 4_000 and 'text_coverage' not in result


def test_whole_article_packet_survives_retry_then_reselects_only_for_new_inputs():
    harness = projection.InMemoryProjectionHarness()
    harness.data['runs']['run']['intent'] = dict(public_source_scope='full_text')
    source = projection.SourceProjectionTests.public('首章正文\n' * 2_000 + '末章独有的边界条件。')
    initial = harness.project([source], stage='material_readiness')[0]
    assert initial['content'] == source['content']
    assert len(initial['content']) > 4_000
    harness.data['runs']['run']['intent'] = dict(public_source_scope='focused')
    retried = harness.project([source], stage='answer', query='A different regenerated query')[0]
    assert retried == initial, 'unchanged-input retry cannot drift back to focused mode'
    harness._context = lambda *_args: ({'current_inputs': ['A genuinely new question']}, {})
    focused = harness.project([source], stage='answer')[0]
    assert len(focused['content']) == 4_000 and 'text_coverage' not in focused


def test_all_four_maximum_read_bodies_fit_without_mutating_or_hiding_omissions():
    sources = [projection.SourceProjectionTests.public(f'第{i}篇\n' + '文' * 19_995, str(i)) for i in range(4)]
    before = copy.deepcopy(sources)
    full = answer_sources(sources, scope='full_text')
    assert all(a['content'] == b['content'] for a, b in zip(full, sources))
    assert all(s['source_selection']['omitted_chars'] == 0 for s in full)
    assert sources == before
    oversized = sources + [projection.SourceProjectionTests.public('额外来源。' * 5_000, 'extra')]
    limited = answer_sources(oversized, scope='full_text')
    assert sum(len(s['content']) for s in limited) <= 80_000
    assert any(s['source_selection']['omitted_chars'] for s in limited)
    assert '未进入本次总结' in notice(limited)


def test_per_source_limit_and_upstream_excerpt_are_distinct():
    source = projection.SourceProjectionTests.public('头部\n' + '中' * 24_000 + '\n尾部')
    selected = answer_sources([source], scope='full_text')[0]
    assert len(selected['content']) == 20_000
    assert selected['text_coverage']['delivered_text_complete'] is False
    assert selected['text_coverage']['upstream_excerpted'] is False
    assert '仅总结已提供部分' in notice([selected])
    excerpt = projection.SourceProjectionTests.public('上游返回的局部段落。', content_excerpted=True)
    selected = answer_sources([excerpt], scope='full_text')[0]
    assert selected['text_coverage']['delivered_text_complete'] is True
    assert selected['text_coverage']['upstream_excerpted'] is True
    assert '可用内容为节选' in notice([selected])
    chunks = projection.SourceProjectionTests.public('远程返回的片段。', content_kind='extracted_chunks')
    assert answer_sources([chunks], scope='full_text')[0]['text_coverage']['upstream_excerpted']


def test_outline_covers_raw_coordinates_and_excludes_fenced_and_indented_code_and_lists():
    raw = '作者\n\\# 文题\n开篇正文\n1 - 第一章\n内容\n```python\n# not a heading\n```\n    # neither\n\\*\\*2 \\- 第二章\\*\\*\n**2.1 子节**\n结语\n  1. Reference entry\n'
    outline = sections(raw)
    assert [s['title'] for s in outline] == ['开篇', '文题', '1 - 第一章', '2 - 第二章', '2.1 子节']
    assert ''.join(raw[s['start']:s['end']] for s in outline) == raw
    assert outline[0]['start'] == 0 and outline[-1]['end'] == len(raw)
