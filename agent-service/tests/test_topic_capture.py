"""Sanitized, context-bearing regressions for A001–A004."""
import unittest
from unittest.mock import patch
from tests import test_conversation_v2 as fixtures
from tests.test_m1_capture_contract import committing_result
intent = fixtures.intent
from agent_service.schemas import IntentDecision, ConversationOutput

class TopicCaptureTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ConversationTests(); self.f.setUp()
    def tearDown(self):
        self.f.tearDown()
    def teach(self):
        self.f.decision = intent('question', scope='conversation')
        self.f.send('RAG 和微调有什么区别？')
        return [m for m in self.f.state()['messages'] if m['role'] == 'coach'][-1]
    def close(self, next_request=''):
        answer = self.teach()
        self.f.decision = IntentDecision.model_validate(dict(intents=['self_report'], relation='continuation', scope='conversation', rationale='用户明确收尾', understanding='self_reported', topic_closure=dict(evidence='明白了', title='RAG 与微调', message_ids=[answer['message_id']], next_request=next_request)))
        self.f.send('明白了' + ('，' + next_request if next_request else ''))
        return list(self.f.state().get('capture_offers', {}).values())[-1]
    def act(self, offer, kind):
        self.f.decision = intent('question')
        return self.f.send(kind, operation=dict(kind=kind, target_id=offer['id'], version=offer['version']))
    def test_real_defer_with_continue_goal_is_short_and_does_not_teach(self):
        self.f.decision = intent('question', scope='learning', workflow='problem_solving')
        self.f.send('学习检索增强生成', mode='problem_solving')
        task = self.f.state()['active_task_id']; self.assertIsNotNone(task); before = len(self.f.calls)
        self.f.decision = intent('defer', scope='continue_goal', target_task_id=task)
        self.f.send('算了，晚点再学吧')
        self.assertEqual(self.f.state()['active_task_id'], task)
        self.assertFalse(any(schema is ConversationOutput for schema, _ in self.f.calls[before:]))
        self.assertEqual(self.f.state()['messages'][-1]['content'], '好的，你慢慢想。准备好后继续。')
        self.assertEqual([s for s, _ in self.f.calls[before:]], [IntentDecision])
    def test_answer_completion_alone_never_offers_capture(self):
        self.teach(); self.assertFalse(self.f.state().get('capture_offers'))
    def test_user_closure_creates_offer_without_teaching_next(self):
        offer = self.close('接下来讲 Agent')
        self.assertEqual(offer['status'], 'offered')
        self.assertEqual(offer['next_request'], '接下来讲 Agent')
        self.assertFalse(offer['continuation_consumed'])
    def test_later_retains_snapshot_and_continues_once(self):
        offer = self.close('接下来讲 Agent')
        self.act(offer, 'capture_later')
        saved = self.f.state()['capture_offers'][offer['id']]
        self.assertEqual(saved['status'], 'deferred')
        self.assertEqual(saved['draft'], offer['draft'])
        self.assertTrue(saved['continuation_consumed'])
        count = len(self.f.state()['runs'])
        self.act(offer, 'capture_later')
        self.assertEqual(len(self.f.state()['runs']), count + 1)
    def test_continue_action_does_not_ask_for_new_session_again(self):
        offer = self.close('接下来讲 Agent')
        self.f.decision = IntentDecision(intents=['goal'], relation='new_topic', scope='learning',
            workflow='topic_exploration', target_description='Agent 基本组成', direct_teaching=True, rationale='新话题')
        self.f.send('稍后录入', operation=dict(kind='capture_later', target_id=offer['id'], version=1))
        state = self.f.state()
        continuation = state['runs'][state['capture_offers'][offer['id']]['continuation_run_id']]
        self.assertEqual(continuation['status'], 'completed')
        self.assertNotEqual((state.get('pending') or {}).get('kind'), 'new_session')
        self.assertTrue(any(m['role'] == 'coach' and m['run_id'] == continuation['run_id'] for m in state['messages']))

    def test_skip_does_not_create_inbox_work(self):
        offer = self.close(); self.act(offer, 'capture_skip')
        self.assertEqual(self.f.state()['capture_offers'][offer['id']]['status'], 'skipped')

    def save(self, offer):
        self.f.capture.return_value = committing_result(offer['draft']['content'])
        self.act(offer, 'capture_save')
        return self.f.state()['capture_offers'][offer['id']]
    def ack(self, offer):
        task = self.f.state()['tasks'][offer['save_task_id']]
        ids = [k['id'] for k in task['memory_package']['knowledge']]
        with patch.object(self.f.harness, 'start'):
            self.f.harness.acknowledge_task(task['task_id'], len(task['events']), ids)
        return ids
    def test_save_waits_for_real_receipt_and_duplicate_ack_does_not_reteach(self):
        offer = self.save(self.close('接下来讲 Agent'))
        self.assertEqual(offer['status'], 'saving')
        self.assertFalse(offer['continuation_consumed'])
        self.assertNotIn('continuation_run_id', offer)
        self.ack(offer)
        after = self.f.state()['capture_offers'][offer['id']]
        self.assertEqual(after['status'], 'saved')
        count = len(self.f.state()['runs']); self.ack(offer)
        self.assertEqual(len(self.f.state()['runs']), count)
        self.f.harness.drain(self.f.sid)
        self.f.capture.assert_called_once()
    def test_saving_deferred_topic_does_not_replay_old_next_request(self):
        offer = self.close('接下来讲 Agent'); self.act(offer, 'capture_later')
        previous_task = self.f.state()['active_task_id']
        saved = self.save(offer); count = len(self.f.state()['runs'])
        self.ack(saved)
        self.assertEqual(len(self.f.state()['runs']), count)
        self.assertEqual(self.f.state()['active_task_id'], previous_task)
    def test_pause_revokes_unclaimed_capture_and_never_continues(self):
        offer = self.save(self.close('接下来讲 Agent'))
        self.f.decision = intent('defer', scope='continue_goal', target_task_id=offer['save_task_id'])
        self.f.send('算了，晚点再学吧')
        current = self.f.state()['capture_offers'][offer['id']]
        self.assertEqual(current['status'], 'failed')
        self.assertTrue(current['continuation_consumed'])
        with self.assertRaises(ValueError): self.f.harness.claim_commit(offer['save_task_id'])
    def test_retry_after_generation_failure_retains_offer(self):
        offer = self.close('接下来讲 Agent')
        self.f.capture.side_effect = RuntimeError('generation failed')
        self.act(offer, 'capture_save')
        self.assertEqual(self.f.state()['capture_offers'][offer['id']]['status'], 'failed')
        self.f.capture.side_effect = None
        saved = self.save(offer)
        self.assertEqual(saved['status'], 'saving')
        self.ack(saved)
        self.assertIn('continuation_run_id', self.f.state()['capture_offers'][offer['id']])
    def test_stale_action_never_writes(self):
        offer = self.close(); offer['version'] += 1
        self.act(offer, 'capture_save'); self.f.capture.assert_not_called()
    def test_quoted_and_followup_closure_never_offers(self):
        answer = self.teach()
        for text, names in [('他说“明白了”', ['self_report']), ('明白了，但再举个例子', ['self_report', 'example'])]:
            self.f.decision = IntentDecision.model_validate(dict(intents=names, relation='continuation', scope='conversation', rationale='测试拒绝', understanding='self_reported', topic_closure=dict(evidence='明白了', title='RAG', message_ids=[answer['message_id']])))
            self.f.send(text)
            self.assertFalse(self.f.state().get('capture_offers'))
    def test_new_input_after_save_cancels_pending_continuation(self):
        offer = self.save(self.close('接下来讲 Agent'))
        self.f.decision = intent('thanks')
        self.f.send('谢谢')
        self.ack(offer)
        self.assertNotIn('continuation_run_id', self.f.state()['capture_offers'][offer['id']])

    def test_correction_invalidates_deferred_version(self):
        offer = self.close(); self.act(offer, 'capture_later')
        self.f.decision = intent('correction')
        self.f.send('刚才的解释需要修正')
        self.assertEqual(self.f.state()['capture_offers'][offer['id']]['status'], 'invalidated')
        self.act(offer, 'capture_save'); self.f.capture.assert_not_called()

    def test_mastery_closure_uses_confirmed_knowledge_not_feedback(self):
        self.f.decision = intent('question', workflow='problem_solving', scope='learning')
        self.f.send('解释 RAG', mode='problem_solving')
        with self.f.store.transaction(self.f.sid) as data:
            task = data['tasks'][data['active_task_id']]
            task['stage'] = 'practice'
            task['context']['check_question'] = '解释 RAG'
        for answer in ['先检索资料，再据资料生成', '检索不准时不能保证正确']:
            self.f.decision = intent('answer', scope='continue_goal')
            self.f.send(answer, mode='problem_solving')
        state = self.f.state(); task = state['tasks'][state['active_task_id']]
        self.assertTrue(task['context']['transfer_passed'])
        self.assertFalse(state.get('capture_offers'))
        latest = state['messages'][-1]
        self.assertNotIn('是否要将', latest['content'])
        self.f.decision = IntentDecision(intents=['self_report'], understanding='self_reported', relation='continuation', scope='conversation', rationale='收尾',
            topic_closure=dict(evidence='明白了', title='RAG', message_ids=[latest['message_id']]))
        self.f.send('明白了', mode='problem_solving')
        offer = list(self.f.state()['capture_offers'].values())[-1]
        self.assertEqual(offer['draft']['content'], task['context']['draft']['content'])
        self.assertNotEqual(offer['draft']['content'], latest['content'])

    def test_sources_are_frozen_from_answer_not_later_task_context(self):
        answer = self.teach()
        source = dict(source_id='synthetic-source', version=2, type='public_source', content='原始来源', url='https://example.com/source')
        with self.f.store.transaction(self.f.sid) as state:
            state['runs'][answer['run_id']]['answer_sources'] = [source]
        self.f.decision = IntentDecision(intents=['self_report'], understanding='self_reported', relation='continuation', scope='conversation', rationale='收尾',
            topic_closure=dict(evidence='明白了', title='RAG', message_ids=[answer['message_id']]))
        self.f.send('明白了')
        offer = list(self.f.state()['capture_offers'].values())[-1]
        self.act(offer, 'capture_later')
        self.assertEqual(self.f.state()['capture_offers'][offer['id']]['sources'], [source])

    def test_restored_offer_revision_advances_and_never_resumes_save(self):
        offer = self.save(self.close('接下来讲 Agent'))
        snapshot = self.f.harness.export_snapshot(self.f.sid)
        restored = fixtures.ConversationHarness(fixtures.ConversationStore(fixtures.HarnessStore(str(fixtures.Path(self.f.tmp.name) / 'restored.sqlite3'))))
        result = restored.restore_snapshot(self.f.sid, snapshot)
        current = result['checkpoint']['capture_offers'][offer['id']]
        self.assertEqual(current['status'], 'failed')
        self.assertTrue(current['continuation_consumed'])
        self.assertGreater(result['recovery_version'], snapshot['recovery_version'])
        self.assertNotIn('continuation_run_id', current)

    def test_explicit_save_does_not_reoffer_same_answer(self):
        answer = self.teach()
        self.f.capture.return_value = committing_result(answer['content'])
        self.f.decision = intent('confirm', understanding='self_reported', proposed_actions=[dict(kind='save', disposition='request', evidence='请保存')])
        self.f.send('我明白了，请保存')
        offer = list(self.f.state()['capture_offers'].values())[-1]
        self.ack(offer)
        self.f.decision = IntentDecision(intents=['self_report'], understanding='self_reported', relation='continuation', scope='conversation', rationale='重复收尾',
            topic_closure=dict(evidence='明白了', title='RAG', message_ids=[answer['message_id']]))
        self.f.send('明白了')
        self.assertEqual(len(self.f.state()['capture_offers']), 1)
        self.assertEqual(self.f.state()['capture_offers'][offer['id']]['status'], 'saved')

    def test_save_reference_without_claiming_understanding(self):
        answer = self.teach()
        self.f.capture.return_value = committing_result(answer['content'])
        self.f.decision = intent('confirm', understanding='unknown', proposed_actions=[dict(kind='save', disposition='request', evidence='先保存')])
        self.f.send('我还没学，先保存资料。')
        self.f.capture.assert_called_once()
        offer = list(self.f.state()['capture_offers'].values())[-1]
        self.ack(offer)
        self.assertEqual(self.f.state()['capture_offers'][offer['id']]['status'], 'saved')

    def test_invalidated_source_has_terminal_panel_and_never_saves(self):
        offer = self.close()
        with self.f.store.transaction(self.f.sid) as data:
            data['capture_offers'][offer['id']]['draft']['memory_references'] = [dict(knowledge_id='invalidated-fixture')]
        with patch.object(self.f.store, 'memory_valid', side_effect=lambda refs: not any(r.get('knowledge_id') == 'invalidated-fixture' for r in refs)):
            self.act(offer, 'capture_save')
        self.assertEqual(self.f.state()['capture_offers'][offer['id']]['status'], 'invalidated')
        self.f.capture.assert_not_called()

    def test_multiple_deferred_topics_survive_snapshot(self):
        first = self.close(); self.act(first, 'capture_later')
        second = self.close(); self.act(second, 'capture_later')
        checkpoint = self.f.harness.export_snapshot(self.f.sid)['checkpoint']
        self.assertEqual({first['id'], second['id']}, set(checkpoint['capture_offers']))
        self.assertTrue(all(o['status'] == 'deferred' for o in checkpoint['capture_offers'].values()))

if __name__ == '__main__': unittest.main()
