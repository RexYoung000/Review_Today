"""Independent questions must not replace a live learning goal's evidence."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from tests import test_conversation_v2 as f
from agent_service.call_errors import WebToolError
from agent_service.openai_client import ModelCallError
from agent_service.schemas import ConversationOutput, EvidenceAssessmentV2, SourceList


class CaptureBoundary(BaseException):
    pass


class IndependentQuestionSourcesTests(unittest.TestCase):
    def setUp(self):
        self.f = f.ConversationTests()
        self.f.setUp()
        self.url = 'https://example.com/http'
        self.output = 'HTTP 的幂等性表示相同请求重复执行，预期效果与执行一次相同。'

    def tearDown(self):
        self.f.tearDown()

    def seed(self):
        self.f.decision = f.intent('goal', scope='learning', workflow='source_learning', direct_teaching=True)
        self.f.send('请分步骤教我 RAG，并检查我的理解。', mode='source_learning')
        state = self.f.state()
        self.tid = state['active_task_id']
        self.f.decision = f.intent('answer', scope='continue_goal', target_task_id=self.tid)
        self.f.send('RAG 先检索相关资料，再依据资料生成回答。')
        self.before = deepcopy(self.f.state())
        self.offer = deepcopy(next(iter(self.before['capture_offers'].values())))
        self.assertEqual(self.offer['trigger'], 'verified_check')
        self.assertTrue(self.before['tasks'][self.tid]['context']['sources'])

    def independent(self, **kwargs):
        self.f.decision = f.intent('question', scope='conversation', answer_only=True, conversation_kind='ordinary',
            **kwargs).model_copy(update={'relation': 'new_topic'})
        return self.f.send('顺便问一下，HTTP 幂等性是什么意思？原来的 RAG 先保留。')

    def model(self, system, user, schema, **kwargs):
        if schema is SourceList:
            return SourceList(candidates=[dict(url=self.url, title='HTTP', reason='受控公开资料')])
        if schema is EvidenceAssessmentV2:
            return EvidenceAssessmentV2(state='supported', summary='当前资料支持该说明。', sources=[self.url])
        if issubclass(schema, ConversationOutput):
            import json
            self.f.calls.append((schema, json.loads(user)))
            return ConversationOutput(message=self.output, learning_concepts=['HTTP 幂等性'])
        return self.f.model(system, user, schema, **kwargs)

    def answer_inputs(self, start=0):
        return [p for schema, p in self.f.calls[start:] if issubclass(schema, ConversationOutput)]

    def assert_goal_preserved(self):
        state = self.f.state()
        self.assertEqual(state['active_task_id'], self.tid)
        self.assertEqual(state['tasks'], self.before['tasks'])
        self.assertEqual(state['capture_offers'], self.before['capture_offers'])
        self.assertEqual(state['draft'], self.before['draft'])
        self.assertEqual(state['pending'], self.before['pending'])
        self.assertEqual(state['mode'], 'source_learning')
        self.f.capture.assert_not_called()

    def test_independent_question_without_search_preserves_goal_and_frozen_offer(self):
        self.seed()
        with patch('agent_service.conversation.parse_model', side_effect=self.model), \
                patch('agent_service.conversation.web_search_text') as search:
            accepted = self.independent()
        self.assertEqual(self.f.state()['runs'][accepted.run_id]['status'], 'completed')
        self.assertEqual(self.answer_inputs()[-1]['sources'], [])
        self.assert_goal_preserved()
        search.assert_not_called()

    def test_independent_verified_page_belongs_to_question_and_does_not_replace_goal(self):
        self.seed()
        with patch('agent_service.conversation.parse_model', side_effect=self.model), \
                patch('agent_service.conversation.web_search_text', return_value=self.url), \
                patch('agent_service.conditional_teaching.fetch_public_url', return_value=('HTTP', self.output)):
            accepted = self.independent(needs_verification=True, public_search_query='HTTP idempotency')
        run = self.f.state()['runs'][accepted.run_id]
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['search_state'], 'verified')
        self.assertEqual([s['url'] for s in self.answer_inputs()[-1]['sources']], [self.url])
        self.assertEqual([s['url'] for s in run['answer_sources']], [self.url])
        self.assert_goal_preserved()

    def test_independent_search_failure_does_not_replace_goal_evidence(self):
        self.seed()
        with patch('agent_service.conversation.parse_model', side_effect=self.model), \
                patch('agent_service.conversation.web_search_text', side_effect=ModelCallError('CONNECTION')):
            accepted = self.independent(needs_verification=True, public_search_query='HTTP idempotency')
        self.assertEqual(self.f.state()['runs'][accepted.run_id]['search_state'], 'failed')
        self.assert_goal_preserved()

    def test_independent_unreadable_page_does_not_fall_back_to_goal_sources(self):
        self.seed()
        with patch('agent_service.conversation.parse_model', side_effect=self.model), \
                patch('agent_service.conversation.web_search_text', return_value=self.url), \
                patch('agent_service.conditional_teaching.fetch_public_url', side_effect=WebToolError('CONNECTION')):
            accepted = self.independent(needs_verification=True, public_search_query='HTTP idempotency')
        run = self.f.state()['runs'][accepted.run_id]
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['search_state'], 'insufficient')
        self.assertEqual(self.answer_inputs()[-1]['sources'], [])
        self.assert_goal_preserved()

    def test_independent_format_repair_keeps_goal_untouched_on_both_attempts(self):
        self.seed()
        attempts = []

        def repair(system, user, schema, **kwargs):
            if issubclass(schema, ConversationOutput):
                attempts.append(user)
                if len(attempts) == 1:
                    raise ModelCallError('SCHEMA', 'json_invalid/non_json')
            return self.model(system, user, schema, **kwargs)

        with patch('agent_service.conversation.parse_model', side_effect=repair):
            accepted = self.independent()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(self.f.state()['runs'][accepted.run_id]['status'], 'completed')
        self.assert_goal_preserved()

    def test_return_to_goal_uses_original_sources_after_independent_verified_question(self):
        self.seed()
        with patch('agent_service.conversation.parse_model', side_effect=self.model), \
                patch('agent_service.conversation.web_search_text', return_value=self.url), \
                patch('agent_service.conditional_teaching.fetch_public_url', return_value=('HTTP', self.output)):
            self.independent(needs_verification=True, public_search_query='HTTP idempotency')
        self.f.decision = f.intent('followup', scope='continue_goal', target_task_id=self.tid, answer_only=True)
        accepted = self.f.send('回到原来的 RAG，请再解释原讲义里的例子，不推进。')
        self.assertEqual(self.f.state()['runs'][accepted.run_id]['status'], 'completed')
        self.assertEqual(self.answer_inputs()[-1]['sources'], self.before['tasks'][self.tid]['context']['sources'])
        self.assertEqual(self.f.state()['tasks'][self.tid]['context']['learning_plan'],
                         self.before['tasks'][self.tid]['context']['learning_plan'])
        self.assertEqual(self.f.state()['capture_offers'], self.before['capture_offers'])

    def test_same_goal_refresh_still_updates_goal_sources(self):
        self.seed()
        self.f.decision = f.intent('followup', scope='continue_goal', target_task_id=self.tid, answer_only=True,
            needs_verification=True, refresh_sources=True, public_search_query='RAG retrieval')
        self.url = 'https://example.com/rag'
        self.output = 'RAG 先检索相关资料，再依据资料生成回答。'
        with patch('agent_service.conversation.parse_model', side_effect=self.model), \
                patch('agent_service.conversation.web_search_text', return_value=self.url), \
                patch('agent_service.conditional_teaching.fetch_public_url', return_value=('RAG', self.output)):
            accepted = self.f.send('请核对刚才 RAG 的资料。')
        state = self.f.state()
        self.assertEqual(state['runs'][accepted.run_id]['status'], 'completed')
        self.assertIn(self.url, [s['url'] for s in state['tasks'][self.tid]['context']['sources']])
        self.assertEqual(state['tasks'][self.tid]['context']['learning_plan'],
                         self.before['tasks'][self.tid]['context']['learning_plan'])

    def test_actual_new_learning_goal_keeps_session_choice(self):
        self.seed()
        self.f.decision = f.intent('goal', scope='learning', workflow='source_learning', direct_teaching=True,
            target_description='HTTP').model_copy(update={'relation': 'new_topic'})
        self.f.send('我想换成系统学习 HTTP，请从第一步教起。')
        state = self.f.state()
        self.assertEqual(state['pending']['kind'], 'new_session')
        self.assertEqual(state['tasks'], self.before['tasks'])
        self.assertEqual(state['active_task_id'], self.tid)

    def test_bound_save_after_independent_question_keeps_frozen_input(self):
        self.seed()
        with patch('agent_service.conversation.parse_model', side_effect=self.model):
            self.independent()
        count = len(self.f.calls)
        seen = []

        def before_capture(commit_id, content, language, **kwargs):
            state = self.f.state()
            self.assertEqual(content, self.offer['draft']['content'])
            self.assertEqual(state['draft'], self.offer['draft'])
            self.assertEqual(state['tasks'][commit_id]['context']['sources'], self.offer['sources'])
            seen.append(commit_id)
            raise CaptureBoundary()

        self.f.capture.side_effect = before_capture
        with self.assertRaises(CaptureBoundary):
            self.f.send('capture_save', operation=dict(kind='capture_save', target_id=self.offer['id'],
                                                       version=self.offer['version']))
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(self.f.calls), count)
        self.assertFalse(self.f.state()['tasks'][seen[0]]['memory_package'])
