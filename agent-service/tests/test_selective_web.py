"""A011: demand-driven web policy, bounded evidence, and truthful live phases."""
import json
import unittest
from unittest.mock import patch
from tests import test_conditional_teaching as fixture
from tests.test_conversation_v2 import intent
from agent_service.schemas import TeachingPreparation, SourceList, EvidenceAssessmentV2, ConversationOutput
from agent_service.call_errors import WebToolError
from agent_service.web_resilience import web_round_scope


class SelectiveWebTests(unittest.TestCase):
    setUp = fixture.ConditionalTeachingTests.setUp
    tearDown = fixture.ConditionalTeachingTests.tearDown
    send = fixture.ConditionalTeachingTests.send
    state = fixture.ConditionalTeachingTests.state
    model = fixture.ConditionalTeachingTests.model

    def test_new_concept_and_stray_public_query_do_not_force_search(self):
        # The preparation fixture returns both a new concept and a safe query.
        for query in ('', 'RAG'):
            with self.subTest(query=query), patch('agent_service.conversation.web_search_text') as search:
                self.decision = intent('question', public_search_query=query).model_copy(update={'relation':'new_topic'})
                result = self.send('RAG 是什么，有什么作用')
                run = self.state()['runs'][result.run_id]
                self.assertEqual(run['search_state'], 'not_called')
                self.assertEqual(run['status'], 'completed')
                self.assertEqual(run['verification_notice'], '')
                search.assert_not_called()
                self.assertNotIn('[!NOTE]', self.state()['messages'][-1]['content'])

    def test_explicit_learning_is_not_automatic_web_authorization(self):
        self.decision = intent('goal', scope='learning', workflow='topic_exploration', direct_teaching=True, learning_goal_ready=True)
        with patch('agent_service.conversation.web_search_text') as search:
            result = self.send('带我系统学习 RAG，用于理解基本原理，直接开始')
        self.assertTrue(self.state()['tasks'])
        self.assertEqual(self.state()['runs'][result.run_id]['status'], 'completed')
        search.assert_not_called()

    def test_stable_percentage_explanation_is_not_risk_keyword_search(self):
        self.decision = intent('question')
        with patch('agent_service.conversation.web_search_text') as search:
            result = self.send('数学里的 10% 是什么意思')
        self.assertEqual(self.state()['runs'][result.run_id]['search_state'], 'not_called')
        search.assert_not_called()

    def test_cross_check_single_source_does_not_claim_verified(self):
        self.decision = intent('question', needs_verification=True, cross_check_sources=True)
        with patch('agent_service.conversation.web_search_text', return_value='https://example.com/rag'), patch('agent_service.conditional_teaching.fetch_public_url', return_value=('原始文档', '检索再生成')):
            result = self.send('请交叉核验这个说法')
        run = self.state()['runs'][result.run_id]
        self.assertEqual(run['search_state'], 'insufficient')
        self.assertIn('两个独立来源', run['verification_notice'])

    def test_cancelled_read_is_not_swallowed_as_optional_source_failure(self):
        self.decision = intent('question', needs_verification=True)
        with patch('agent_service.conversation.web_search_text', return_value='https://example.com/rag'), patch('agent_service.conditional_teaching.fetch_public_url', side_effect=WebToolError('CANCELLED')), patch('agent_service.web_tools.web_context_pages') as recovery:
            result = self.send('请查证 RAG')
        run = self.state()['runs'][result.run_id]
        self.assertNotEqual(run['status'], 'completed')
        self.assertFalse(run.get('teaching_sources'))
        recovery.assert_not_called()

    def progressive(self, states, *, cross=False, same_host=False):
        urls = ['https://example.com/rag', 'https://example.com/second' if same_host else 'https://other.org/rag', 'https://third.org/rag']
        assessments = []
        original = self.model
        def model(system, user, schema, **kwargs):
            if schema is SourceList:
                return SourceList(candidates=[dict(url=u, title='原始资料') for u in urls])
            if schema is EvidenceAssessmentV2:
                sources = json.loads(user)['sources']
                assessments.append(len(sources))
                return EvidenceAssessmentV2(state=states[min(len(assessments)-1, len(states)-1)], summary='支持范围', sources=[s['url'] for s in sources])
            return original(system, user, schema, **kwargs)
        self.decision = intent('question', needs_verification=True, cross_check_sources=cross)
        with patch('agent_service.conversation.parse_model', side_effect=model), patch('agent_service.conversation.web_search_text', return_value=' '.join(urls)) as search, patch('agent_service.conditional_teaching.fetch_public_url', return_value=('原始资料', '检索再生成')) as fetch:
            result = self.send('请查证 RAG 的原理')
        return self.state()['runs'][result.run_id], fetch.call_count, assessments

    def test_first_supported_source_stops_additional_reads(self):
        run, count, assessed = self.progressive(['supported'])
        self.assertEqual((count, assessed, run['search_state']), (1, [1], 'verified'))

    def test_insufficient_first_source_reads_next_then_stops(self):
        run, count, assessed = self.progressive(['insufficient', 'supported'])
        self.assertEqual((count, assessed, run['search_state']), (2, [1, 2], 'verified'))

    def test_cross_check_reads_two_origins_before_assessing(self):
        run, count, assessed = self.progressive(['supported'], cross=True)
        self.assertEqual((count, assessed, run['search_state']), (2, [2], 'verified'))

    def test_two_pages_on_same_host_do_not_satisfy_cross_check(self):
        run, count, assessed = self.progressive(['supported'], cross=True, same_host=True)
        self.assertEqual((count, assessed, run['search_state']), (3, [3], 'verified'))

    def test_no_search_answer_cannot_invent_clickable_reference(self):
        original = self.model
        def model(system, user, schema, **kw):
            if schema is ConversationOutput:
                return ConversationOutput(message='基础知识。[伪造来源](https://invented.example/source)', evidence_state='unverified')
            return original(system, user, schema, **kw)
        self.decision = intent('question')
        with patch('agent_service.conversation.parse_model', side_effect=model):
            result = self.send('什么是检索')
        self.assertNotIn('https://invented.example', self.state()['messages'][-1]['content'])
        self.assertEqual(self.state()['runs'][result.run_id]['allowed_source_urls'], [])

    def test_telemetry_retains_current_phase_but_remains_in_details(self):
        self.decision = intent('greeting', light_reply='你好')
        result = self.send('你好')
        with self.harness.store.transaction(self.sid) as state:
            run = state['runs'][result.run_id]
            event = self.harness.store.event
            event(state, run, 'source_candidates', '正在选择相关来源')
            event(state, run, 'model_attempt', '正在处理当前步骤')
            event(state, run, 'model_attempt_failed', '本次模型调用未完成', error='RT.MODEL.SCHEMA')
            self.assertIsNone(run.get('error_code'))
            event(state, run, 'source_candidates', '本步骤已完成', duration_ms=100)
            self.assertEqual(run['user_summary'], '正在选择相关来源')
            event(state, run, 'web_provider', '正在读取网页正文', payload={'status':'started'})
            event(state, run, 'web_provider', '网页工具运行详情', payload={'status':'succeeded'})
            self.assertEqual(run['user_summary'], '正在读取网页正文')
            self.assertEqual(state['events'][-1]['user_summary'], '网页工具运行详情')

    def test_round_budget_override_and_nested_reuse(self):
        with web_round_scope(seconds=30) as state:
            with web_round_scope() as nested:
                self.assertIs(state, nested)
                self.assertEqual(nested.seconds, 30)
            state.spent = 30
            with self.assertRaises(WebToolError):
                state.check()
        with web_round_scope() as state:
            self.assertEqual(state.seconds, 60)
