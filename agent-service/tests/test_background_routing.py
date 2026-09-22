"""Background is conversational context, not permission to create a course."""
import copy
import unittest

from tests import test_conversation_v2 as f
from agent_service.dialogue_routing import POLICY_VERSION
from agent_service.schemas import ConversationOutput, IntentDecision, TeachingPreparation


BACKGROUND = '我在准备ai产品经理的面试'
ACKNOWLEDGEMENT = '了解，你在准备 AI 产品经理面试。想先聚焦技术原理还是产品案例？'


def background(**kwargs):
    return f.intent('social', conversation_kind='background', answer_only=True,
                    light_reply=ACKNOWLEDGEMENT, **kwargs)


class BackgroundRoutingTests(unittest.TestCase):
    def setUp(self):
        self.f = f.ConversationTests()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def test_identity_then_background_does_not_create_a_goal_or_location_choice(self):
        for text, decision in [
            ('嘿', f.intent('greeting', light_reply='你好，我是学习教练。')),
            ('你知道我是谁吗', f.intent('capabilities', light_reply='目前没有你的身份信息。可以告诉我一些背景。')),
            (BACKGROUND, background().model_copy(update={'relation': 'new_topic'})),
        ]:
            self.f.decision = decision
            accepted = self.f.send(text)
            state = self.f.state()
            self.assertEqual(state['runs'][accepted.run_id]['status'], 'completed')
            self.assertFalse(state.get('focus_goal'))
            self.assertFalse(state['tasks'])
            self.assertIsNone(state['pending'])
        self.assertEqual(state['messages'][-1]['content'], ACKNOWLEDGEMENT)
        self.assertFalse(any(s in {TeachingPreparation, ConversationOutput} for s, _ in self.f.calls))
        self.f.capture.assert_not_called()

    def test_original_identity_question_cannot_become_session_goal(self):
        self.f.decision = f.intent('question', answer_only=True)
        self.f.send('你知道我是谁吗')
        self.assertFalse(self.f.state().get('focus_goal'))
        self.f.decision = background()
        self.f.send(BACKGROUND)
        prompt = [p for s, p in self.f.calls if s is IntentDecision][-1]
        self.assertEqual(prompt['session_goal'], '')
        self.assertFalse(self.f.state()['tasks'])

    def test_conversation_scope_blocks_goal_label_even_with_workflow(self):
        for workflow in (None, 'topic_exploration'):
            with self.subTest(workflow=workflow):
                self.f.sid = str(f.uuid.uuid4())
                self.f.decision = f.intent('goal', scope='conversation', workflow=workflow)
                self.f.send(BACKGROUND)
                self.assertFalse(self.f.state()['tasks'])
                self.assertIsNone(self.f.state()['pending'])

    def test_missing_background_reply_uses_context_without_teaching_preparation(self):
        self.f.decision = background().model_copy(update={'light_reply': ''})
        self.f.send(BACKGROUND)
        prompts = [p for s, p in self.f.calls if s is ConversationOutput]
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]['context']['current_inputs'], [BACKGROUND])
        self.assertIn('已知在准备面试', prompts[0]['instruction'])
        self.assertFalse(any(s is TeachingPreparation for s, _ in self.f.calls))
        self.assertFalse(self.f.state()['tasks'])
        self.assertIsNone(next(iter(self.f.state()['runs'].values()))['activity_kind'])

    def test_legacy_chat_focus_does_not_block_first_explicit_learning_request(self):
        self.f.send('嘿')
        with self.f.store.transaction(self.f.sid) as data:
            data['focus_goal'] = '你知道我是谁吗'
        self.f.decision = f.intent('goal', scope='learning', workflow='source_learning', direct_teaching=True
            ).model_copy(update={'relation': 'new_topic'})
        self.f.send('请带我学习 RAG 的原理，不用搜索')
        state = self.f.state()
        self.assertIsNone(state['pending'])
        self.assertEqual(len(state['tasks']), 1)
        self.assertEqual(state['tasks'][state['active_task_id']]['stage'], 'teaching')
        prompt = [p for s, p in self.f.calls if s is IntentDecision][-1]
        self.assertEqual(prompt['session_goal'], '')

    def test_background_does_not_change_a_real_learning_task(self):
        self.f.decision = f.intent('goal', workflow='source_learning', direct_teaching=True)
        self.f.send('带我学习 RAG')
        before = copy.deepcopy(self.f.state())
        self.f.decision = background().model_copy(update={'relation': 'new_topic'})
        self.f.send(BACKGROUND)
        after = self.f.state()
        for key in ('tasks', 'active_task_id', 'pending', 'draft', 'focus_goal'):
            self.assertEqual(after[key], before[key], key)

    def test_background_with_question_keeps_the_actual_question(self):
        self.f.decision = f.intent('social', 'question', conversation_kind='ordinary', answer_only=True)
        self.f.send(BACKGROUND + '，RAG 是什么？')
        state = self.f.state()
        self.assertFalse(state['tasks'])
        self.assertNotIn('social_reply_kind', next(iter(state['runs'].values())))
        self.assertTrue(any(s is ConversationOutput for s, _ in self.f.calls))

    def test_clarification_uses_known_purpose_and_only_asks_missing_information(self):
        self.f.decision = f.intent('goal', workflow='topic_exploration', target_description='准备 AI 产品经理面试')
        self.f.send('请安排 AI 产品经理面试学习，先帮我确定具体方向')
        state = self.f.state()
        task = state['tasks'][state['active_task_id']]
        self.assertEqual(task['stage'], 'clarify_goal')
        prompt = next(p for s, p in self.f.calls if s is ConversationOutput)
        self.assertIn('AI 产品经理面试', prompt['context']['task']['content'])
        self.assertIn('不得再问学完要做什么', prompt['instruction'])
        self.assertEqual(state['messages'][-1]['content'], '这是本轮真实回答。')
        self.assertFalse(task['context'].get('check_question'))

    def test_reply_to_an_existing_goal_clarification_can_continue_learning(self):
        self.f.decision = f.intent('goal', workflow='topic_exploration')
        self.f.send('请帮我确定面试学习方向')
        tid = self.f.state()['active_task_id']
        self.f.decision = f.intent('continue', scope='continue_goal', workflow='source_learning',
            target_task_id=tid, learning_goal_ready=True, direct_teaching=True)
        self.f.send('AI 产品经理面试里的 RAG 部分，请先讲基础')
        self.assertEqual(self.f.state()['active_task_id'], tid)
        self.assertEqual(self.f.state()['tasks'][tid]['stage'], 'teaching')

    def test_old_location_button_only_resolves_location_not_learning_permission(self):
        accepted = self.f.send('嘿')
        legacy = f.intent('goal', scope='conversation').model_dump()
        with self.f.store.transaction(self.f.sid) as data:
            data['pending'] = dict(kind='new_session', target_id=accepted.run_id, version=1,
                content=BACKGROUND, decision=legacy)
            data['focus_goal'] = '你知道我是谁吗'
        self.f.send('继续放在这里', operation=dict(kind='continue_session', target_id=accepted.run_id, version=1))
        state = self.f.state()
        self.assertIsNone(state['pending'])
        self.assertFalse(state['tasks'])
        self.assertFalse(state.get('focus_goal'))
        prompt = [p for s, p in self.f.calls if s is ConversationOutput][-1]
        self.assertEqual(prompt['context']['current_inputs'], [BACKGROUND])
        self.assertEqual(prompt['context']['session_goal'], '')

    def test_proven_legacy_location_misroute_is_retired_without_rewriting_messages(self):
        self.f.decision = f.intent('goal', workflow='topic_exploration')
        accepted = self.f.send(BACKGROUND)
        with self.f.store.transaction(self.f.sid) as data:
            task = data['tasks'][data['active_task_id']]
            tid = task['task_id']
            data['runs'][accepted.run_id].update(intent=f.intent('goal', scope='conversation').model_dump(),
                resolved_input=BACKGROUND)
            original = next(m for m in data['messages'] if m['message_id'] == task['client_message_id'])
            original.update(content='继续放在这里', operation={'kind': 'continue_session'})
        original_messages = copy.deepcopy(self.f.state()['messages'])
        self.f.decision = background()
        self.f.send('我就是补充一下自己的背景')
        state = self.f.state()
        self.assertEqual(state['tasks'][tid]['status'], 'cancelled')
        self.assertEqual(state['tasks'][tid]['stage'], 'routing_corrected')
        self.assertIsNone(state['active_task_id'])
        self.assertEqual(state['messages'][:len(original_messages)], original_messages)
        prompt = [p for s, p in self.f.calls if s is IntentDecision][-1]
        self.assertIsNone(prompt['task'])
        self.assertEqual(prompt['session_goal'], '')

    def test_old_unfinished_intent_is_rejudged_but_current_policy_can_be_reused(self):
        for policy in (None, POLICY_VERSION):
            with self.subTest(policy=policy):
                self.f.sid = str(f.uuid.uuid4())
                self.f.calls.clear()
                accepted = self.f.send(BACKGROUND, drain=False)
                with self.f.store.transaction(self.f.sid) as data:
                    run = data['runs'][accepted.run_id]
                    run.update(intent=background().model_dump(), decision_input_ids=list(run['input_ids']),
                        decision_mode='auto', judgment_policy=None, dialogue_policy=policy)
                self.f.decision = background()
                self.f.harness.drain(self.f.sid)
                self.assertEqual(any(s is IntentDecision for s, _ in self.f.calls), policy is None)
                self.assertFalse(self.f.state()['tasks'])
                self.assertEqual(self.f.state()['messages'][-1]['content'], ACKNOWLEDGEMENT)
