import unittest
import uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
import agent_service.main as main
from tests.test_conversation_v2 import intent
import tests.test_conversation_v2 as fixtures


class ConversationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ConversationTests()
        self.fixture.setUp()
        self.h = self.fixture.harness
        self.sid = self.fixture.sid
        self.patches = [patch.object(main, "conversation_harness", self.h), patch.object(main, "harness_store", self.fixture.tasks), patch.object(self.h, "start")]
        for p in self.patches: p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches): p.stop()
        self.fixture.tearDown()

    def submit(self, text="你好"):
        return self.client.post(f"/v2/sessions/{self.sid}/messages", json={"client_message_id": str(uuid.uuid4()), "content": text})

    def test_accepts_before_model_and_does_not_create_task(self):
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["task_id"])
        self.assertEqual(self.fixture.calls, [])
        self.h.drain(self.sid)
        run = self.client.get("/v2/runs/" + response.json()["run_id"]).json()
        self.assertEqual(run["status"], "completed")
        self.assertNotIn("steps", run)

    def test_incremental_session_events_and_ack_reject_ahead(self):
        self.submit()
        self.h.drain(self.sid)
        page = self.client.get(f"/v2/sessions/{self.sid}/events?after_seq=1").json()
        self.assertEqual(page["events"][0]["seq"], 2)
        ack = self.client.post(f"/v2/sessions/{self.sid}/ack", json={"last_event_seq": page["last_seq"]})
        self.assertEqual(ack.status_code, 200)
        ahead = self.client.post(f"/v2/sessions/{self.sid}/ack", json={"last_event_seq": page["last_seq"] + 1})
        self.assertEqual(ahead.status_code, 409)

    def test_recovery_delta_catches_up_before_background_snapshot(self):
        from agent_service.checkpoint_delta import apply_changes, recovery_projection
        self.submit()
        first = self.client.get(f"/v2/sessions/{self.sid}/events").json()
        state = first["recovery"]["checkpoint"]
        version = first["recovery"]["version"]
        self.h.drain(self.sid)
        page = self.client.get(f"/v2/sessions/{self.sid}/events?after_seq={first['last_seq']}&recovery_version={version}").json()
        for delta in page["recovery"]["deltas"]:
            self.assertEqual(delta["base_version"], version)
            state = apply_changes(state, delta["changes"])
            version = delta["version"]
        self.assertEqual(state, recovery_projection(self.h.store.get(self.sid)))
        self.assertEqual(state["event_base_seq"], page["last_seq"])
        calls = len(self.fixture.calls)
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        fresh = ConversationHarness(ConversationStore(HarnessStore(self.fixture.tmp.name + "/delta-restored.sqlite3")))
        restored = fresh.restore_snapshot(self.sid, dict(schema_version=1, session_id=self.sid, checkpoint=state))
        self.assertTrue(restored["checkpoint"]["paused"])
        self.assertIsNone(restored["checkpoint"]["pending"])
        self.assertEqual(len(self.fixture.calls), calls)

    def test_old_recovery_version_gets_full_snapshot_not_broken_delta(self):
        self.submit()
        for i in range(36):
            with self.h.store.transaction(self.sid) as data:
                data["summary_version"] = i
        page = self.client.get(f"/v2/sessions/{self.sid}/events?recovery_version=1").json()
        self.assertIn("checkpoint", page["recovery"])
        self.assertEqual(page["recovery"]["checkpoint"]["summary_version"], 35)

    def test_run_controls_are_idempotent_and_stop_does_not_delete_message(self):
        accepted = self.submit().json()
        path = f"/v2/runs/{accepted['run_id']}/actions"
        body = {"action_id": str(uuid.uuid4()), "action": "stop"}
        first = self.client.post(path, json=body).json()
        again = self.client.post(path, json=body).json()
        self.assertEqual(first["revision"], again["revision"])
        self.assertEqual(len(self.h.store.get(self.sid)["messages"]), 1)

    def test_legacy_task_action_cannot_bypass_versioned_consent(self):
        self.fixture.decision = intent("goal", workflow="source_learning", scope="learning")
        self.submit("学习 RAG")
        self.h.drain(self.sid)
        task_id = self.h.store.get(self.sid)["active_task_id"]
        response = self.client.post(f"/v2/tasks/{task_id}/actions", json={"action_id": str(uuid.uuid4()), "action_type": "form_memory", "content": "不要保存"})
        self.assertEqual(response.status_code, 409)
        self.fixture.capture.assert_not_called()

    def test_unknown_session_ack_is_not_a_session_creation(self):
        response = self.client.post(f"/v2/sessions/{self.sid}/ack", json={"last_event_seq": 0})
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(self.h.store.get(self.sid))

    def test_legacy_rejected_action_is_not_consumed_before_acceptance(self):
        self.fixture.decision = intent("goal", workflow="source_learning", scope="learning")
        self.submit("学习 RAG")
        self.h.drain(self.sid)
        task_id = self.h.store.get(self.sid)["active_task_id"]
        path = f"/v2/tasks/{task_id}/actions"
        body = {"action_id": str(uuid.uuid4()), "action_type": "respond", "content": "请解释第二点"}
        with patch.object(self.h, "accept", side_effect=ValueError("RT.RUN.TEMPORARY_CONFLICT")):
            self.assertEqual(self.client.post(path, json=body).status_code, 409)
        self.assertNotIn(body["action_id"], self.fixture.tasks.get(task_id).processed_action_ids)
        self.assertEqual(self.client.post(path, json=body).status_code, 200)
        first = len(self.h.store.get(self.sid)["messages"])
        self.assertEqual(self.client.post(path, json=body).status_code, 200)
        self.assertEqual(len(self.h.store.get(self.sid)["messages"]), first)
        self.assertEqual(self.client.post(path, json=body | {"content":"不要保存"}).status_code, 409)


if __name__ == "__main__": unittest.main()
