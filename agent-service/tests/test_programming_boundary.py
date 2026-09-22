"""A005: controlled routing; real semantic classification is tested separately."""
import copy
import unittest
from tests import test_conversation_v2 as fixtures
from agent_service.schemas import IntentDecision, ConversationOutput
from agent_service.scope_reply import ScopeReply


class ProgrammingBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ConversationTests()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def decision(self, boundary, *intents, **kwargs):
        # model_copy also lets the pre-fix implementation reproduce the failure.
        return fixtures.intent(*(intents or ('capabilities',)), **kwargs).model_copy(
            update={'programming_boundary': boundary})

    def test_capability_question_cannot_publish_unbounded_model_promise(self):
        self.f.decision = self.decision('capability_question', light_reply='可以，我能替你写完整项目并运行调试。')
        result = self.f.send('你能帮我 coding 嘛')
        state = self.f.state()
        self.assertIn('不能直接替你完成', state['messages'][-1]['content'])
        self.assertNotIn('？', state['messages'][-1]['content'])
        self.assertNotIn('运行调试', state['messages'][-1]['content'])
        self.assertEqual(state['runs'][result.run_id]['status'], 'completed')
        self.assertEqual([s for s, _ in self.f.calls], [IntentDecision, ScopeReply])
        self.assertFalse(state['tasks'])
        self.assertFalse(state.get('capture_offers'))
        self.f.capture.assert_not_called()

    def test_development_delivery_does_not_start_learning_in_any_mode(self):
        for mode in fixtures.LABELS:
            with self.subTest(mode=mode):
                self.f.sid = str(fixtures.uuid.uuid4())
                self.f.decision = self.decision('development_delivery', 'goal', scope='learning',
                    workflow='problem_solving', target_description='交付完整应用', direct_teaching=True)
                before = len(self.f.calls)
                self.f.send('帮我改仓库、跑测试并部署整个项目', mode=mode)
                state = self.f.state()
                self.assertFalse(state['tasks'])
                self.assertFalse(state.get('focus_goal'))
                self.assertFalse(state.get('pending'))
                self.assertIn('不能直接替你完成', state['messages'][-1]['content'])
                self.assertEqual([s for s, _ in self.f.calls[before:]], [IntentDecision, ScopeReply])

    def test_boundary_keeps_existing_progress_and_pending_state(self):
        self.f.decision = fixtures.intent('question', scope='learning', workflow='problem_solving')
        self.f.send('学习 RAG', mode='problem_solving')
        before = copy.deepcopy(self.f.state())
        task = before['active_task_id']
        self.f.decision = self.decision('development_delivery', 'goal', scope='continue_goal', target_task_id=task)
        self.f.send('帮我直接改好项目')
        after = self.f.state()
        for key in ('active_task_id', 'tasks', 'pending', 'draft', 'focus_goal', 'capture_offers'):
            self.assertEqual(before.get(key), after.get(key), key)
        self.f.capture.assert_not_called()

    def test_learning_examples_explanations_and_quoted_requests_still_reach_coach(self):
        for text in ('用十行 Python 示例教我循环', '解释这段代码的报错原理',
                     '不要代写项目，只讲重构的思路', '解释这句话的意思：“帮我改仓库并部署”'):
            with self.subTest(text=text):
                self.f.sid = str(fixtures.uuid.uuid4())
                self.f.decision = self.decision('none', 'question', answer_only=True)
                before = len(self.f.calls)
                self.f.send(text)
                self.assertTrue(any(s is ConversationOutput for s, _ in self.f.calls[before:]))

    def test_defer_and_stop_keep_priority_over_conflicting_boundary(self):
        self.f.decision = self.decision('development_delivery', 'defer')
        self.f.send('算了，暂时不学 coding 了')
        self.assertEqual(self.f.state()['messages'][-1]['content'], '好的，你慢慢想。准备好后继续。')
        self.f.decision = self.decision('development_delivery', 'stop')
        result = self.f.send('停止')
        self.assertEqual(self.f.state()['runs'][result.run_id]['status'], 'interrupted')

    def test_old_intent_schema_is_readable(self):
        self.assertEqual(fixtures.intent('question').programming_boundary, 'none')

    def test_old_cached_decision_is_reclassified_before_reply(self):
        self.f.decision = self.decision('capability_question')
        result = self.f.send('你能帮我 coding 嘛', drain=False)
        with self.f.store.transaction(self.f.sid) as data:
            run = data['runs'][result.run_id]
            old = fixtures.intent('capabilities', light_reply='可以，我帮你开发完整项目。').model_dump()
            old.pop('programming_boundary', None)
            run.update(intent=old, decision_input_ids=list(run['input_ids']), decision_mode=data['mode'])
        self.f.harness.drain(self.f.sid)
        self.assertIn('不能直接替你完成', self.f.state()['messages'][-1]['content'])
        self.assertEqual([s for s, _ in self.f.calls], [IntentDecision, ScopeReply])

    def test_deferred_capture_survives_capability_question(self):
        self.f.decision = fixtures.intent('question')
        self.f.send('讲解 Python 循环')
        answer = self.f.state()['messages'][-1]
        self.f.decision = fixtures.intent('self_report', understanding='self_reported',
            topic_closure=dict(evidence='明白了', title='循环', message_ids=[answer['message_id']]))
        self.f.send('明白了')
        offer = next(iter(self.f.state()['capture_offers'].values()))
        self.f.send('稍后录入', operation=dict(kind='capture_later', target_id=offer['id'], version=offer['version']))
        before = copy.deepcopy(self.f.state())
        self.assertEqual(before['capture_offers'][offer['id']]['status'], 'deferred')
        self.f.decision = self.decision('capability_question')
        self.f.send('你能帮我 coding 吗')
        after = self.f.state()
        self.assertEqual(before['capture_offers'], after['capture_offers'])
        self.assertEqual(before.get('draft'), after.get('draft'))
        self.f.capture.assert_not_called()

    def test_mixed_request_only_explains_verbatim_learning_part(self):
        self.f.decision = self.decision('mixed_learning', 'goal', scope='learning',
            workflow='problem_solving', programming_learning_request='先解释闭包原理')
        self.f.send('先解释闭包原理，再帮我把项目部署上线')
        outputs = [p for s, p in self.f.calls if s is ConversationOutput]
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]['context']['current_inputs'], ['先解释闭包原理'])
        self.assertIn('不执行', outputs[0]['instruction'])
        self.assertFalse(self.f.state()['tasks'])
        self.assertFalse(self.f.state().get('capture_offers'))
        self.f.capture.assert_not_called()

    def test_mixed_request_without_valid_excerpt_cannot_start_delivery(self):
        for excerpt in ('', '用户没有提出的学习问题', '解释闭包并部署'):
            self.f.sid = str(fixtures.uuid.uuid4())
            self.f.decision = self.decision('mixed_learning', 'goal', programming_learning_request=excerpt)
            before = len(self.f.calls)
            self.f.send('解释闭包并部署')
            self.assertEqual([s for s, _ in self.f.calls[before:]], [IntentDecision, ScopeReply])
            self.assertFalse(self.f.state()['tasks'])

    def test_mixed_learning_preserves_existing_task_and_retries_learning(self):
        from unittest.mock import patch
        from agent_service.openai_client import ModelCallError
        self.f.decision = fixtures.intent('question', scope='learning', workflow='problem_solving')
        self.f.send('学习 RAG', mode='problem_solving')
        before = copy.deepcopy(self.f.state()['tasks'])
        self.f.decision = self.decision('mixed_learning', 'goal', programming_learning_request='解释闭包')
        def fail_answer(system, user, schema, **kwargs):
            if schema is ConversationOutput:
                raise ModelCallError('TIMEOUT')
            return self.f.model(system, user, schema, **kwargs)
        with patch('agent_service.conversation.parse_model', side_effect=fail_answer):
            result = self.f.send('解释闭包，再帮我部署项目')
        self.assertEqual(self.f.state()['runs'][result.run_id]['status'], 'retryable_failed')
        self.f.control(result.run_id, 'retry')
        self.f.harness.drain(self.f.sid)
        state = self.f.state()
        self.assertEqual(state['runs'][result.run_id]['status'], 'completed')
        outputs = [p for s, p in self.f.calls if s is ConversationOutput]
        self.assertEqual(outputs[-1]['context']['current_inputs'], ['解释闭包'])
        self.assertIsNone(outputs[-1]['context']['task'])
        self.assertEqual(before, state['tasks'])
