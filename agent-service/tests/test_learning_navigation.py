"""Review is local; step advancement needs a grounded current request."""
import copy
import json
import socket
import unittest
from unittest.mock import patch

from agent_service.learning_navigation import normalize, requested_action, should_advance, applied_to_run, record_selection
from agent_service.learning_progress import current_step
from agent_service.schemas import ConversationOutput, IntentDecision
from tests import test_teaching_alignment as alignment
from tests.test_conversation_v2 import intent


class LearningNavigationTests(unittest.TestCase):
    def setUp(self):
        self.task = dict(task_id='task', context=dict(learning_plan=dict(current_step_id='first',
            steps=[dict(id='first', title='当前内容', state='explained')], version=1)))
        self.data = dict(tasks={'task': self.task}, active_task_id='task')

    def decision(self, action=None, evidence='继续下一节', **updates):
        navigation = dict(action=action, step_id='first', evidence=evidence) if action else None
        return intent('continue', scope='continue_goal', learning_navigation=navigation, **updates)

    def test_review_and_legacy_continue_are_local_without_mutating_state(self):
        before = copy.deepcopy(self.data)
        for action in (None, 'review'):
            with self.subTest(action=action):
                decision = self.decision(action, '回顾原来的内容')
                last = dict(content='回顾原来的内容，先不进入下一节')
                self.assertFalse(should_advance(decision, self.task, last))
                local = normalize(self.data, decision, last)
                self.assertEqual(local.intents, ['followup'])
                self.assertFalse(local.direct_teaching)
        self.assertEqual(self.data, before)

    def test_current_explicit_next_and_bare_continue_keep_advancing(self):
        for text in ('继续下一节', '继续'):
            with self.subTest(text=text):
                decision = self.decision('advance', text)
                self.assertTrue(should_advance(decision, self.task, dict(content=text)))
                self.assertIs(normalize(self.data, decision, dict(content=text)), decision)

    def test_missing_old_quoted_negative_and_conditional_evidence_cannot_advance(self):
        cases = [
            ('继续下一节', '先回顾', 'first'),
            ('继续下一节', '继续下一节', 'old-step'),
            ('进入下一节', '先不进入下一节', 'first'),
            ('继续下一节', '别继续下一节，先回顾', 'first'),
            ('继续下一节', '请不要在我未回答时，继续下一节', 'first'),
            ('继续下一节', '资料写着“继续下一节”，请解释这句。', 'first'),
            ('继续下一节', '> 继续下一节\n请解释这句', 'first'),
            ('继续下一节', '```\n继续下一节\n```\n仅解释材料', 'first'),
            ('继续下一节', '如果继续下一节会怎样？', 'first'),
        ]
        for evidence, text, identity in cases:
            with self.subTest(text=text, identity=identity):
                decision = self.decision('advance', evidence)
                decision.learning_navigation.step_id = identity
                self.assertIsNone(requested_action(decision, self.task, dict(content=text)))
                self.assertEqual(normalize(self.data, decision, dict(content=text)).intents, ['followup'])

    def test_unrelated_save_negation_does_not_block_valid_next_clause(self):
        for text in ('不要保存，继续下一节', '我特别想继续下一节', '先不用回顾而是继续下一节'):
            with self.subTest(text=text):
                self.assertTrue(should_advance(self.decision('advance'), self.task, dict(content=text)))

    def test_thanks_and_self_report_do_not_discard_explicit_next(self):
        for extra, text in [('thanks', '谢谢，继续下一节'), ('self_report', '我明白了，继续下一节')]:
            with self.subTest(extra=extra):
                decision = self.decision('advance')
                decision.intents.append(extra)
                self.assertTrue(should_advance(decision, self.task, dict(content=text)))
                self.assertIs(normalize(self.data, decision, dict(content=text)), decision)

    def test_selected_step_retry_cannot_authorize_new_input_or_stale_plan(self):
        decision = self.decision('advance')
        last = dict(message_id='message', run_id='run', content='继续下一节')
        run = dict(input_ids=['message'])
        self.task['context']['learning_plan'].update(current_step_id='second',
            steps=[dict(id='second', title='下一步', state='pending')])
        record_selection(run, self.task, decision, last, 'source_learning', 'first')
        self.data.update(mode='source_learning', runs={'run': run})
        self.assertTrue(applied_to_run(run, self.task, decision, last, 'source_learning'))
        self.assertIs(normalize(self.data, decision, last), decision)
        run['input_ids'].append('steering')
        self.assertFalse(applied_to_run(run, self.task, decision, last, 'source_learning'))
        self.assertEqual(normalize(self.data, decision, last).intents, ['followup'])
        run['input_ids'].pop()
        self.task['context']['learning_plan']['version'] = 2
        self.assertFalse(applied_to_run(run, self.task, decision, last, 'source_learning'))

    def test_explicit_skip_route_and_controls_keep_their_existing_meaning(self):
        skip = intent('skip_check', 'continue', scope='continue_goal')
        self.assertTrue(should_advance(skip, self.task, dict(content='先别考我，跳过')))
        self.assertIs(normalize(self.data, skip, dict(content='跳过')), skip)
        for name in ('answer', 'stop', 'pause', 'cancel', 'confirm'):
            with self.subTest(name=name):
                decision = intent(name, scope='continue_goal')
                self.assertIs(normalize(self.data, decision, dict(content='本轮请求')), decision)
                self.assertFalse(should_advance(decision, self.task, dict(content='本轮请求')))

    def test_stale_task_and_problem_mastery_cannot_use_navigation_to_advance(self):
        decision = self.decision('advance', target_task_id='other-task')
        self.assertFalse(should_advance(decision, self.task, dict(content='继续下一节')))
        self.task['context']['requires_mastery'] = True
        decision = self.decision('advance')
        self.assertFalse(should_advance(decision, self.task, dict(content='继续下一节')))
        self.assertIs(normalize(self.data, decision, dict(content='继续下一节')), decision)


class LearningNavigationHarnessTests(unittest.TestCase):
    setUp = alignment.TeachingAlignmentTests.setUp
    tearDown = alignment.TeachingAlignmentTests.tearDown
    send = alignment.TeachingAlignmentTests.send
    state = alignment.TeachingAlignmentTests.state
    start_lesson = alignment.TeachingAlignmentTests.start_lesson
    control = alignment.fixture.ConversationTests.control
    def model(self, system, user, schema, **kwargs):
        if schema is ConversationOutput:
            self.calls.append((schema, json.loads(user)))
            return ConversationOutput(message='只回顾当前原理，不进入下一步。')
        return alignment.TeachingAlignmentTests.model(self, system, user, schema, **kwargs)

    def test_review_with_conflicting_continue_keeps_plan_question_sources_and_history(self):
        task = self.start_lesson()
        before = copy.deepcopy(self.state())
        self.calls.clear()
        self.decision = intent('continue', workflow='source_learning', scope='continue_goal',
            learning_navigation=dict(action='review', step_id=current_step(task)['id'], evidence='回顾原讲解'))
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden')):
            accepted = self.send('回到 RAG，回顾原讲解，先不要进入下一节')
        after = self.state()
        self.assertEqual(after['runs'][accepted.run_id]['status'], 'completed')
        self.assertEqual(after['runs'][accepted.run_id]['intent']['intents'], ['followup'])
        old, new = task['context'], after['tasks'][task['task_id']]['context']
        for key in ('learning_plan', 'check_question', 'check_binding', 'last_lesson', 'sources', 'understanding', 'lesson_index'):
            self.assertEqual(new[key], old[key], key)
        self.assertEqual(after['messages'][:len(before['messages'])], before['messages'])
        self.assertEqual(after.get('capture_offers'), before.get('capture_offers'))
        self.assertEqual(after['pending'], before['pending'])
        self.assertEqual([schema.__name__ for schema, _ in self.calls],
                         ['IntentDecision', 'TeachingPreparation', 'ConversationOutput'])
        self.capture.assert_not_called()

    def test_explicit_next_targets_new_step_without_certifying_old_step(self):
        task = self.start_lesson()
        self.decision = intent('continue', workflow='source_learning', scope='continue_goal',
            learning_navigation=dict(action='advance', step_id=current_step(task)['id'], evidence='继续下一节'))
        self.send('继续下一节')
        after = self.state()['tasks'][task['task_id']]
        self.assertEqual(current_step(after)['title'], '检索与生成的职责')
        self.assertTrue(all(s['understanding'] == 'unknown' for s in after['context']['learning_plan']['steps']))

    def test_execution_rechecks_navigation_even_if_a_caller_bypasses_normalization(self):
        task = self.start_lesson()
        self.decision = intent('continue', workflow='source_learning', scope='continue_goal')
        with patch('agent_service.dialogue_routing.normalize', side_effect=lambda data, decision, last: decision):
            self.send('仅回顾，不进入下一节')
        after = self.state()['tasks'][task['task_id']]
        self.assertEqual(current_step(after)['id'], current_step(task)['id'])

    def test_failed_next_retries_selected_lesson_once_without_returning_to_followup(self):
        task = self.start_lesson()
        self.decision = intent('continue', workflow='source_learning', scope='continue_goal',
            learning_navigation=dict(action='advance', step_id=current_step(task)['id'], evidence='继续下一节'))
        base = self.harness._call
        def fail_lesson(*args, **kwargs):
            if args[3] == 'lesson':
                raise RuntimeError('controlled failure after selection')
            return base(*args, **kwargs)
        with patch.object(self.harness, '_call', side_effect=fail_lesson):
            accepted = self.send('继续下一节')
        failed = self.state()
        self.assertEqual(failed['runs'][accepted.run_id]['status'], 'retryable_failed')
        selected_id = current_step(failed['tasks'][task['task_id']])['id']
        self.assertNotEqual(selected_id, current_step(task)['id'])
        self.calls.clear()
        self.control(accepted.run_id, 'retry')
        with patch.object(self.harness, '_call', wraps=self.harness._call) as retry_calls:
            self.harness.drain(self.sid)
        after = self.state()
        self.assertEqual(after['runs'][accepted.run_id]['status'], 'completed')
        self.assertEqual(after['runs'][accepted.run_id]['intent']['intents'], ['continue'])
        self.assertEqual(current_step(after['tasks'][task['task_id']])['id'], selected_id)
        self.assertTrue(any(call.args[3] == 'lesson' and call.args[6].__name__ == 'TeachingConversationOutput'
                            for call in retry_calls.call_args_list))
        self.assertFalse(any(call.args[3] == 'answer' for call in retry_calls.call_args_list))

    def test_exact_teaching_control_retry_keeps_original_selection_after_new_reply(self):
        task = self.start_lesson()
        base = self.harness._call
        def fail_lesson(*args, **kwargs):
            if args[3] == 'lesson':
                raise RuntimeError('controlled exact teaching failure')
            return base(*args, **kwargs)
        with patch.object(self.harness, '_call', side_effect=fail_lesson):
            accepted = self.send('继续讲解')
        failed = self.state()
        selected_id = current_step(failed['tasks'][task['task_id']])['id']
        self.assertNotEqual(selected_id, current_step(task)['id'])
        self.send('继续讲解')
        self.control(accepted.run_id, 'retry')
        self.harness.drain(self.sid)
        after = self.state()
        self.assertEqual(after['runs'][accepted.run_id]['status'], 'completed')
        self.assertEqual(after['tasks'][task['task_id']]['status'], 'awaiting_user')
        self.assertEqual(after['tasks'][task['task_id']]['stage'], 'teaching')
        self.assertEqual(current_step(after['tasks'][task['task_id']])['id'], selected_id)
        self.assertNotIn('这份学习安排已讲解完毕', after['messages'][-1]['content'])
