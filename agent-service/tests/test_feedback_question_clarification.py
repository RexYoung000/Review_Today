"""Local question clarification must not inherit a stale teaching command."""
import copy
import unittest
from unittest.mock import patch

from agent_service import dialogue_routing
from agent_service.schemas import ConversationOutput, IntentDecision
from tests import test_conversation_v2 as fixtures
from tests import test_judgment_harness as jev_fixtures


QUESTION = "文档切得太大或太小时，会怎样影响检索结果？"
EXPLANATION = "这题是在比较两种切法：一段很长，或一段很短。请分别想想检索得到的内容会有什么问题，说明原因即可，不用讲索引或生成。"


def seed_question(fixture):
    fixture.decision = fixtures.intent('goal', scope='learning', workflow='source_learning', direct_teaching=True)
    fixture.send('直接教我 RAG')
    with fixture.store.transaction(fixture.sid) as data:
        task = data['tasks'][data['active_task_id']]
        task['context']['check_question'] = QUESTION
        task['required_action'] = dict(type='submit_answer', prompt=QUESTION, options=[])
        data['messages'][-1]['content'] = "RAG 会先把文档切成片段，再检索相关片段。\n\n" + QUESTION
        data['draft'] = dict(id=task['task_id'], version=1, content='既有待保存草稿', understanding='unknown')
        data['pending'] = dict(kind='save', target_id=task['task_id'], version=1)
    fixture.calls.clear()
    return copy.deepcopy(fixture.state())


def conflicting_feedback(task_id):
    # These are the conflicting structured fields observed in the actual route:
    # a local question complaint plus teaching and the active topic as target.
    return fixtures.intent('question', reply_feedback='response_only', light_reply=EXPLANATION,
        scope='continue_goal', workflow='source_learning', direct_teaching=True,
        learning_goal_ready=True, target_task_id=task_id, target_description='RAG 检索索引',
        understanding='self_reported')


class FeedbackQuestionClarificationTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ConversationTests()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def test_conflicting_teaching_fields_explain_question_without_changing_any_learning_state(self):
        before = seed_question(self.f)
        self.f.decision = conflicting_feedback(before['active_task_id'])
        with patch.object(self.f.harness, '_prepare_teaching', side_effect=AssertionError('no teaching or tools')):
            accepted = self.f.send('我不理解你的问题')
        after = self.f.state()
        run = after['runs'][accepted.run_id]
        self.assertEqual(after['messages'][-1]['content'], EXPLANATION)
        self.assertEqual(after['messages'][:len(before['messages'])], before['messages'])
        for key in ('tasks', 'active_task_id', 'pending', 'draft', 'focus_goal', 'teaching_context', 'capture_offers'):
            self.assertEqual(after.get(key), before.get(key), key)
        self.assertEqual([schema for schema, _ in self.f.calls], [IntentDecision])
        self.assertIn(QUESTION, str(self.f.calls[0][1]))
        self.assertTrue(run['reply_feedback_handled'])
        self.assertTrue(run['dialogue_only'])
        self.assertIsNone(run['task_id'])
        self.assertIsNone(run.get('activity_kind'))
        self.assertFalse(run.get('learning_concepts'))
        decision = run['intent']
        self.assertEqual((decision['scope'], decision['workflow'], decision['understanding']),
                         ('conversation', None, 'unknown'))
        self.assertFalse(decision['direct_teaching'])
        self.assertFalse(decision['learning_goal_ready'])
        self.assertEqual((decision['target_task_id'], decision['target_description']), ('', ''))
        self.assertEqual(run['dialogue_policy'], dialogue_routing.POLICY_VERSION)
        self.f.capture.assert_not_called()

    def test_response_only_normalizes_stale_topic_and_answer_fields_without_word_matching(self):
        base = conflicting_feedback('old-target').model_copy(update=dict(
            relation='new_topic', intents=['correction'], answer_evidence='stale answer',
            topic_closure=dict(title='旧话题', evidence='明白了', message_ids=['old-message'])))
        normalized = dialogue_routing.normalize({}, base, {'content': 'That question is unclear.'})
        self.assertEqual(normalized.intents, ['question'])
        self.assertEqual(normalized.relation, 'continuation')
        self.assertFalse(normalized.direct_teaching)
        self.assertEqual(normalized.answer_evidence, '')
        self.assertIsNone(normalized.topic_closure)

    def test_long_feedback_keeps_complete_explanation_instead_of_generic_apology(self):
        before = seed_question(self.f)
        useful = '这题是在比较一段很长和一段很短的两种切法。请分别说明检索结果会有什么问题，以及你这样判断的原因。'
        extra = '这次只需要解释你的判断依据，不需要补写索引建立、向量计算、生成答案或其他后续步骤中的技术细节，也不用把整个检索流程从头到尾复述一遍或者再额外讲解其他尚未介绍过的知识点。'
        self.assertGreater(len(useful + extra), 120)
        self.f.decision = conflicting_feedback(before['active_task_id']).model_copy(update={'light_reply': useful + extra})
        accepted = self.f.send('我不理解你的问题')
        self.assertEqual(self.f.state()['messages'][-1]['content'], useful)
        self.assertEqual(self.f.state()['tasks'], before['tasks'])
        self.assertTrue(self.f.state()['runs'][accepted.run_id]['reply_feedback_handled'])

    def test_feedback_with_an_actual_new_teaching_request_keeps_teaching(self):
        before = seed_question(self.f)
        self.f.decision = fixtures.intent('goal', reply_feedback='with_request',
            scope='continue_goal', workflow='source_learning', direct_teaching=True,
            target_task_id=before['active_task_id'], target_description='RAG 检索索引')
        accepted = self.f.send('刚才没讲清楚，直接教我检索索引')
        after = self.f.state()
        task = after['tasks'][before['active_task_id']]
        self.assertNotIn('reply_feedback_handled', after['runs'][accepted.run_id])
        self.assertTrue(after['runs'][accepted.run_id]['intent']['direct_teaching'])
        self.assertGreater(task['context']['lesson_index'], before['tasks'][before['active_task_id']]['context']['lesson_index'])
        self.assertTrue(any(issubclass(schema, ConversationOutput) for schema, _ in self.f.calls))

    def test_operations_controls_and_independent_requests_are_not_normalized_away(self):
        base = conflicting_feedback('old-target')
        variants = [base.model_copy(update={'reply_feedback': 'with_request'})]
        variants += [base.model_copy(update={'intents': [control]})
                     for control in ('stop', 'pause', 'cancel', 'defer', 'queue', 'continue', 'answer', 'confirm')]
        variants += [base.model_copy(update={'proposed_actions': [dict(kind='save', disposition='request', evidence='保存')]}),
                     base.model_copy(update={'requested_mode': 'problem_solving'}),
                     base.model_copy(update={'conversation_repair': True}),
                     base.model_copy(update={'needs_verification': True})]
        for decision in variants:
            with self.subTest(decision=decision):
                self.assertIs(dialogue_routing.normalize({'mode': 'auto'}, decision, {'content': 'mixed request'}), decision)
        self.assertIs(dialogue_routing.normalize({'mode': 'auto'}, base,
            {'content': '录入', 'operation': {'kind': 'capture_save'}}), base)

    def test_previous_policy_cache_is_reclassified_before_it_can_teach(self):
        before = seed_question(self.f)
        accepted = self.f.send('我不理解你的问题', drain=False)
        old = conflicting_feedback(before['active_task_id'])
        with self.f.store.transaction(self.f.sid) as data:
            run = data['runs'][accepted.run_id]
            run.update(intent=old.model_dump(), decision_input_ids=list(run['input_ids']),
                       decision_mode=data['mode'], dialogue_policy='dialogue-materials-7', judgment_policy=None)
        self.f.decision = old
        self.f.harness.drain(self.f.sid)
        self.assertEqual([schema for schema, _ in self.f.calls], [IntentDecision])
        self.assertEqual(self.f.state()['messages'][-1]['content'], EXPLANATION)
        self.assertEqual(self.f.state()['tasks'], before['tasks'])


class JevFeedbackQuestionClarificationTests(unittest.TestCase):
    def test_reserved_replacement_resolves_same_conflict_with_one_entry_call(self):
        fixture = jev_fixtures.HarnessJudgmentTests()
        fixture.setUp()
        try:
            before = seed_question(fixture)
            fixture.enable()
            fixture.labels.update(intent='question', workflow='source_learning')
            fixture.decision = conflicting_feedback(before['active_task_id'])
            fixture.replacement = fixture.decision
            with patch.object(fixture.harness, '_prepare_teaching', side_effect=AssertionError('no teaching')):
                accepted = fixture.send('我不理解你的问题')
            after = fixture.state()
            run = after['runs'][accepted.run_id]
            self.assertTrue(run['reply_feedback_handled'])
            self.assertFalse(run['judgments'][0]['applied'])
            self.assertEqual([schema for schema, _ in fixture.calls], [jev_fixtures.IntentRemainder])
            self.assertEqual(after['messages'][-1]['content'], EXPLANATION)
            self.assertEqual(after['tasks'], before['tasks'])
            self.assertEqual(len(fixture.http_calls), 1)
        finally:
            fixture.tearDown()
