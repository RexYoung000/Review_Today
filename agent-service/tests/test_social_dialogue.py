"""A012: semantic routes, state isolation, mixed requests and old checkpoints."""
import copy
import unittest
from unittest.mock import patch

from tests import test_conversation_v2 as fixtures
from tests.test_m1_capture_contract import committing_result
from agent_service.schemas import ConversationOutput, IntentDecision
from agent_service.social_dialogue import kind_for


class SocialDialogueTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ConversationTests()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def social(self, kind="companionship", *names, **kwargs):
        return fixtures.intent(*(names or ("social",)), conversation_kind=kind, **kwargs)

    def assert_no_learning_effects(self, accepted):
        state = self.f.state()
        run = state['runs'][accepted.run_id]
        self.assertEqual(run['status'], 'completed')
        self.assertIsNone(run.get('activity_kind'))
        self.assertFalse(run.get('learning_concepts'))
        self.assertEqual(run.get('search_state'), 'not_called')
        self.assertFalse(state['tasks'])
        self.assertFalse(state.get('capture_offers'))
        self.f.capture.assert_not_called()

    def test_pure_social_all_modes_uses_only_router_without_goals_or_tools(self):
        for mode in fixtures.LABELS:
            for kind, names, text, reply in [
                ('social', ('greeting',), '你好', '你好。'),
                ('social', ('thanks',), '谢谢', '不客气。'),
                ('social', ('social',), '今天有点累', '累了就先歇一歇。'),
                ('companionship', ('social',), '你可以陪我说说话吗', '随便聊什么都行，我一直陪你。'),
                ('companionship', ('social', 'defer'), '今天不想学，只想随便聊', '那接着上课吧？'),
            ]:
                with self.subTest(mode=mode, kind=kind, text=text):
                    self.f.sid = str(fixtures.uuid.uuid4())
                    self.f.calls.clear()
                    self.f.decision = self.social(kind, *names, light_reply=reply)
                    with patch.object(self.f.harness, '_prepare_teaching', side_effect=AssertionError('no teaching/tools')):
                        result = self.f.send(text, mode=mode)
                    self.assertEqual([s for s, _ in self.f.calls], [IntentDecision])
                    self.assert_no_learning_effects(result)
                    if kind == 'social':
                        self.assertEqual(self.f.state()['messages'][-1]['content'], reply)
                    else:
                        self.assertNotEqual(self.f.state()['messages'][-1]['content'], reply)
                        self.assertNotIn('？', self.f.state()['messages'][-1]['content'])

    def test_history_remains_but_does_not_leak_into_companionship(self):
        self.f.decision = fixtures.intent('question', answer_only=True)
        for text in ('我上次说了什么', '真的吗', '你再看看'):
            self.f.send(text)
        history = copy.deepcopy(self.f.state()['messages'])
        self.f.decision = self.social(light_reply='我只能看到本窗口记录，再早的看不到。想聊什么都行。')
        self.f.calls.clear()
        self.f.send('可以陪我说说话吗')
        state = self.f.state()
        self.assertEqual(state['messages'][:len(history)], history)
        self.assertEqual(state['messages'][-1]['content'], '我在。可以聊聊学习中遇到的困惑，或者最近想弄明白的事。')
        self.assertEqual([s for s, _ in self.f.calls], [IntentDecision])

    def test_greeting_and_thanks_do_not_repeat_identity_or_learning_invitation(self):
        for name, text, expected in [('greeting', '你好', '你好。'), ('thanks', '谢谢', '不客气。')]:
            self.f.decision = self.social('social', name, light_reply='我是你的学习教练，想学习什么随时找我。')
            self.f.send(text)
            self.assertEqual(self.f.state()['messages'][-1]['content'], expected)

    def test_greeting_how_are_you_and_response_feedback_use_existing_entry_reply(self):
        turns = [
            ('你好', self.social('social', 'greeting', light_reply='你好，很高兴见到你。'), '你好，很高兴见到你。'),
            ('你好吗', self.social('social', 'greeting', light_reply='我在，谢谢你的问候。今天想聊点什么？'), '我在，谢谢你的问候。'),
            ('为什么你只会回我这句话', fixtures.intent('question', reply_feedback='response_only',
                light_reply='抱歉，刚才的回应太生硬了。我会回应你问的具体内容。'), '抱歉，刚才的回应太生硬了。我会回应你问的具体内容。'),
        ]
        with patch.object(self.f.harness, '_prepare_teaching', side_effect=AssertionError('no teaching preparation')):
            for text, decision, expected in turns:
                self.f.decision = decision
                result = self.f.send(text)
                self.assertEqual(self.f.state()['messages'][-1]['content'], expected)
                self.assert_no_learning_effects(result)
        self.assertEqual([s for s, _ in self.f.calls], [IntentDecision] * 3)
        self.assertTrue(self.f.state()['runs'][result.run_id]['reply_feedback_handled'])

    def test_valid_thanks_and_usable_sentence_survive_without_fixed_replacement(self):
        for text, intent_name, reply, expected in [
            ('谢谢刚才的解释', 'thanks', '能帮上忙就好。', '能帮上忙就好。'),
            ('你好吗', 'greeting', '我在，谢谢关心。想学什么随时找我。', '我在，谢谢关心。'),
            ('你好吗', 'greeting', '我在呢，谢谢你的问候。有想弄明白的知识点或学习上的事，随时说。', '我在呢，谢谢你的问候。'),
            ('你好', 'greeting', '', '你好。'),
            ('你好', 'greeting', '无效' * 100, '你好。'),
        ]:
            with self.subTest(text=text, reply=reply):
                self.f.decision = self.social('social', intent_name, light_reply=reply)
                self.f.send(text)
                self.assertEqual(self.f.state()['messages'][-1]['content'], expected)

    def test_reply_feedback_preserves_active_learning_state_and_rejects_blame(self):
        self.f.decision = fixtures.intent('question', scope='learning', workflow='problem_solving')
        self.f.send('学习 RAG', mode='problem_solving')
        with self.f.store.transaction(self.f.sid) as state:
            state['draft'] = dict(id=state['active_task_id'], version=1, content='已有草稿', understanding='unknown')
            state['pending'] = dict(kind='save', target_id=state['active_task_id'], version=1)
        before = copy.deepcopy(self.f.state())
        self.f.decision = fixtures.intent('question', reply_feedback='response_only',
            light_reply='抱歉，刚才回应太机械。你没给我可回的东西。想学什么随时找我。')
        with patch.object(self.f.harness, '_prepare_teaching', side_effect=AssertionError('no teaching')):
            accepted = self.f.send('你怎么总是重复', mode='problem_solving')
        after = self.f.state()
        for key in ('tasks', 'active_task_id', 'pending', 'draft', 'focus_goal', 'teaching_context'):
            self.assertEqual(before.get(key), after.get(key), key)
        self.assertEqual(after['messages'][-1]['content'], '抱歉，刚才回应太机械。')
        self.assertEqual(after['messages'][:len(before['messages'])], before['messages'])
        self.assertTrue(after['runs'][accepted.run_id]['reply_feedback_handled'])

    def test_feedback_with_knowledge_is_answered_and_control_is_not_swallowed(self):
        self.f.decision = fixtures.intent('question', reply_feedback='with_request', answer_only=True,
                                         light_reply='这条短回复不能吞掉知识问题。')
        text = '别再只回你好了，请用一句话解释 RAG'
        accepted = self.f.send(text)
        answers = [p for s, p in self.f.calls if s is ConversationOutput]
        self.assertIn(text, str(answers[-1]))
        self.assertNotIn('reply_feedback_handled', self.f.state()['runs'][accepted.run_id])
        self.assertFalse(self.f.state()['tasks'])
        for name in ('stop', 'pause', 'defer'):
            self.f.decision = fixtures.intent(name, reply_feedback='response_only', light_reply='抱歉，我会调整。')
            accepted = self.f.send('别再重复，' + {'stop':'停止', 'pause':'暂停学习', 'defer':'晚点再学'}[name])
            self.assertNotIn('reply_feedback_handled', self.f.state()['runs'][accepted.run_id])

    def test_old_unfinished_intent_without_feedback_is_reclassified(self):
        old = fixtures.intent('question').model_dump()
        old.pop('reply_feedback')
        self.assertEqual(IntentDecision.model_validate(old).reply_feedback, 'none')
        accepted = self.f.send('你的回复太生硬', drain=False)
        with self.f.store.transaction(self.f.sid) as data:
            run = data['runs'][accepted.run_id]
            run.update(intent=old, decision_input_ids=list(run['input_ids']), decision_mode=data['mode'])
        self.f.decision = fixtures.intent('question', reply_feedback='response_only', light_reply='收到，我会回应得更自然些。')
        self.f.harness.drain(self.f.sid)
        self.assertTrue(self.f.state()['runs'][accepted.run_id]['reply_feedback_handled'])
        self.assertEqual([s for s, _ in self.f.calls], [IntentDecision])

    def test_repeated_companionship_does_not_repeat_boundary_or_ask_for_topic(self):
        self.f.decision = self.social()
        self.f.send('陪我聊聊')
        first = self.f.state()['messages'][-1]['content']
        self.f.send('就随便聊聊嘛')
        second = self.f.state()['messages'][-1]['content']
        self.assertNotEqual(first, second)
        self.assertNotIn('？', second)
        self.assertNotIn('学习教练', second)
        self.assertFalse(self.f.state()['tasks'])

    def test_existing_task_pending_and_draft_are_not_modified_by_social_or_support(self):
        self.f.decision = fixtures.intent('question', scope='learning', workflow='problem_solving')
        self.f.send('学习 RAG', mode='problem_solving')
        with self.f.store.transaction(self.f.sid) as state:
            state['draft'] = dict(id=state['active_task_id'], version=1, content='已有草稿', understanding='unknown')
            state['pending'] = dict(kind='save', target_id=state['active_task_id'], version=1)
        before = copy.deepcopy(self.f.state())
        for kind, names, text in [('social', ('social',), '今天有点累'),
                                  ('companionship', ('social',), '陪我聊聊'),
                                  ('learning_support', ('question',), '总是学完就忘，有点挫败')]:
            self.f.decision = self.social(kind, *names, target_task_id=before['active_task_id'], scope='continue_goal')
            self.f.send(text, mode='problem_solving')
            after = self.f.state()
            for key in ('active_task_id', 'tasks', 'pending', 'draft', 'focus_goal', 'teaching_context'):
                self.assertEqual(before.get(key), after.get(key), (kind, key))
        self.f.capture.assert_not_called()

    def test_support_uses_coach_but_discards_plan_grades_and_sources(self):
        self.f.decision = self.social('learning_support', 'question')
        with patch.object(self.f.harness, '_prepare_teaching', side_effect=AssertionError('no teaching/tools')):
            result = self.f.send('复习记不住，帮我调整一下心态')
        self.assertEqual([s for s, _ in self.f.calls], [IntentDecision, ConversationOutput])
        self.assert_no_learning_effects(result)
        self.assertNotIn('请用自己的话', self.f.state()['messages'][-1]['content'])
        self.f.decision = fixtures.intent('self_report', understanding='self_reported', topic_closure=dict(
            title='复习', evidence='明白了', message_ids=[self.f.state()['messages'][-1]['message_id']]))
        self.f.send('明白了')
        self.assertFalse(self.f.state().get('capture_offers'), 'support is not a knowledge segment')

    def test_support_request_with_defer_is_helped_without_resuming_lesson(self):
        self.f.decision = self.social('learning_support', 'social', 'defer')
        with patch.object(self.f.harness, '_prepare_teaching', side_effect=AssertionError('no teaching')):
            result = self.f.send('我学不进去，先不继续课了，只给点调整状态的建议')
        self.assertEqual([s for s, _ in self.f.calls], [IntentDecision, ConversationOutput])
        self.assertEqual(self.f.state()['runs'][result.run_id]['social_reply_kind'], 'learning_support')
        self.assert_no_learning_effects(result)

    def test_mixed_emotion_and_question_still_answers_without_forced_training(self):
        for kind in ('ordinary', 'social', 'companionship'):
            self.f.sid = str(fixtures.uuid.uuid4())
            self.f.calls.clear()
            self.f.decision = self.social(kind, 'social', 'question', workflow='topic_exploration', scope='learning')
            self.f.send('今天很烦，顺便解释一下 RAG')
            self.assertTrue(any(s is ConversationOutput for s, _ in self.f.calls))
            self.assertFalse(self.f.state()['tasks'])
            self.assertNotIn('social_reply_kind', list(self.f.state()['runs'].values())[-1])

    def test_social_label_cannot_swallow_control_confirmation_resume_or_actual_answer(self):
        for name in ('stop', 'pause', 'cancel', 'queue', 'confirm', 'reject', 'continue', 'answer', 'goal', 'material'):
            with self.subTest(name=name):
                self.assertIsNone(kind_for(self.social('companionship', 'social', name), {}))
        for props in (dict(conversation_repair=True), dict(reply_feedback='response_only'), dict(direct_teaching=True),
                      dict(continuation_evidence='继续上次学习'), dict(requested_mode='source_learning'),
                      dict(proposed_actions=[dict(kind='save', disposition='request', evidence='保存')]),
                      dict(programming_boundary='capability_question')):
            self.assertIsNone(kind_for(self.social(**props), {}))
        self.assertIsNone(kind_for(self.social(), dict(operation={'kind': 'capture_save'})))

    def test_stop_defer_and_continue_behaviour_survives_a_social_label(self):
        self.f.decision = fixtures.intent('question', scope='learning', workflow='problem_solving')
        self.f.send('学习 RAG', mode='problem_solving')
        before = copy.deepcopy(self.f.state()['tasks'])
        self.f.decision = self.social('companionship', 'defer')
        self.f.send('算了，晚点再学吧')
        self.assertEqual(before, self.f.state()['tasks'])
        self.assertIn('歇一歇', self.f.state()['messages'][-1]['content'])
        self.f.decision = self.social('companionship', 'stop')
        stopped = self.f.send('停止')
        self.assertEqual(self.f.state()['runs'][stopped.run_id]['status'], 'interrupted')
        self.f.decision = fixtures.intent('continue', scope='continue_goal', conversation_kind='companionship')
        self.f.calls.clear()
        self.f.send('继续学习', mode='problem_solving')
        self.assertTrue(any(s is ConversationOutput for s, _ in self.f.calls))

    def test_bound_save_keeps_version_checks_despite_social_words(self):
        self.f.decision = fixtures.intent('question')
        self.f.send('解释 RAG')
        answer = self.f.state()['messages'][-1]
        self.f.decision = fixtures.intent('self_report', understanding='self_reported', topic_closure=dict(
            evidence='明白了', title='RAG', message_ids=[answer['message_id']]))
        self.f.send('明白了')
        offer = next(iter(self.f.state()['capture_offers'].values()))
        self.f.decision = self.social('social', 'thanks')
        self.f.send('谢谢，录入吧', operation=dict(kind='capture_save', target_id=offer['id'], version=offer['version']+1))
        self.f.capture.assert_not_called()
        self.f.capture.return_value = committing_result(offer['draft']['content'])
        self.f.send('谢谢，录入吧', operation=dict(kind='capture_save', target_id=offer['id'], version=offer['version']))
        self.f.capture.assert_called_once()

    def test_legacy_intent_is_readable_but_unfinished_cached_intent_is_reclassified(self):
        old = fixtures.intent('question').model_dump()
        old.pop('conversation_kind')
        self.assertEqual(IntentDecision.model_validate(old).conversation_kind, 'ordinary')
        result = self.f.send('陪我随便聊聊', drain=False)
        with self.f.store.transaction(self.f.sid) as state:
            run = state['runs'][result.run_id]
            run.update(intent=old, decision_input_ids=list(run['input_ids']), decision_mode=state['mode'])
        self.f.decision = self.social()
        self.f.harness.drain(self.f.sid)
        self.assertEqual([s for s, _ in self.f.calls], [IntentDecision])
        self.assertEqual(self.f.state()['runs'][result.run_id]['social_reply_kind'], 'companionship')

    def test_support_failure_retry_keeps_bounded_path_and_existing_progress(self):
        from agent_service.openai_client import ModelCallError
        self.f.decision = self.social('learning_support', 'question')
        def fail(system, user, schema, **kwargs):
            if schema is ConversationOutput:
                raise ModelCallError('TIMEOUT')
            return self.f.model(system, user, schema, **kwargs)
        with patch('agent_service.conversation.parse_model', side_effect=fail):
            result = self.f.send('学不进去，怎么办')
        self.assertEqual(self.f.state()['runs'][result.run_id]['status'], 'retryable_failed')
        self.f.control(result.run_id, 'retry')
        self.f.calls.clear()
        self.f.harness.drain(self.f.sid)
        self.assertEqual([s for s, _ in self.f.calls], [ConversationOutput])
        self.assert_no_learning_effects(result)


if __name__ == '__main__':
    unittest.main()
