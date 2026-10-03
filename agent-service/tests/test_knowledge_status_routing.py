"""Current-card enquiries use receipts, never the entry model's saved claims."""
import copy
import unittest
import uuid

from tests import test_conversation_v2 as fixtures
from agent_service.schemas import SessionMessageRequest, IntentDecision


class KnowledgeStatusRoutingTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ConversationTests()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def query(self, text='你有记录刚才相关知识卡吗', **overrides):
        values = dict(scope='conversation', knowledge_card_status=True,
                      reply_purpose='product_information', answer_only=True,
                      light_reply='有的，本轮已经保存了两张知识卡。')
        values.update(overrides)
        self.f.decision = fixtures.intent('capabilities', **values)
        request = SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text,
            context={'knowledge_summaries': ['旧的 RAG 基础卡：解释 RAG，来自历史资料。']})
        accepted = self.f.harness.accept(self.f.sid, request)
        self.f.harness.drain(self.f.sid)
        return self.f.state(), accepted

    def test_old_related_cards_never_become_current_save_receipts(self):
        self.f.decision = fixtures.intent('question', scope='conversation')
        self.f.send('关键词与向量检索有什么区别？')
        before = copy.deepcopy(self.f.state())
        calls = len(self.f.calls)
        state, accepted = self.query()
        reply = state['messages'][-1]['content']
        self.assertIn('还没有整理成知识卡', reply)
        self.assertIn('把刚才内容整理成知识卡', reply)
        self.assertNotIn('本轮已经保存了两张', reply)
        self.assertNotIn('账号', reply)
        self.assertEqual(state['tasks'], before['tasks'])
        self.assertEqual(state['draft'], before['draft'])
        self.assertEqual(state['pending'], before['pending'])
        self.assertTrue(state['runs'][accepted.run_id]['knowledge_status_reply'])
        self.assertIsNone(state['runs'][accepted.run_id]['activity_kind'])
        self.assertEqual([schema for schema, _ in self.f.calls[calls:]], [IntentDecision])
        self.f.capture.assert_not_called()

    def test_empty_chat_can_explain_generation_without_claiming_content(self):
        state, _ = self.query('这些内容要怎么生成知识卡？')
        self.assertEqual(state['tasks'], {})
        self.assertFalse(state.get('capture_offers'))
        self.assertIn('还没有', state['messages'][-1]['content'])
        self.f.capture.assert_not_called()

    def test_card_facts_are_present_for_intent_even_when_old_memory_is_filtered(self):
        self.query()
        prompt = next(payload for schema, payload in self.f.calls if schema is IntentDecision)
        self.assertEqual(prompt['knowledge_capture_status']['stage'], 'none')
        self.assertNotIn('related_knowledge', prompt)
        self.assertNotIn('related_learning', prompt)

    def test_actual_save_request_is_not_consumed_as_status_query(self):
        self.f.decision = fixtures.intent('question', scope='conversation')
        self.f.send('讲一下向量检索。')
        previous = self.f.state()['messages'][-1]
        self.f.capture.return_value = fixtures.committing_result(previous['content'])
        self.f.decision = fixtures.intent('confirm', knowledge_card_status=False,
            proposed_actions=[dict(kind='save', disposition='request', target_id=previous['message_id'],
                                  version=1, evidence='把刚才内容保存成知识卡')])
        accepted = self.f.send('把刚才内容保存成知识卡')
        self.assertFalse(self.f.state()['runs'][accepted.run_id].get('knowledge_status_reply'))
        self.f.capture.assert_called_once()

    def test_contradictory_status_and_save_output_cannot_authorize_writing(self):
        self.f.decision = fixtures.intent('question', scope='conversation')
        self.f.send('讲一下向量检索。')
        previous = self.f.state()['messages'][-1]
        # Simulate a provider that returns both a read-only enquiry and an
        # operation. Harness revalidates even already-constructed model values.
        self.f.decision = fixtures.intent('capabilities', scope='conversation',
            proposed_actions=[dict(kind='save', disposition='request', target_id=previous['message_id'],
                                  version=1, evidence='生成知识卡')]).model_copy(update={'knowledge_card_status': True})
        self.f.send('这些内容怎么生成知识卡？')
        self.f.capture.assert_not_called()
        self.assertFalse(self.f.state().get('capture_offers'))


if __name__ == '__main__':
    unittest.main()
