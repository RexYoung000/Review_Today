"""Real Harness preparation and failover; only model/HTTP transports are replaced."""
import json
import os
import unittest
from unittest.mock import Mock, patch

from tests import test_conditional_teaching as fixture
from tests.test_conversation_v2 import intent
from agent_service import web_resilience as policy, web_tools as web
from agent_service.call_errors import WebToolError
from agent_service.schemas import EvidenceAssessmentV2, SourceList, TeachingPreparation
from agent_service.source_content import PageRead

OLD = ['https://old.example/specification', 'https://old.example/second', 'https://old.example/third']
NEW = ['https://current.example/specification', 'https://current.example/second']


class QualityFallbackTests(unittest.TestCase):
    setUpFixture = fixture.ConditionalTeachingTests.setUp
    tearDown = fixture.ConditionalTeachingTests.tearDown
    send = fixture.ConditionalTeachingTests.send
    state = fixture.ConditionalTeachingTests.state
    control = fixture.ConditionalTeachingTests.control

    def setUp(self):
        self.setUpFixture()
        self.statuses = ['insufficient', 'supported']
        self.assessments, self.selections = [], []
        self.reject_first = False
        self.fabricate_second = False
        self.after_assessment = None
        self.domains = []
        self.env = patch.dict(os.environ, dict(REVIEW_TODAY_SEARCH_PROVIDER='deepseek',
            REVIEW_TODAY_SEARCH_FALLBACKS='exa,tavily', REVIEW_TODAY_READ_PROVIDER='exa',
            REVIEW_TODAY_READ_FALLBACKS='tavily,deepseek', REVIEW_TODAY_BROWSER_FALLBACK='0',
            REVIEW_TODAY_CONTEXT_PROVIDER='none'))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.states = patch.object(policy, '_states', {})
        self.states.start()
        self.addCleanup(self.states.stop)
        self.backends = {}
        for name, urls in [('deepseek', OLD), ('exa', NEW), ('tavily', ['https://unused.example/specification'])]:
            backend = Mock()
            backend.name = name
            backend.search.return_value = [web.SearchResult(u, 'Public specification') for u in urls]
            backend.read.side_effect = lambda url, **kw: ('Public specification', 'Synthetic public specification: ' + url)
            self.backends[name] = backend
        factory = patch.object(web, '_backend', side_effect=self.backends.__getitem__)
        factory.start()
        self.addCleanup(factory.stop)
        self.decision = intent('question', needs_verification=True, public_search_query='public specification')

    def model(self, system, user, schema, **kwargs):
        if schema is TeachingPreparation:
            return TeachingPreparation(public_query='public specification', source_domains=self.domains)
        if schema is SourceList:
            data = json.loads(user)
            self.selections.append(data)
            if len(self.selections) == 1 and self.reject_first:
                return SourceList()
            urls = [item['url'] for item in data['search']]
            if len(self.selections) == 2 and self.fabricate_second:
                urls = ['https://invented.example/not-returned']
            return SourceList(candidates=[dict(url=url, title='Public specification') for url in urls[:3]])
        if schema is EvidenceAssessmentV2:
            data = json.loads(user)
            self.assessments.append(data)
            state = self.statuses[min(len(self.assessments) - 1, len(self.statuses) - 1)]
            if self.after_assessment:
                self.after_assessment()
            return EvidenceAssessmentV2(state=state, summary='Synthetic applicable scope: ' + state,
                sources=[s['url'] for s in data['sources']])
        return fixture.ConditionalTeachingTests.model(self, system, user, schema, **kwargs)

    def run_question(self):
        result = self.send('请查证当前公开规范的适用范围')
        return self.state()['runs'][result.run_id]

    def test_insufficient_body_switches_search_once_and_keeps_exa_reading_first(self):
        run = self.run_question()
        self.assertEqual(run['search_state'], 'verified')
        self.assertEqual(run['quality_supplement']['after_provider'], 'deepseek')
        self.assertEqual([len(x['sources']) for x in self.assessments], [1, 2])
        self.assertEqual(len(self.selections), 2)
        self.backends['deepseek'].search.assert_called_once()
        self.backends['exa'].search.assert_called_once()
        self.assertEqual(self.backends['exa'].search.call_args.args[0], 'public specification')
        self.backends['tavily'].search.assert_not_called()
        self.assertEqual(self.backends['exa'].read.call_count, 2)
        self.backends['deepseek'].read.assert_not_called()
        self.assertEqual(policy.provider_state('deepseek').until, 0)

    def test_selection_and_assessment_receive_full_question_and_missing_scope(self):
        self.domains = ['old.example', 'current.example']
        question = '请按当前正式官方文档，说明必需前提和失败后的处理方式；仅给名称不够。'
        result = self.send(question)
        self.assertEqual(self.state()['runs'][result.run_id]['search_state'], 'verified')
        self.assertEqual([x['question'] for x in self.selections], [question, question])
        self.assertEqual([x['question'] for x in self.assessments], [question, question])
        self.assertEqual(self.selections[1]['previous_evidence']['state'], 'insufficient')
        self.assertEqual(self.selections[1]['attempted_urls'], OLD[:1])
        # The web service still sees the minimal public topic, not the question.
        for name in ['deepseek', 'exa']:
            self.assertEqual(self.backends[name].search.call_args.args[0],
                'public specification site:old.example OR site:current.example')
            self.assertTrue(self.selections[0]['official_sources_required'])

    def test_supported_even_old_source_stops_without_quality_search(self):
        self.statuses = ['supported']
        run = self.run_question()
        self.assertNotIn('quality_supplement', run)
        self.assertEqual(len(self.assessments), 1)
        self.backends['exa'].search.assert_not_called()

    def test_two_insufficient_assessments_do_not_reset_quotas_for_third_provider(self):
        self.statuses = ['insufficient']
        run = self.run_question()
        self.assertEqual(run['search_state'], 'insufficient')
        self.assertEqual([len(x['sources']) for x in self.assessments], [1, 2])
        self.assertEqual(self.backends['exa'].read.call_count, 2)
        self.backends['tavily'].search.assert_not_called()

    def test_conflicting_evidence_is_retained_without_quality_search(self):
        self.statuses = ['conflicting']
        run = self.run_question()
        self.assertEqual(run['search_state'], 'conflicting')
        self.assertNotIn('quality_supplement', run)
        self.backends['exa'].search.assert_not_called()
        self.assertEqual(len(self.assessments), 2)

    def test_failed_supplement_preserves_partial_scope(self):
        self.statuses = ['scoped']
        for name in ['exa', 'tavily']:
            self.backends[name].search.side_effect = WebToolError('READ_FAILED')
        run = self.run_question()
        self.assertEqual(run['teaching_evidence']['state'], 'scoped')
        self.assertEqual(run['teaching_evidence']['summary'], 'Synthetic applicable scope: scoped')
        self.assertEqual(len(self.assessments), 1)
        self.assertEqual(len(run['teaching_sources']), 1)

    def test_no_suitable_candidates_can_supplement_before_any_body(self):
        self.reject_first = True
        self.statuses = ['supported']
        run = self.run_question()
        self.assertEqual(run['quality_supplement']['reason'], 'no_usable_source')
        self.assertEqual(run['search_state'], 'verified')
        self.assertEqual(self.backends['exa'].read.call_count, 1)
        self.assertEqual(len(self.assessments), 1)

    def test_unreadable_first_results_can_supplement_without_treating_snippets_as_body(self):
        self.backends['deepseek'].search.return_value = [web.SearchResult(OLD[0], 'Public specification')]
        def read(url, **kw):
            if url in OLD:
                raise WebToolError('READ_FAILED')
            return 'Specification', 'Readable synthetic specification.'
        for backend in self.backends.values():
            backend.read.side_effect = read
        self.statuses = ['supported']
        run = self.run_question()
        self.assertEqual(run['search_state'], 'verified')
        self.assertEqual([s['url'] for s in run['teaching_sources']], NEW[:1])
        self.assertEqual(len(self.assessments), 1)

    def test_supplemented_candidates_still_need_exact_returned_urls(self):
        self.fabricate_second = True
        run = self.run_question()
        self.assertEqual(run['search_state'], 'insufficient')
        self.assertEqual(self.backends['exa'].read.call_count, 1)
        self.assertEqual(len(self.assessments), 1)
        self.assertNotIn('https://invented.example/not-returned', str(run.get('answer_sources')))

    def test_cross_check_shares_three_reads_two_assessments_and_independence_guard(self):
        self.decision = self.decision.model_copy(update={'cross_check_sources': True})
        run = self.run_question()
        self.assertEqual(run['search_state'], 'verified')
        self.assertEqual([len(x['sources']) for x in self.assessments], [2, 3])
        self.assertEqual(self.backends['exa'].read.call_count, 3)
        self.backends['tavily'].search.assert_not_called()

    def test_cancel_during_supplement_stops_before_next_provider(self):
        self.backends['exa'].search.side_effect = WebToolError('CANCELLED')
        run = self.run_question()
        self.assertNotEqual(run['status'], 'completed')
        self.backends['tavily'].search.assert_not_called()

    def test_tool_round_budget_is_not_reset_for_quality_search(self):
        self.after_assessment = lambda: setattr(policy.active_round.get(), 'calls', policy.ROUND_CALLS)
        run = self.run_question()
        self.assertEqual(run['search_state'], 'insufficient')
        self.backends['exa'].search.assert_not_called()
        self.assertEqual(len(self.assessments), 1)

    def test_page_without_observed_redirect_keeps_requested_url(self):
        self.backends['exa'].read.side_effect = None
        self.backends['exa'].read.return_value = PageRead('Specification', 'Readable synthetic body.',
            details=dict(provider='deepseek', requested_url=OLD[0], content_kind='page_text'))
        self.statuses = ['supported']
        run = self.run_question()
        self.assertEqual(run['search_state'], 'verified')
        self.assertEqual(run['teaching_sources'][0]['url'], OLD[0])
        self.assertNotIn('final_url', run['teaching_sources'][0]['read_details'])

    def test_two_empty_searches_remain_stopped_after_cached_result_reuse(self):
        self.backends['deepseek'].search.return_value = []
        self.backends['exa'].search.return_value = []
        with policy.web_round_scope():
            result = web.web_search_text('public specification')
        self.assertEqual(json.loads(result)['empty_searches'], 2)
        with policy.web_round_scope():
            self.assertEqual(web.quality_fallback_after(result), '')
        self.backends['tavily'].search.assert_not_called()

    def test_cancelled_round_with_empty_allowance_spent_still_reports_cancellation(self):
        with policy.web_round_scope() as state:
            state.empty_searches = 2
            with self.assertRaisesRegex(WebToolError, 'CANCELLED'):
                web.web_search_text('public specification', on_cancel_handle=lambda cancel: cancel())
        for backend in self.backends.values():
            backend.search.assert_not_called()

    def test_empty_allowance_is_shared_across_quality_and_error_failover(self):
        brave = Mock()
        brave.name = 'brave'
        self.backends['brave'] = brave
        self.backends['deepseek'].search.return_value = []
        self.backends['tavily'].search.return_value = []
        with patch.dict(os.environ, {'REVIEW_TODAY_SEARCH_FALLBACKS': 'exa,tavily,brave'}), policy.web_round_scope():
            first = web.web_search_text('public specification')
            self.assertEqual(json.loads(first)['provider'], 'exa')
            result = web.web_search_text('public specification', after_provider='exa')
            self.assertEqual(json.loads(result)['empty_searches'], 2)
            self.assertEqual(web.quality_fallback_after(result), '')
        brave.search.assert_not_called()

    def test_unstructured_or_unconfigured_provider_does_not_enable_supplement(self):
        for result in ['https://old.example', json.dumps(dict(protocol=web.PROTOCOL, provider='unknown', results=[]))]:
            self.assertEqual(web.quality_fallback_after(result), '')
        with patch.dict(os.environ, {'REVIEW_TODAY_SEARCH_PROVIDER': 'none'}):
            self.assertEqual(web.provider_chain('search', after_provider='deepseek'), [])
