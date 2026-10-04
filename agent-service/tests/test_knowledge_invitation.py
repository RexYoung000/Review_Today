"""End-to-end controlled learning → visible source invitation → explicit save."""
import copy
import json
import unittest
from unittest.mock import patch

from agent_service.learning_progress import current_step
from agent_service.schemas import ConversationOutput, CaptureScopeUpdate, IntentDecision
from tests import test_teaching_alignment as alignment
from tests.test_conversation_v2 import intent
from tests.test_m1_capture_contract import committing_result


class KnowledgeInvitationTests(unittest.TestCase):
    setUp = alignment.TeachingAlignmentTests.setUp
    tearDown = alignment.TeachingAlignmentTests.tearDown
    send = alignment.TeachingAlignmentTests.send
    state = alignment.TeachingAlignmentTests.state
    model = alignment.TeachingAlignmentTests.model
    start_lesson = alignment.TeachingAlignmentTests.start_lesson
    answer = alignment.TeachingAlignmentTests.answer

    def offer(self):
        return next(iter(self.state().get('capture_offers', {}).values()))

    def start_offer(self):
        task = self.start_lesson()
        self.answer()
        return task, self.offer()

    def action(self, offer, kind):
        return self.send(kind, operation=dict(kind=kind, target_id=offer['id'], version=offer['version']))

    def followup(self, text, *, correction=False, update=True):
        self.decision = intent('correction' if correction else 'followup', scope='continue_goal', workflow='source_learning')
        base = self.model
        def response(system, user, schema, **kwargs):
            if issubclass(schema, ConversationOutput):
                payload = json.loads(user)
                selected = payload['capture_candidates'][0]
                proposal = CaptureScopeUpdate(offer_id=selected['id'], version=selected['version'],
                    retained_fragment_ids=[] if correction else [f['id'] for f in selected['fragments']],
                    evidence_quotes=[text], scope_summary=text) if update else None
                return ConversationOutput(message=text, learning_concepts=['外部资料作用'], capture_update=proposal)
            return base(system, user, schema, **kwargs)
        with patch('agent_service.conversation.parse_model', side_effect=response):
            self.send('请纠正刚才的说法' if correction else '继续解释这个知识点')

    def test_first_grounded_pass_invites_under_feedback_without_generating_or_advancing(self):
        task, offer = self.start_offer()
        state = self.state()
        self.assertEqual(offer['trigger'], 'verified_check')
        self.assertEqual(offer['anchor_message_id'], state['messages'][-1]['message_id'])
        self.assertEqual(offer['title'], '外部资料作用')
        self.assertIn('外部资料作用', offer['scope_summary'])
        self.assertEqual(offer['next_request'], '')
        self.assertTrue(offer['continuation_consumed'])
        self.assertEqual(current_step(state['tasks'][task['task_id']])['id'], current_step(task)['id'])
        self.assertEqual(current_step(state['tasks'][task['task_id']])['understanding'], 'unknown')
        self.assertIsNone(state['draft'])
        self.assertIsNone(state['pending'])
        self.capture.assert_not_called()
        events = [e for e in state['events'] if e['stage'] == 'capture_offer']
        self.assertEqual(events[-1]['payload']['capture_offer']['scope_summary'], offer['scope_summary'])

    def test_repeat_pass_does_not_create_duplicate_invitation(self):
        _, offer = self.start_offer()
        self.answer()
        self.assertEqual(list(self.state()['capture_offers']), [offer['id']])
        self.assertEqual(self.offer()['version'], 1)
        self.capture.assert_not_called()

    def add_overlapping_pass(self):
        task = self.state()['tasks'][self.state()['active_task_id']]
        with self.store.transaction(self.sid) as data:
            data['tasks'][task['task_id']]['context']['check_binding']['concepts'] = ['外部资料作用', '检索错误风险']
        base = self.model
        def evaluate(system, user, schema, **kwargs):
            from agent_service.schemas import MasteryEvaluation
            result = base(system, user, schema, **kwargs)
            if schema is MasteryEvaluation:
                self.assertEqual(json.loads(user)['capture_concepts'], ['检索错误风险'])
                result.capture_quotes = ['但仍可能检索错或答错。']
            return result
        with patch('agent_service.conversation.parse_model', side_effect=evaluate):
            self.answer()
        return list(self.state()['capture_offers'].values())[-1]

    def test_overlapping_combination_only_invites_new_concept(self):
        _, old = self.start_offer()
        new = self.add_overlapping_pass()
        self.assertEqual(new['concepts'], ['检索错误风险'])
        self.assertNotIn('补充模型未学过的资料', new['draft']['content'])
        self.assertEqual(self.state()['capture_offers'][old['id']], old)
        self.answer()  # The same combined scope is now wholly covered.
        self.assertEqual(len(self.state()['capture_offers']), 2)

    def test_subset_of_previous_combination_does_not_reinvite(self):
        task = self.start_lesson()
        with self.store.transaction(self.sid) as data:
            data['tasks'][task['task_id']]['context']['check_binding']['concepts'].append('检索错误风险')
        self.answer()
        self.assertEqual(len(self.offer()['concepts']), 2)
        with self.store.transaction(self.sid) as data:
            data['tasks'][task['task_id']]['context']['check_binding']['concepts'] = ['外部资料作用']
        self.answer()
        self.assertEqual(len(self.state()['capture_offers']), 1)

    def test_correcting_one_of_two_same_step_invitations_keeps_other_available(self):
        _, first = self.start_offer()
        other = self.add_overlapping_pass()
        self.followup('外部资料仅在可访问且检索到时才能作为回答依据。', correction=True)
        state = self.state()
        self.assertEqual(state['capture_offers'][first['id']]['status'], 'offered')
        self.assertEqual(state['capture_offers'][other['id']]['status'], 'offered')
        self.assertEqual(state['capture_offers'][other['id']]['draft']['content'], other['draft']['content'])

    def test_restart_between_save_click_and_commit_task_does_not_leave_saving_stuck(self):
        task, offer = self.start_offer()
        accepted = self.send('新增知识', operation=dict(kind='capture_save', target_id=offer['id'], version=1), drain=False)
        with self.store.transaction(self.sid) as data:
            run = data['runs'][accepted.run_id]
            run.update(status='running', task_id=task['task_id'], capture_offer_id=offer['id'])
            data['capture_offers'][offer['id']].update(status='saving', action_input_id=accepted.message_id)
        with patch.object(self.harness, 'start'):
            self.harness.recover()
        self.assertEqual(self.offer()['status'], 'failed')
        self.capture.return_value = committing_result(offer['draft']['content'])
        self.action(self.offer(), 'capture_save')
        self.assertEqual(self.offer()['status'], 'saving')
        self.capture.assert_called_once()

    def test_failed_hint_and_missing_binding_never_invite(self):
        task = self.start_lesson()
        self.partial_answer = True
        self.answer()
        self.assertFalse(self.state().get('capture_offers'))
        self.partial_answer = False
        with self.store.transaction(self.sid) as data:
            ctx = data['tasks'][task['task_id']]['context']
            ctx['hint_used'] = True
        self.answer()
        self.assertFalse(self.state().get('capture_offers'))
        with self.store.transaction(self.sid) as data:
            data['tasks'][task['task_id']]['context'].pop('check_binding', None)
        self.answer()
        self.assertFalse(self.state().get('capture_offers'))

    def test_followup_updates_original_visible_scope_and_stale_click_cannot_generate(self):
        task, old = self.start_offer()
        self.followup('外部资料也可能过时，所以需要注意资料版本。')
        updated = self.offer()
        self.assertEqual(updated['id'], old['id'])
        self.assertEqual(updated['anchor_message_id'], old['anchor_message_id'])
        self.assertEqual(updated['version'], old['version'] + 1)
        self.assertEqual(updated['status'], 'offered')
        self.assertIn('资料版本', updated['scope_summary'])
        self.assertIn('资料版本', updated['draft']['content'])
        self.action(old, 'capture_save')
        self.capture.assert_not_called()
        self.assertNotEqual(self.offer()['status'], 'saved')

    def test_correction_replaces_invalid_old_fragments_and_restores_invitation(self):
        _, old = self.start_offer()
        self.followup('准确说法是：只有能访问且检索到的新资料才可能帮助回答。', correction=True)
        updated = self.offer()
        self.assertEqual(updated['id'], old['id'])
        self.assertGreater(updated['version'], old['version'])
        self.assertEqual(updated['status'], 'offered')
        self.assertNotIn(alignment.LESSON, updated['draft']['content'])
        self.assertIn('只有能访问且检索到', updated['draft']['content'])
        self.assertFalse(updated.get('correction_pending'))
        self.capture.assert_not_called()

    def test_new_concept_in_same_step_does_not_change_original_scope(self):
        _, offer = self.start_offer()
        self.followup('切块大小需要结合资料结构选择。', update=False)
        self.assertEqual(self.offer()['draft'], offer['draft'])
        self.assertEqual(self.offer()['version'], offer['version'])
        self.assertNotIn('切块大小', self.offer()['draft']['content'])

    def test_later_then_update_retains_inbox_status_without_reteaching(self):
        task, offer = self.start_offer()
        self.action(offer, 'capture_later')
        self.assertEqual(self.offer()['status'], 'deferred')
        self.assertNotIn('continuation_run_id', self.offer())
        self.followup('外部资料也可能过时，需要核对版本。')
        self.assertEqual(self.offer()['status'], 'deferred')
        self.assertEqual(current_step(self.state()['tasks'][task['task_id']])['id'], current_step(task)['id'])

    def test_click_freezes_updated_scope_and_only_ack_confirms_saved(self):
        task, offer = self.start_offer()
        self.followup('外部资料也可能过时，需要核对版本。')
        offer = self.offer()
        self.capture.return_value = committing_result(offer['draft']['content'])
        self.action(offer, 'capture_save')
        self.assertEqual(self.capture.call_args.args[1], offer['draft']['content'])
        saving = self.offer()
        self.assertEqual(saving['status'], 'saving')
        commit = self.state()['tasks'][saving['save_task_id']]
        ids = [k['id'] for k in commit['memory_package']['knowledge']]
        with patch.object(self.harness, 'start'):
            self.harness.acknowledge_task(commit['task_id'], len(commit['events']), ids)
        saved = self.offer()
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(saved['knowledge_ids'], ids)
        self.assertNotIn('continuation_run_id', saved)
        self.assertEqual(self.state()['active_task_id'], task['task_id'])
        self.assertEqual(current_step(self.state()['tasks'][task['task_id']])['id'], current_step(task)['id'])
        self.action(offer, 'capture_save')
        self.capture.assert_called_once()

    def test_foreign_or_invented_update_is_rejected_before_publication(self):
        from agent_service.knowledge_invitation import validate_update, candidates
        from agent_service.openai_client import ModelCallError
        _, offer = self.start_offer()
        state = self.state()
        run = state['runs'][state['messages'][-1]['run_id']]
        allowed = candidates(self.harness, state, run)
        valid = dict(offer_id=offer['id'], version=1, retained_fragment_ids=[], evidence_quotes=['真实补充'], scope_summary='真实补充')
        for change in [dict(offer_id='foreign'), dict(version=2), dict(retained_fragment_ids=['foreign']), dict(evidence_quotes=['不存在'])]:
            with self.subTest(change=change), self.assertRaises(ModelCallError):
                validate_update(dict(valid, **change), '真实补充', allowed)

    def test_final_reply_and_invitation_restore_together_without_reoffering(self):
        _, offer = self.start_offer()
        snapshot = self.harness.export_snapshot(self.sid)
        self.harness.recover()
        self.harness.drain(self.sid)
        self.assertEqual(list(self.state()['capture_offers']), [offer['id']])
        self.assertEqual(snapshot['checkpoint']['capture_offers'][offer['id']]['version'], self.offer()['version'])

    def test_failed_save_then_correction_updates_original_invitation_and_retry_uses_new_scope(self):
        task, offer = self.start_offer()
        self.capture.return_value = dict(outcome='retryable_failed', error_code='RT.MEMORY.GENERATION_FAILED')
        self.action(offer, 'capture_save')
        failed = self.offer()
        failed_task = copy.deepcopy(self.state()['tasks'][failed['save_task_id']])
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(self.state()['draft']['id'], offer['id'])

        correction = '只有可访问且检索到的新资料才可能帮助回答。'
        self.followup(correction, correction=True)
        updated = self.offer()
        state = self.state()
        self.assertEqual(updated['id'], offer['id'])
        self.assertGreater(updated['version'], failed['version'])
        self.assertEqual(updated['status'], 'failed')
        self.assertIn(correction, updated['draft']['content'])
        self.assertNotIn(alignment.LESSON, updated['draft']['content'])
        self.assertFalse(updated.get('correction_pending'))
        self.assertIsNone(state['draft'])
        self.assertIsNone(state['pending'])
        self.assertEqual(state['active_task_id'], task['task_id'])
        self.assertEqual(state['tasks'][failed['save_task_id']], failed_task)
        self.capture.assert_called_once()

        self.capture.return_value = committing_result(updated['draft']['content'])
        self.action(updated, 'capture_save')
        self.assertEqual(self.capture.call_count, 2)
        self.assertEqual(self.capture.call_args.args[1], updated['draft']['content'])
        self.assertEqual(self.offer()['status'], 'saving')
        self.assertNotEqual(self.offer()['save_task_id'], failed['save_task_id'])

    def test_retry_save_crash_at_real_entry_recovers_despite_previous_failed_task_id(self):
        class SimulatedCrash(BaseException):
            pass

        _, offer = self.start_offer()
        self.capture.return_value = dict(outcome='retryable_failed', error_code='RT.MEMORY.GENERATION_FAILED')
        self.action(offer, 'capture_save')
        failed = self.offer()
        failed_task = copy.deepcopy(self.state()['tasks'][failed['save_task_id']])
        with patch.object(self.harness, '_save_memory', side_effect=SimulatedCrash):
            with self.assertRaises(SimulatedCrash):
                self.action(failed, 'capture_save')
        self.assertEqual(self.offer()['status'], 'saving')
        self.assertEqual(self.offer()['save_task_id'], failed['save_task_id'])
        with patch.object(self.harness, 'start'):
            self.harness.recover()
        recovered = self.offer()
        self.assertEqual(recovered['status'], 'failed')
        self.assertIsNone(self.state()['pending'])
        self.assertEqual(self.state()['tasks'][failed['save_task_id']], failed_task)

        self.capture.return_value = committing_result(recovered['draft']['content'])
        self.action(recovered, 'capture_save')
        self.assertEqual(self.capture.call_count, 2)
        self.assertEqual(self.offer()['status'], 'saving')

    def test_recover_preserves_claimed_save_and_receipt_still_confirms_result(self):
        _, offer = self.start_offer()
        self.capture.return_value = committing_result(offer['draft']['content'])
        accepted = self.action(offer, 'capture_save')
        saving = self.offer()
        self.harness.claim_commit(saving['save_task_id'])
        with self.store.transaction(self.sid) as data:
            # Model a crash between execution and the worker's completed marker.
            data['runs'][accepted.run_id].update(status='running', execution_complete=False)
            data['foreground'] = accepted.run_id
        with patch.object(self.harness, 'start'):
            self.harness.recover()
        self.assertEqual(self.offer()['status'], 'saving')
        commit = self.state()['tasks'][saving['save_task_id']]
        ids = [item['id'] for item in commit['memory_package']['knowledge']]
        with patch.object(self.harness, 'start'):
            self.harness.acknowledge_task(commit['task_id'], len(commit['events']), ids)
        self.assertEqual(self.offer()['status'], 'saved')
        self.assertEqual(self.offer()['knowledge_ids'], ids)
        self.capture.assert_called_once()
