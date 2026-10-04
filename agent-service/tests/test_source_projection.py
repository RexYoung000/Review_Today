"""Question-bound public excerpts keep exact provenance and honest budgets."""
import copy
import hashlib
import unittest
from contextlib import contextmanager

from agent_service.source_projection import answer_sources, project_for_run


class InMemoryProjectionHarness:
    """Exercise the actual packet function without a service or database."""
    def __init__(self):
        self.data = {'runs': {'run': {'revision': 1}}}
        self.store = self

    def _snapshot(self, *_args):
        data = copy.deepcopy(self.data)
        return data, data['runs']['run']

    def _context(self, *_args):
        return {'current_inputs': ['CAPSTONE recovery']}, {}

    @contextmanager
    def transaction(self, *_args):
        yield self.data

    def event(self, *_args, **_kwargs):
        pass

    def project(self, sources, *, stage='answer', query='CAPSTONE recovery'):
        return project_for_run(self, 'session', 'run', 1, sources, stage=stage, query=query)


class SourceProjectionTests(unittest.TestCase):
    REASONS = {'full', 'query_match', 'no_match_fallback', 'no_query_fallback', 'budget_exhausted'}

    @staticmethod
    def public(text, identifier='page', **extra):
        return dict(id=identifier, type='public_source', title='Synthetic public documentation',
                    url=f'https://example.test/{identifier}', content=text, **extra)

    def assert_selection(self, original, result, query, *, budget):
        text = original.get('content', '')
        content = result.get('content', '')
        selection = result['source_selection']
        self.assertEqual(selection['version'], 1)
        self.assertEqual(selection['content_hash'], hashlib.sha256(text.encode('utf-8')).hexdigest())
        self.assertEqual(selection['query_hash'], hashlib.sha256(query.encode('utf-8')).hexdigest())
        self.assertEqual(selection['original_chars'], len(text))
        self.assertEqual(selection['projected_chars'], len(content))
        self.assertLessEqual(len(content), budget)
        self.assertIn(selection['reason'], self.REASONS)
        ranges = selection['ranges']
        prior_end = 0
        cursor = 0
        selected_chars = 0
        for item in ranges:
            start, end = item['start'], item['end']
            self.assertIsInstance(start, int)
            self.assertIsInstance(end, int)
            self.assertGreaterEqual(start, prior_end)
            self.assertGreater(end, start)
            self.assertLessEqual(end, len(text))
            self.assertIn(item['reason'], self.REASONS)
            fragment = text[start:end]
            position = content.find(fragment, cursor)
            self.assertGreaterEqual(position, cursor, 'every reported range must occur verbatim in original order')
            cursor = position + len(fragment)
            selected_chars += end - start
            prior_end = end
        self.assertEqual(selection['selected_chars'], selected_chars)
        self.assertEqual(selection['omitted_chars'], len(text) - selected_chars)
        self.assertGreaterEqual(selection['projected_chars'], selected_chars)
        if len(ranges) == 1:
            self.assertEqual(content, text[ranges[0]['start']:ranges[0]['end']],
                             'a continuous-window projection cannot add text absent from the selected source')
        if not ranges:
            self.assertEqual(content, '')
        if selection['omitted_chars']:
            self.assertTrue(result['content_excerpted'])
        for key in ('id', 'title', 'url', 'type'):
            self.assertEqual(result[key], original[key])
        return selection

    def test_unique_tail_fact_is_available_instead_of_only_page_head(self):
        fact = 'Warm-start latency is exactly 73 milliseconds under the documented recovery protocol.'
        source = self.public(('Navigation, legal notices, contact information.\n' * 400) + fact)
        query = 'warm-start latency recovery'
        result = answer_sources([source], query=query, per_source=500, total_chars=500)[0]
        self.assertIn(fact, result['content'])
        selection = self.assert_selection(source, result, query, budget=500)
        self.assertEqual(selection['reason'], 'query_match')
        self.assertTrue(any(item['end'] == len(source['content']) for item in selection['ranges']))

    def test_chinese_question_finds_its_unique_fact(self):
        fact = '语义检索可以匹配近义表达，但资料不足时必须说明回答边界。'
        source = self.public(('页面目录与联系说明。\n' * 500) + fact)
        query = '语义检索的回答边界'
        result = answer_sources([source], query=query, per_source=500, total_chars=500)[0]
        self.assertIn(fact, result['content'])
        self.assertEqual(self.assert_selection(source, result, query, budget=500)['reason'], 'query_match')

    def test_english_terms_are_case_insensitive(self):
        fact = 'Quasar telemetry is retained for seven days before deletion.'
        source = self.public(('Account menu, navigation and introductory notes.\n' * 300) + fact)
        query = 'QUASAR TELEMETRY'
        result = answer_sources([source], query=query, per_source=500, total_chars=500)[0]
        self.assertIn(fact, result['content'])
        self.assertEqual(self.assert_selection(source, result, query, budget=500)['reason'], 'query_match')

    def test_mixed_chinese_and_english_question_keeps_actual_evidence(self):
        fact = 'RAG 的召回边界取决于已有资料，缺少依据时应说明限制。'
        source = self.public(('帮助导航与联络方式。\n' * 450) + fact)
        query = 'RAG 召回边界'
        result = answer_sources([source], query=query, per_source=500, total_chars=500)[0]
        self.assertIn(fact, result['content'])
        self.assert_selection(source, result, query, budget=500)

    def test_different_questions_select_different_facts_from_same_page(self):
        first = 'ALPHA rollback restores the prior checkpoint without deleting learning history.'
        second = 'OMEGA archival preserves saved cards while hiding the old conversation.'
        text = ('Introductory navigation.\n' * 180) + first + ('\nUnrelated appendix material.\n' * 250) + second
        source = self.public(text)
        results = []
        for query, expected, excluded in [('ALPHA rollback', first, 'OMEGA archival'),
                                          ('OMEGA archival', second, 'ALPHA rollback')]:
            with self.subTest(query=query):
                result = answer_sources([source], query=query, per_source=500, total_chars=500)[0]
                self.assertIn(expected, result['content'])
                self.assertNotIn(excluded, result['content'])
                self.assert_selection(source, result, query, budget=500)
                results.append(result)
        self.assertNotEqual(results[0]['content'], results[1]['content'])
        self.assertNotEqual(results[0]['source_selection']['query_hash'], results[1]['source_selection']['query_hash'])

    def test_long_single_paragraph_can_select_a_middle_match(self):
        fact = '星河协议的重试上限为七次，超过后必须报告失败。'
        source = self.public(('与当前问题无关的前置说明。' * 900) + fact + ('普通附录及导航信息。' * 900))
        query = '星河协议重试上限'
        result = answer_sources([source], query=query, per_source=500, total_chars=500)[0]
        self.assertIn(fact, result['content'])
        self.assertEqual(self.assert_selection(source, result, query, budget=500)['reason'], 'query_match')

    def test_long_single_paragraph_can_select_a_tail_match(self):
        fact = 'Bluefin checkpoint expires after nine idle days.'
        source = self.public(('Unrelated prose without any paragraph delimiter. ' * 600) + fact)
        query = 'Bluefin checkpoint'
        result = answer_sources([source], query=query, per_source=500, total_chars=500)[0]
        self.assertIn(fact, result['content'])
        self.assert_selection(source, result, query, budget=500)

    def test_single_source_budget_counts_the_rendered_projection(self):
        source = self.public(('Ordinary page contents.\n' * 400) + 'AURORA retries are bounded by a documented limit.')
        query = 'AURORA retries'
        for per_source, total in [(180, 700), (700, 180), (500, 500)]:
            with self.subTest(per_source=per_source, total=total):
                result = answer_sources([source], query=query, per_source=per_source, total_chars=total)[0]
                self.assert_selection(source, result, query, budget=min(per_source, total))

    def test_total_budget_includes_every_public_source_and_separator(self):
        sources = [self.public(('Generic navigation text.\n' * 350) + f'CAPSTONE source {index} documents recovery.', f'page-{index}')
                   for index in range(3)]
        query = 'CAPSTONE recovery'
        results = answer_sources(sources, query=query, per_source=260, total_chars=510)
        self.assertEqual(len(results), len(sources))
        self.assertLessEqual(sum(len(source['content']) for source in results), 510)
        for original, result in zip(sources, results):
            self.assert_selection(original, result, query, budget=260)

    def test_no_match_fallback_is_explicit_and_preserves_exact_source_text(self):
        source = self.public('菜单导航与普通附录说明。\n' * 400)
        query = 'ZEBRACODE RETENTION'
        result = answer_sources([source], query=query, per_source=240, total_chars=240)[0]
        selection = self.assert_selection(source, result, query, budget=240)
        self.assertEqual(selection['reason'], 'no_match_fallback')
        self.assertGreater(selection['selected_chars'], 0)
        self.assertTrue(all(item['reason'] == 'no_match_fallback' for item in selection['ranges']))

    def test_empty_question_is_an_explicit_fallback_not_a_relevance_claim(self):
        source = self.public('普通来源文字与附录。\n' * 400)
        result = answer_sources([source], query='', per_source=240, total_chars=240)[0]
        selection = self.assert_selection(source, result, '', budget=240)
        self.assertEqual(selection['reason'], 'no_query_fallback')
        self.assertGreater(selection['selected_chars'], 0)

    def test_short_source_is_full_provided_text_and_keeps_existing_excerpt_flag(self):
        text = '已读取的资料片段，不承诺整页已读。'
        for excerpted in (False, True):
            with self.subTest(already_excerpted=excerpted):
                source = self.public(text, content_excerpted=excerpted)
                result = answer_sources([source], query='整页', per_source=500, total_chars=500)[0]
                self.assertEqual(result['content'], text)
                self.assertEqual(result['content_excerpted'], excerpted)
                selection = self.assert_selection(source, result, '整页', budget=500)
                self.assertEqual(selection['reason'], 'full')
                self.assertEqual(selection['omitted_chars'], 0)

    def test_projection_and_nested_metadata_do_not_mutate_original_sources(self):
        source = self.public(('Documentation and notes.\n' * 300) + 'DELTA ownership survives a restart.',
                             read_details=dict(reader='local', warnings=['transport excerpt']))
        originals = [source]
        before = copy.deepcopy(originals)
        result = answer_sources(originals, query='DELTA ownership', per_source=500, total_chars=500)
        self.assertEqual(originals, before)
        self.assertIsNot(result, originals)
        self.assertIsNot(result[0], originals[0])
        result[0]['read_details']['warnings'].append('projection-only edit')
        self.assertEqual(originals, before, 'a later prompt projection cannot rewrite durable read metadata')
        self.assertNotIn('source_selection', originals[0])

    def test_user_material_and_other_source_types_are_not_trimmed_or_charged(self):
        protected = [dict(id='material', type='user_material', content='用户完整资料。' * 1200,
                          details=dict(tags=['keep'])),
                     dict(id='generated', type='agent_generated', content='完整学习记录。' * 1000)]
        public = self.public('公开来源正文与附录。' * 500)
        sources = [protected[0], public, protected[1]]
        result = answer_sources(sources, query='', per_source=160, total_chars=160)
        self.assertEqual(result[0], protected[0])
        self.assertEqual(result[2], protected[1])
        self.assertNotIn('source_selection', result[0])
        self.assertNotIn('source_selection', result[2])
        selection = self.assert_selection(public, result[1], '', budget=160)
        self.assertGreater(selection['selected_chars'], 0, 'protected material does not consume the public excerpt allowance')

    def test_zero_budget_is_empty_and_explained_without_touching_user_material(self):
        source = self.public('需要保留来源身份的公开正文。' * 50)
        material = dict(id='material', type='user_material', content='用户资料必须完整保留。' * 20)
        for per_source, total in [(100, 0), (0, 100), (0, 0)]:
            with self.subTest(per_source=per_source, total=total):
                result = answer_sources([source, material], query='公开正文', per_source=per_source, total_chars=total)
                self.assertEqual(result[1], material)
                selection = self.assert_selection(source, result[0], '公开正文', budget=0)
                self.assertEqual(selection['reason'], 'budget_exhausted')
                self.assertEqual(selection['ranges'], [])
                self.assertEqual(selection['selected_chars'], 0)
                self.assertEqual(selection['omitted_chars'], len(source['content']))

    def test_empty_inputs_remain_valid_projections(self):
        self.assertEqual(answer_sources([], query='anything'), [])
        for source in (self.public(''), dict(id='no-text', type='public_source', title='Empty', url='https://example.test/empty')):
            with self.subTest(source=source['id']):
                result = answer_sources([source], query='anything', per_source=500, total_chars=500)[0]
                selection = self.assert_selection(source, result, 'anything', budget=500)
                self.assertEqual(result['content'], '')
                self.assertEqual(selection['ranges'], [])
                self.assertEqual(selection['selected_chars'], 0)
                self.assertEqual(selection['omitted_chars'], 0)

    def test_identical_inputs_produce_identical_content_ranges_and_metadata(self):
        source = self.public(('Document navigation.\n' * 320) + 'STABLE lease duration is exactly four hours.')
        query = 'STABLE lease duration'
        first = answer_sources([source], query=query, per_source=500, total_chars=500)
        for _ in range(3):
            self.assertEqual(answer_sources(copy.deepcopy([source]), query=query, per_source=500, total_chars=500), first)
        self.assert_selection(source, first[0], query, budget=500)

    def test_duplicate_public_identity_does_not_undercharge_incremental_packet_budget(self):
        source = self.public('CAPSTONE recovery details.\n' * 600, source_id='duplicate', version=1)
        sources = [copy.deepcopy(source), copy.deepcopy(source),
                   self.public('CAPSTONE recovery details.\n' * 600, 'other-one', source_id='one', version=1),
                   self.public('CAPSTONE recovery details.\n' * 600, 'other-two', source_id='two', version=1)]
        before = copy.deepcopy(sources)
        harness = InMemoryProjectionHarness()
        initial = harness.project(sources[:2], stage='assessment')
        self.assertEqual(len(initial), 1)
        for results in (answer_sources(sources, query='CAPSTONE recovery'), harness.project(sources)):
            self.assertEqual(len(results), 3)
            self.assertEqual(len({s['source_id'] for s in results}), 3)
            self.assertEqual(sum(len(s['content']) for s in results), 12_000)
            self.assertTrue(all(len(s['content']) <= 4_000 for s in results))
        entries = harness.data['runs']['run']['source_selection_packet']['entries']
        self.assertEqual(sum(value['selection']['projected_chars'] for value in entries.values()), 12_000)
        self.assertEqual(sources, before)

    def test_repeated_object_references_are_copied_without_projection_aliases(self):
        source = self.public('CAPSTONE recovery details.\n' * 600, source_id='shared', version=1)
        material = dict(id='material', type='user_material', content='完整用户资料。' * 1200,
                        details=dict(tags=['preserve']))
        sources = [source, source, material, material]
        before = copy.deepcopy(sources)
        for selector in (answer_sources, InMemoryProjectionHarness().project):
            with self.subTest(selector=selector.__name__):
                result = selector(sources, query='CAPSTONE recovery')
                self.assertEqual(len(result), 3)
                self.assert_selection(source, result[0], 'CAPSTONE recovery', budget=4_000)
                self.assertEqual(result[1], material)
                self.assertEqual(result[2], material)
                self.assertIsNot(result[1], result[2])
                result[1]['details']['tags'].append('projection-only edit')
                self.assertEqual(result[2], material)
                self.assertEqual(sources, before)

    def test_same_public_identity_keeps_newest_version_and_last_body_at_equal_version(self):
        old = self.public('Outdated body without the current requirement.\n' * 500,
                          source_id='shared', version=1)
        revised = self.public('CAPSTONE recovery requires explicit acknowledgement.\n' * 500,
                              source_id='shared', version=2)
        replacement = self.public('CAPSTONE recovery now requires a visible scope check.\n' * 500,
                                  source_id='shared', version=1)
        for sources, expected in (([old, revised], revised), ([revised, old], revised),
                                  ([old, replacement], replacement), ([replacement, old], old)):
            for selector in (answer_sources, InMemoryProjectionHarness().project):
                with self.subTest(versions=[s['version'] for s in sources],
                                  expected=expected['content'][:40], selector=selector.__name__):
                    before = copy.deepcopy(sources)
                    result = selector(sources, query='CAPSTONE recovery')
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0]['version'], expected['version'])
                    self.assert_selection(expected, result[0], 'CAPSTONE recovery', budget=4_000)
                    self.assertEqual(sources, before)
