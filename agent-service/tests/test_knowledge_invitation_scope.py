"""Scope refresh must remain available throughout a longer learning thread."""
import copy
import unittest
from unittest.mock import patch
from agent_service.schemas import MasteryEvaluation
from tests import test_knowledge_invitation as fixture


class KnowledgeInvitationScopeTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.KnowledgeInvitationTests()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def test_earlier_invitation_can_update_after_three_more_invitations(self):
        _, first = self.f.start_offer()
        with self.f.store.transaction(self.f.sid) as data:
            for i in range(3):
                other = copy.deepcopy(first)
                other['id'] = 'later-' + str(i)
                other['concepts'] = ['其他知识点' + str(i)]
                data['capture_offers'][other['id']] = other
        self.f.followup('补充最早的知识点：外部资料仍需要核对适用条件。')
        offers = self.f.state()['capture_offers']
        self.assertEqual(offers[first['id']]['version'], first['version'] + 1)
        self.assertIn('适用条件', offers[first['id']]['draft']['content'])
        self.assertTrue(all(o['version'] == 1 for k, o in offers.items() if k != first['id']))
        self.f.capture.assert_not_called()

    def test_completed_correction_without_valid_scope_does_not_claim_it_is_running(self):
        _, offer = self.f.start_offer()
        self.f.followup('纠正还需要你补充具体适用条件。', correction=True, update=False)
        updated = self.f.offer()
        self.assertEqual(updated['status'], 'invalidated')
        self.assertIn('尚未确认', updated['error'])
        self.assertNotIn('正在', updated['error'])
        self.f.action(updated, 'capture_save')
        self.f.capture.assert_not_called()

    def test_plain_summary_uses_the_same_evaluation_without_extra_card_generation(self):
        self.f.start_lesson()
        base = self.f.model
        summary = '外部资料可补充新信息，但仍需核对检索和回答结果。'
        def evaluate(system, user, schema, **kwargs):
            result = base(system, user, schema, **kwargs)
            if schema is MasteryEvaluation:
                result.capture_scope_summary = summary
            return result
        with patch('agent_service.conversation.parse_model', side_effect=evaluate):
            self.f.answer()
        self.assertEqual(self.f.offer()['scope_summary'], summary)
        self.assertNotIn('本节其他内容', self.f.state()['messages'][-1]['content'])
        self.f.capture.assert_not_called()
