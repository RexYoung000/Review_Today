"""Save receipts survive stop; unpersisted obsolete claims remain reversible."""
import copy
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from agent_service.main import app
from tests import test_conversation_v2 as fixture_module


class CommitRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture_module.ConversationTests()
        self.f.setUp()
        self.run, self.task_id = self.f.make_committable()
        self.claim = self.f.harness.claim_commit(self.task_id)
        self.binding = (self.run.run_id, self.claim['commit_revision'])
        self.ids = [item['id'] for item in self.claim['memory_package']['knowledge']]

    def tearDown(self):
        self.f.tearDown()

    def release(self):
        return self.f.harness.release_commit(self.task_id, *self.binding)

    def stop(self):
        self.f.control(self.run.run_id, 'stop')

    def test_saved_late_ack_and_duplicates_finish_without_restart(self):
        self.stop()
        with self.assertRaisesRegex(ValueError, 'COMMIT_REVOKED'):
            self.f.harness.claim_commit(self.task_id)
        before = len(self.f.calls)
        view = self.f.harness.acknowledge_task(self.task_id, 0, self.ids)
        again = self.f.harness.acknowledge_task(self.task_id, 0, self.ids)
        self.assertEqual(view['status'], 'completed')
        self.assertEqual(again['status'], 'completed')
        self.assertTrue(self.f.state()['paused'])
        self.assertIsNone(self.f.state()['foreground'])
        self.assertEqual(len(self.f.calls), before)
        with self.assertRaisesRegex(ValueError, 'COMMIT_NOT_CLAIMED'):
            self.release()

    def test_unwritten_release_is_idempotent_and_preserves_package(self):
        self.stop()
        package = copy.deepcopy(self.f.state()['tasks'][self.task_id]['memory_package'])
        first, second = self.release(), self.release()
        self.assertEqual(first['status'], 'awaiting_user')
        self.assertEqual(second['last_event_seq'], first['last_event_seq'])
        state = self.f.state()
        task = state['tasks'][self.task_id]
        self.assertFalse(task['context']['commit_claimed'])
        self.assertEqual(task['memory_package'], package)
        offer = state['capture_offers'][task['context']['capture_offer_id']]
        self.assertEqual(offer['status'], 'failed')
        self.assertEqual(offer['knowledge_ids'], [])
        self.assertTrue(state['paused'])
        with self.assertRaisesRegex(ValueError, 'COMMIT_REVOKED'):
            self.f.harness.acknowledge_task(self.task_id, 0, self.ids)

    def test_current_claim_cannot_be_released(self):
        before = self.f.state()
        with self.assertRaisesRegex(ValueError, 'COMMIT_STILL_CURRENT'):
            self.release()
        self.assertEqual(self.f.state(), before)

    def test_receipt_recovery_never_starts_deferred_teaching_before_stop_arrives(self):
        with self.f.store.transaction(self.f.sid) as data:
            offer = data['capture_offers'][data['tasks'][self.task_id]['context']['capture_offer_id']]
            offer.update(continuation_consumed=False, next_request='继续讲下一节')
        before = len(self.f.state()['runs'])
        self.f.harness.acknowledge_task(self.task_id, 0, self.ids, allow_continuation=False)
        self.assertEqual(len(self.f.state()['runs']), before)
        self.assertIsNone(self.f.state()['foreground'])

    def test_release_is_bound_to_both_origin_and_revision(self):
        self.stop()
        for origin, revision in [(str(uuid.uuid4()), self.binding[1]), (self.binding[0], self.binding[1] + 1)]:
            with self.subTest(origin=origin, revision=revision):
                with self.assertRaisesRegex(ValueError, 'COMMIT_REVOKED'):
                    self.f.harness.release_commit(self.task_id, origin, revision)
        self.assertTrue(self.f.state()['tasks'][self.task_id]['context']['commit_claimed'])

    def test_explicit_same_version_save_reuses_package_and_fences_old_release(self):
        self.stop()
        self.release()
        state = self.f.state()
        old_package = copy.deepcopy(state['tasks'][self.task_id]['memory_package'])
        offer = state['capture_offers'][state['tasks'][self.task_id]['context']['capture_offer_id']]
        before = self.f.capture.call_count
        resumed = self.f.send('保存为知识卡', operation=dict(kind='capture_save', target_id=offer['id'], version=offer['version']))
        task = self.f.state()['tasks'][self.task_id]
        self.assertEqual(task['status'], 'committing')
        self.assertEqual(task['memory_package'], old_package)
        self.assertEqual(self.f.capture.call_count, before)
        self.assertEqual(task['context']['origin_run_id'], resumed.run_id)
        self.f.harness.claim_commit(self.task_id)
        with self.assertRaisesRegex(ValueError, 'COMMIT_REVOKED'):
            self.release()
        self.assertTrue(self.f.state()['tasks'][self.task_id]['context']['commit_claimed'])
        self.assertEqual(self.f.harness.acknowledge_task(self.task_id, 0, self.ids)['status'], 'completed')

    def test_changed_content_does_not_reuse_old_package(self):
        self.stop()
        self.release()
        with self.f.store.transaction(self.f.sid) as data:
            offer = data['capture_offers'][data['tasks'][self.task_id]['context']['capture_offer_id']]
            offer['draft']['content'] += '\n这是已确认的新内容。'
        state = self.f.state()
        offer = state['capture_offers'][state['tasks'][self.task_id]['context']['capture_offer_id']]
        before = self.f.capture.call_count
        self.f.send('保存修订内容', operation=dict(kind='capture_save', target_id=offer['id'], version=offer['version']))
        self.assertGreater(self.f.capture.call_count, before)

    def test_http_release_validates_binding_and_records_no_success_receipt(self):
        self.stop()
        with patch('agent_service.main.conversation_harness', self.f.harness):
            client = TestClient(app)
            path = f'/v2/tasks/{self.task_id}/commit-release'
            self.assertEqual(client.post(path, json={'run_id': 'bad', 'commit_revision': 1}).status_code, 422)
            bad = client.post(path, json={'run_id': str(uuid.uuid4()), 'commit_revision': self.binding[1]})
            self.assertEqual(bad.status_code, 409)
            response = client.post(path, json={'run_id': self.binding[0], 'commit_revision': self.binding[1]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'awaiting_user')
            self.assertFalse(self.f.state()['tasks'][self.task_id]['context']['commit_claimed'])
