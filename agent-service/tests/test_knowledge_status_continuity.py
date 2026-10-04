"""A corrected receipt answer must make sense beside the old visible dialogue."""
import copy
import unittest

from agent_service.knowledge_capture_status import facts, reply, validate_context
from tests import test_conversation_v2 as fixtures
from tests import knowledge_status_history_fixture as history


class StatusContinuityTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ConversationTests()
        self.f.setUp()
        history.seed(self.f.harness, self.f.sid)

    def tearDown(self):
        self.f.tearDown()

    def test_legacy_claim_is_corrected_and_actual_discussion_named_without_writing(self):
        before = copy.deepcopy(self.f.state())
        self.f.decision = fixtures.intent('capabilities', scope='conversation',
            reply_purpose='product_information', knowledge_card_status=True, status_context=history.proposal())
        accepted = self.f.send(history.QUERY)
        state = self.f.state()
        text = state['messages'][-1]['content']
        self.assertIn('前面关于本轮知识卡的说法不准确', text)
        self.assertNotIn(history.CLAIM_QUOTE, text)
        self.assertIn('刚才讨论的是关键词检索、向量检索', text)
        self.assertIn('还没有整理成知识卡', text)
        self.assertNotIn('资料切块', text, 'a stale plan title is not the current discussion')
        self.assertEqual(state['messages'][:len(before['messages'])], before['messages'])
        task = before['active_task_id']
        self.assertEqual(state['tasks'][task]['context'], before['tasks'][task]['context'])
        self.assertEqual(state['runs'][accepted.run_id]['knowledge_status_correction_message_id'], history.CLAIM_ID)
        self.assertFalse(state.get('capture_offers'))
        self.f.capture.assert_not_called()

    def test_generic_unsaved_reply_does_not_count_as_a_correction(self):
        data = self.f.state()
        before = copy.deepcopy(data)
        state = facts(data)
        self.assertIn(history.CLAIM_ID, [item['message_id'] for item in state['prior_status_messages']])
        self.assertIn(history.VECTOR_ID, [item['message_id'] for item in state['discussion_sources']])
        self.assertEqual(data, before)

    def test_completed_correction_is_not_repeated(self):
        self.f.decision = fixtures.intent('capabilities', scope='conversation',
            knowledge_card_status=True, status_context=history.proposal())
        self.f.send(history.QUERY)
        self.f.send(history.QUERY)
        self.assertNotIn('不准确', self.f.state()['messages'][-1]['content'])
        self.assertIn('关键词检索', self.f.state()['messages'][-1]['content'])

    def test_natural_primary_topic_survives_empty_concepts_and_repeat_query(self):
        before = copy.deepcopy(self.f.state())
        context = history.comparison_proposal()
        self.assertNotIn(context['focus'][0]['label'], context['focus'][0]['quote'])
        state = facts(before)
        source = next(item for item in state['discussion_sources'] if item['message_id'] == history.VECTOR_ID)
        self.assertEqual(source['concepts'], [])
        self.assertEqual(validate_context(state, context)['focus_labels'],
                         [item['label'] for item in context['focus']])
        self.f.decision = fixtures.intent('capabilities', scope='conversation',
            knowledge_card_status=True, status_context=context)
        first = self.f.send(history.QUERY)
        self.assertIn('刚才讨论的是关键词与向量检索的匹配差异、关键词检索',
                      self.f.state()['messages'][-1]['content'])
        second = self.f.send(history.QUERY)
        after = self.f.state()
        self.assertIn('关键词与向量检索的匹配差异', after['messages'][-1]['content'])
        self.assertNotIn('不准确', after['messages'][-1]['content'])
        self.assertEqual(after['runs'][first.run_id]['knowledge_status_correction_message_id'], history.CLAIM_ID)
        self.assertIsNone(after['runs'][second.run_id]['knowledge_status_correction_message_id'])
        self.assertEqual(before['tasks'], after['tasks'])
        self.assertFalse(after.get('capture_offers'))
        self.f.capture.assert_not_called()

    def test_invalid_primary_reference_does_not_publish_older_secondary_topic(self):
        state = facts(self.f.state())
        for change in (dict(message_id='foreign'), dict(quote='未出现的比较讲解')):
            with self.subTest(change=change):
                context = history.comparison_proposal()
                context['focus'][0].update(change)
                result = validate_context(state, context)
                self.assertEqual(result['focus_labels'], [])
                self.assertIsNone(result['correction_message_id'])
                self.assertNotIn('刚才讨论的是关键词检索', reply(state, context))

    def test_long_prior_assertion_is_corrected_without_repeating_its_details(self):
        state = facts(self.f.state())
        context = history.proposal()
        quote = '本会话已经记录了知识卡：' + '这些旧卡的定义、机制和用途说明。' * 8
        state['prior_status_messages'] = [dict(message_id=history.CLAIM_ID, content=quote)]
        context['prior_claim'].update(quote=quote)
        self.assertEqual(validate_context(state, context)['correction_message_id'], history.CLAIM_ID)
        text = reply(state, context)
        self.assertIn('不准确', text)
        self.assertIn('没有可确认的本轮知识卡保存记录', text)
        self.assertNotIn(quote, text)
        self.assertLess(len(text.split('\n\n')[0]), 80)

    def test_unrelated_ids_quotes_and_invalid_label_shapes_are_ignored(self):
        state = facts(self.f.state())
        bad_focus = [dict(message_id='foreign', label='关键词检索', quote=history.KEYWORD_QUOTE),
                     dict(message_id=history.KEYWORD_ID, label='关键词检索', quote='并未说过这句'),
                     dict(message_id=history.KEYWORD_ID, label='', quote=history.KEYWORD_QUOTE),
                     dict(message_id=history.KEYWORD_ID, label='主题' * 31, quote=history.KEYWORD_QUOTE)]
        for item in bad_focus:
            with self.subTest(item=item):
                proposal = dict(history.proposal(), focus=[item])
                result = validate_context(state, proposal)
                self.assertEqual(result['focus_labels'], [])
                self.assertIsNone(result['correction_message_id'])
        for change in [dict(message_id=history.KEYWORD_ID), dict(quote='已保存九张新卡')]:
            with self.subTest(change=change):
                proposal = copy.deepcopy(history.proposal())
                proposal['prior_claim'].update(change)
                self.assertIsNone(validate_context(state, proposal)['correction_message_id'])

    def test_actual_prior_receipt_is_not_retracted_as_a_lie(self):
        data = self.f.state()
        data['tasks']['saved'] = dict(task_id='saved', session_id=self.f.sid, status='completed',
            mode='memory_organization', context={}, memory_package=dict(knowledge=[dict(id='real-card')]),
            events=[dict(node='mac_ack')])
        text = reply(facts(data), history.proposal())
        self.assertNotIn('不准确', text)
        self.assertIn('此前有 1 张已确认写入的卡', text)

    def test_claim_quote_cannot_drop_negation_attribution_or_hypothesis(self):
        state = facts(self.f.state())
        for content, quote in [
            ('目前还没有保存知识卡；这里只是聊天记录。', '保存知识卡'),
            ('资料里的例子说：“已经保存两张卡”。', '已经保存两张卡'),
            ('假设已经保存两张卡，就会在知识库出现。', '已经保存两张卡'),
            ('知识卡已经保存了吗？这是待核实的问题。', '知识卡已经保存'),
        ]:
            with self.subTest(content=content):
                state['prior_status_messages'] = [dict(message_id=history.CLAIM_ID, content=content)]
                proposal = copy.deepcopy(history.proposal())
                proposal['prior_claim'].update(quote=quote, kind='saved')
                self.assertIsNone(validate_context(state, proposal)['correction_message_id'])
                self.assertNotIn('不准确', reply(state, proposal))

    def test_generated_package_without_receipt_is_not_called_un_generated(self):
        data = self.f.state()
        data['tasks']['generating'] = dict(task_id='generating', session_id=self.f.sid, status='committing',
            context={}, memory_package=dict(knowledge=[dict(id='generated-card')]), events=[])
        proposal = copy.deepcopy(history.proposal())
        proposal['prior_claim']['kind'] = 'generated'
        self.assertIsNone(validate_context(facts(data), proposal)['correction_message_id'])

    def test_new_topic_cannot_reuse_old_claim_or_discussion(self):
        data = self.f.state()
        data['runs']['other'] = dict(status='completed', task_id=None, activity_kind='knowledge_answer',
            intent=dict(relation='new_topic'), learning_concepts=['光合作用'])
        data['messages'].append(dict(message_id='other', role='coach', run_id='other', content='光合作用把光能转化为化学能。'))
        state = facts(data)
        self.assertEqual([item['message_id'] for item in state['discussion_sources']], ['other'])
        self.assertEqual(state['prior_status_messages'], [])
        self.assertEqual(validate_context(state, history.proposal())['focus_labels'], [])


if __name__ == '__main__':
    unittest.main()
