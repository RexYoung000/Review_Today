"""Typed entry context remains evidence-only and works in both routing modes."""
import copy
import unittest

from pydantic import ValidationError

from agent_service.schemas import IntentDecision, KnowledgeStatusContext
from tests.knowledge_status_history_fixture import CLAIM_ID, KEYWORD_ID, VECTOR_ID, QUERY, proposal, seed


def decision(**updates):
    return IntentDecision.model_validate(dict(intents=['capabilities'], scope='conversation',
        relation='continuation', rationale='核对本段知识卡状态', knowledge_card_status=True,
        answer_only=True, **updates))


class KnowledgeStatusContextSchemaTests(unittest.TestCase):
    def test_grounded_proposal_round_trips_without_saved_state_fields(self):
        value = decision(status_context=proposal())
        self.assertEqual(value.status_context.model_dump(), proposal())
        self.assertEqual(value.proposed_actions, [])
        self.assertEqual(value.light_reply, '')
        fields = KnowledgeStatusContext.model_json_schema()['properties']
        self.assertEqual(set(fields), {'focus', 'prior_claim'})

    def test_context_cannot_accompany_a_non_status_request(self):
        value = decision(status_context=proposal()).model_dump()
        value['knowledge_card_status'] = False
        with self.assertRaises(ValidationError):
            IntentDecision.model_validate(value)

    def test_proposal_limits_and_semantic_kinds_are_enforced(self):
        for change in ('empty_quote', 'long_label', 'too_many_focus', 'invented_kind'):
            with self.subTest(change=change):
                value = proposal()
                if change == 'empty_quote':
                    value['focus'][0]['quote'] = ''
                elif change == 'long_label':
                    value['focus'][0]['label'] = '题' * 61
                elif change == 'too_many_focus':
                    value['focus'] *= 2
                else:
                    value['prior_claim']['kind'] = 'authorized_save'
                with self.assertRaises(ValidationError):
                    decision(status_context=value)

    def test_jev_remainder_preserves_same_reference_contract(self):
        from agent_service.judgment_nodes import IntentRemainder
        remainder = IntentRemainder(scope='conversation', rationale='状态回放',
            knowledge_card_status=True, status_context=proposal())
        self.assertEqual(remainder.status_context.model_dump(), proposal())
        self.assertEqual(IntentRemainder.model_fields['status_context'].annotation,
                         IntentDecision.model_fields['status_context'].annotation)

    def test_grounded_focus_is_required_only_when_status_has_candidates(self):
        from agent_service.openai_client import ModelCallError
        value = decision()
        value.validate_request({})
        value.validate_request(dict(knowledge_capture_status=dict(discussion_sources=[])))
        payload = dict(knowledge_capture_status=dict(discussion_sources=[dict(
            message_id=KEYWORD_ID, content=proposal()['focus'][0]['quote'], concepts=['关键词检索'])]))
        with self.assertRaises(ModelCallError):
            value.validate_request(payload)
        decision(status_context=proposal()).validate_request(payload)

    def test_jev_replacement_and_partial_share_grounding_check(self):
        from agent_service.judgment_nodes import IntentRemainder
        from agent_service.openai_client import ModelCallError
        payload = dict(context=dict(knowledge_capture_status=dict(discussion_sources=[dict(
            message_id=KEYWORD_ID, content=proposal()['focus'][0]['quote'], concepts=['关键词检索'])])))
        for fields in (dict(replacement=decision()), dict(knowledge_card_status=True)):
            with self.subTest(fields=fields):
                value = IntentRemainder(scope='conversation', rationale='状态回放', **fields)
                with self.assertRaises(ModelCallError):
                    value.validate_request(payload)

    def test_jev_context_flag_conflict_is_schema_failure_before_final_assembly(self):
        from agent_service.judgment_nodes import IntentRemainder
        from agent_service.openai_client import ModelCallError
        invalid = decision(status_context=proposal()).model_copy(update={'knowledge_card_status': False})
        partial = IntentRemainder(scope='conversation', rationale='合成冲突',
            knowledge_card_status=False, status_context=proposal())
        replacement = IntentRemainder.model_construct(scope='conversation', rationale='合成冲突',
            replacement=invalid)
        for value in (partial, replacement):
            with self.subTest(replacement=value.replacement is not None):
                with self.assertRaises(ModelCallError) as caught:
                    value.validate_request(dict(context={}))
                self.assertEqual(caught.exception.code, 'RT.MODEL.SCHEMA')
                self.assertIn('knowledge_status_context_requires_status_query', caught.exception.diagnostic)


class KnowledgeStatusHistoryRoutingTests(unittest.TestCase):
    def setUp(self):
        from tests import test_conversation_v2 as fixtures
        self.f = fixtures.ConversationTests()
        self.f.setUp()
        seed(self.f.harness, self.f.sid)

    def tearDown(self):
        self.f.tearDown()

    def query(self, context):
        self.f.decision = decision(status_context=context,
            reply_purpose='product_information', light_reply='有的，已经保存两张卡了。')
        before = copy.deepcopy(self.f.state())
        calls = len(self.f.calls)
        accepted = self.f.send(QUERY, mode='source_learning')
        after = self.f.state()
        self.assertEqual([schema for schema, _ in self.f.calls[calls:]], [IntentDecision])
        self.assertEqual(before['tasks'], after['tasks'])
        self.assertEqual(before['messages'], after['messages'][:len(before['messages'])])
        self.assertEqual(before.get('capture_offers'), after.get('capture_offers'))
        self.assertEqual(before['draft'], after['draft'])
        self.assertEqual(before['pending'], after['pending'])
        self.f.capture.assert_not_called()
        return after['runs'][accepted.run_id], after['messages'][-1]['content'], self.f.calls[calls][1]

    def test_realistic_legacy_prefix_exposes_current_topics_and_corrects_false_card_claim(self):
        run, reply, entry = self.query(proposal())
        facts = entry['knowledge_capture_status']
        sources = {item['message_id'] for item in facts['discussion_sources']}
        self.assertTrue({KEYWORD_ID, VECTOR_ID}.issubset(sources))
        self.assertIn(CLAIM_ID, [item['message_id'] for item in facts['prior_status_messages']])
        self.assertEqual(run['knowledge_status_correction_message_id'], CLAIM_ID)
        self.assertIn('关键词检索', reply)
        self.assertIn('向量检索', reply)
        self.assertIn('不准确', reply)
        self.assertNotIn('讨论的是资料切块', reply)
        self.assertNotIn('有的，已经保存两张卡了', reply)

    def test_already_corrected_claim_is_not_repeated_in_next_status_reply(self):
        self.query(proposal())
        context = proposal()
        context['prior_claim'] = None
        run, reply, entry = self.query(context)
        self.assertNotIn(CLAIM_ID, [item['message_id']
            for item in entry['knowledge_capture_status']['prior_status_messages']])
        self.assertIsNone(run['knowledge_status_correction_message_id'])
        self.assertIn('关键词检索', reply)
        self.assertIn('向量检索', reply)
        self.assertNotIn('不准确', reply)

    def test_missing_focus_repairs_once_before_publishing_contextual_status(self):
        from unittest.mock import patch
        from agent_service.execution_policy import current_budget
        calls = []

        def model(system, user, schema, **kwargs):
            current_budget.get().take()
            calls.append(schema)
            return decision(status_context=proposal() if len(calls) == 2 else None)

        with patch('agent_service.conversation.parse_model', side_effect=model):
            accepted = self.f.send(QUERY, mode='source_learning')
        state = self.f.state()
        self.assertEqual(calls, [IntentDecision, IntentDecision])
        self.assertEqual(state['runs'][accepted.run_id]['status'], 'completed')
        self.assertIn('关键词检索', state['messages'][-1]['content'])
        self.assertIn('不准确', state['messages'][-1]['content'])

    def test_unrepaired_focus_does_not_silently_publish_generic_status(self):
        self.f.decision = decision()
        before = copy.deepcopy(self.f.state())
        accepted = self.f.send(QUERY, mode='source_learning')
        state = self.f.state()
        self.assertEqual([schema for schema, _ in self.f.calls], [IntentDecision, IntentDecision])
        self.assertEqual(state['runs'][accepted.run_id]['status'], 'retryable_failed')
        tid = before['active_task_id']
        for key in ('learning_plan', 'understanding', 'practice', 'last_lesson', 'check_question'):
            self.assertEqual(state['tasks'][tid]['context'][key], before['tasks'][tid]['context'][key])
        self.assertFalse(state['runs'][accepted.run_id].get('knowledge_status_reply'))
        self.f.capture.assert_not_called()

    def test_jev_flag_conflict_uses_same_bounded_entry_repair(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from agent_service.execution_policy import current_budget
        from agent_service.judgment_nodes import IntentRemainder
        engine = Mock()
        engine.judge.return_value = SimpleNamespace(status='ok', reason='', labels=dict(
            intent='question', workflow='none', relation='continuation',
            needs_verification='no', cross_check_sources='no', refresh_sources='no'))
        self.f.harness.judgments = engine
        calls = []

        def model(system, user, schema, **kwargs):
            current_budget.get().take()
            calls.append(schema)
            if len(calls) == 1:
                return IntentRemainder(scope='conversation', rationale='合成字段冲突',
                    knowledge_card_status=False, status_context=proposal())
            return IntentRemainder(scope='conversation', rationale='已修复状态冲突',
                replacement=decision(status_context=proposal()))

        before = copy.deepcopy(self.f.state())
        with patch('agent_service.conversation.parse_model', side_effect=model):
            accepted = self.f.send(QUERY, mode='source_learning')
        state = self.f.state()
        self.assertEqual(calls, [IntentRemainder, IntentRemainder])
        self.assertEqual(engine.judge.call_count, 1)
        self.assertEqual(state['runs'][accepted.run_id]['status'], 'completed')
        self.assertTrue(state['runs'][accepted.run_id]['knowledge_status_reply'])
        self.assertIn('关键词检索', state['messages'][-1]['content'])
        self.assertIn('不准确', state['messages'][-1]['content'])
        self.assertEqual(state['tasks'], before['tasks'])
        self.f.capture.assert_not_called()

    def test_jev_repeated_flag_conflict_stops_after_one_repair(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from agent_service.execution_policy import current_budget
        from agent_service.judgment_nodes import IntentRemainder
        engine = Mock()
        engine.judge.return_value = SimpleNamespace(status='ok', reason='', labels=dict(
            intent='question', workflow='none', relation='continuation',
            needs_verification='no', cross_check_sources='no', refresh_sources='no'))
        self.f.harness.judgments = engine
        calls = []

        def model(system, user, schema, **kwargs):
            current_budget.get().take()
            calls.append(schema)
            return IntentRemainder(scope='conversation', rationale='合成持续冲突',
                knowledge_card_status=False, status_context=proposal())

        with patch('agent_service.conversation.parse_model', side_effect=model):
            accepted = self.f.send(QUERY, mode='source_learning')
        run = self.f.state()['runs'][accepted.run_id]
        self.assertEqual(calls, [IntentRemainder, IntentRemainder])
        self.assertEqual(engine.judge.call_count, 1)
        self.assertEqual(run['status'], 'retryable_failed')
        self.assertEqual(run['error_code'], 'RT.MODEL.SCHEMA')
        self.assertFalse(run.get('knowledge_status_reply'))
        self.f.capture.assert_not_called()


if __name__ == '__main__':
    unittest.main()
