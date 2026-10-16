"""Saved-result notices preserve scope; neither notices nor model prose prove a save."""
import copy
import json
from pathlib import Path
import unittest

from agent_service.knowledge_capture_status import facts, reply
from agent_service.schemas import IntentDecision
from tests import test_conversation_v2 as fixtures


ROOT = Path(__file__).resolve().parents[2]
REAL = ROOT / "docs/evidence/2026-10-16-native-save-continuation/repair"


def recorded():
    data = json.loads((REAL / "phase-06-status-mismatch.json").read_text())
    proposal = list(data["runs"].values())[-1]["intent"]["status_context"]
    baseline = json.loads((REAL / "status-query-baseline.json").read_text())
    return data, proposal, baseline


class SaveResultScopeTests(unittest.TestCase):
    def setUp(self):
        self.data, self.proposal, self.baseline = recorded()
        self.offer = next(iter(self.data["capture_offers"].values()))
        self.commit = self.data["tasks"][self.offer["save_task_id"]]
        self.notice_run = self.data["runs"][self.baseline["cleared_by_run_id"]]

    def current(self):
        before = copy.deepcopy(self.data)
        result = facts(self.data, status_context=self.proposal)
        self.assertEqual(self.data, before, "Reading a result must not rewrite chat, task, offer or receipt")
        return result

    def add_lesson(self, *, correction=False):
        message = dict(message_id="new-explanation", run_id="new-learning", role="coach",
                       content="检索结果还需要按使用场景检查，不能只比较相似度。")
        owner = self.offer["origin_task_id"] if correction else "new-topic-task"
        self.data["messages"].append(message)
        self.data["runs"]["new-learning"] = dict(status="completed", task_id=owner,
            activity_kind="knowledge_answer", intent=dict(relation="continuation" if correction else "new_topic",
                                                        intents=["correction" if correction else "question"]))
        self.proposal = dict(focus=[dict(message_id=message["message_id"], quote=message["content"],
                                        label="使用场景核对")], prior_claim=None)
        return message

    def test_recorded_failed_save_then_success_answers_matching_four_card_receipt(self):
        result = self.current()
        self.assertEqual(result["stage"], "saved")
        self.assertEqual(set(result["current_knowledge_ids"]), set(self.offer["knowledge_ids"]))
        self.assertEqual(len(result["current_knowledge_ids"]), 4)
        self.assertIn("已成功写入 4 张知识卡", reply(result, self.proposal))
        self.assertNotIn("还没有整理成知识卡", reply(result, self.proposal))
        self.assertNotIn(self.baseline["cleared_by_message_id"],
                         [s["message_id"] for s in result["discussion_sources"]])

    def test_retention_of_scope_does_not_depend_on_old_event_page(self):
        # Session events may be compacted while the message, run and task remain.
        self.data["events"] = []
        self.assertEqual(self.current()["stage"], "saved")

    def test_result_classification_does_not_guess_from_failure_wording(self):
        for message in self.data["messages"]:
            if message["message_id"] == self.baseline["cleared_by_message_id"]:
                message["content"] = "处理结果需要查看，当前请求已结束。"
        self.assertEqual(self.current()["stage"], "saved")

    def test_still_failed_save_keeps_failure_without_borrowing_other_receipts(self):
        self.offer.update(status="failed", knowledge_ids=[])
        self.commit.update(status="needs_attention", memory_package=None, events=[])
        result = self.current()
        self.assertEqual(result["stage"], "failed")
        self.assertEqual(result["current_knowledge_ids"], [])
        self.assertIn("尚未完成", reply(result, self.proposal))

    def test_no_ack_or_mismatched_ids_never_become_saved(self):
        for change in ("missing_ack", "mismatched_ids"):
            with self.subTest(change=change):
                self.setUp()
                if change == "missing_ack":
                    self.commit["events"] = [e for e in self.commit["events"] if e.get("node") != "mac_ack"]
                else:
                    self.offer["knowledge_ids"] = ["another-card"]
                result = self.current()
                self.assertEqual(result["stage"], "saving")
                self.assertEqual(result["current_knowledge_ids"], [])

    def test_new_topic_after_save_does_not_inherit_old_success(self):
        message = self.add_lesson()
        result = self.current()
        self.assertEqual(result["stage"], "unorganized")
        self.assertEqual([m["message_id"] for m in result["discussion_sources"]], [message["message_id"]])
        self.assertEqual(result["current_knowledge_ids"], [])
        self.assertEqual(len(result["session_saved_knowledge_ids"]), 4)

    def test_delayed_old_save_result_cannot_restore_scope_after_a_new_topic(self):
        notice = next(m for m in self.data["messages"] if m["message_id"] == self.baseline["cleared_by_message_id"])
        self.data["messages"].remove(notice)
        message = self.add_lesson()
        self.data["messages"].append(notice)
        result = self.current()
        self.assertEqual(result["stage"], "unorganized")
        self.assertEqual([m["message_id"] for m in result["discussion_sources"]], [message["message_id"]])

    def test_correction_and_invalidated_version_do_not_use_old_saved_receipt(self):
        self.offer.update(status="invalidated", version=self.offer["version"] + 1)
        self.offer["draft"]["invalidated"] = True
        self.assertEqual(self.current()["stage"], "invalidated", "Old scope must keep its invalidation")
        self.add_lesson(correction=True)
        result = self.current()
        self.assertEqual(result["stage"], "unorganized", "The new correction has no matching save")
        self.assertEqual(result["current_knowledge_ids"], [])

    def test_invalidated_stopped_or_stale_notice_is_not_allowed_to_bypass_fences(self):
        for change in ("stopped", "run_invalidated", "task_invalidated", "stale_revision"):
            with self.subTest(change=change):
                self.setUp()
                if change == "stopped":
                    self.notice_run["status"] = "interrupted"
                elif change == "run_invalidated":
                    self.notice_run["memory_invalidated"] = True
                elif change == "task_invalidated":
                    self.commit["context"]["memory_invalidated"] = True
                else:
                    self.notice_run["revision"] += 1
                self.assertNotEqual(self.current()["stage"], "saved")

    def test_metadata_without_a_matching_program_owned_task_is_not_transparent(self):
        for change in ("missing_offer_binding", "wrong_task_mode", "unmanaged_task", "foreign_task", "new_topic"):
            with self.subTest(change=change):
                self.setUp()
                if change == "missing_offer_binding":
                    self.commit["context"]["capture_offer_id"] = "unrelated-offer"
                elif change == "wrong_task_mode":
                    self.commit["mode"] = "source_learning"
                elif change == "unmanaged_task":
                    self.commit["context"]["conversation_managed"] = False
                elif change == "foreign_task":
                    self.commit["session_id"] = "foreign-session"
                else:
                    self.notice_run["intent"] = dict(relation="new_topic")
                self.assertNotEqual(self.current()["stage"], "saved")

    def test_real_teaching_on_a_bound_run_still_changes_the_learning_scope(self):
        self.notice_run.update(activity_kind="knowledge_answer", learning_concepts=["新的知识"])
        self.assertNotEqual(self.current()["stage"], "saved")


class SaveResultRoutingTests(unittest.TestCase):
    def test_two_queries_reuse_the_recorded_router_output_without_capture_or_state_writes(self):
        data, _, _ = recorded()
        f = fixtures.ConversationTests()
        f.setUp()
        try:
            f.sid = data["session_id"]
            with f.store.transaction(f.sid) as current:
                current.update(copy.deepcopy(data))
            f.decision = IntentDecision.model_validate(list(data["runs"].values())[-1]["intent"])
            before = copy.deepcopy(f.state())
            for _ in range(2):
                accepted = f.send("刚才保存的 RAG 知识卡存好了吗？实际保存了几张？", mode=data["mode"])
                after = f.state()
                self.assertEqual(after["runs"][accepted.run_id]["status"], "completed")
                self.assertIn("已成功写入 4 张知识卡", after["messages"][-1]["content"])
                self.assertEqual(after["tasks"], before["tasks"])
                self.assertEqual(after["capture_offers"], before["capture_offers"])
                self.assertEqual(after["draft"], before["draft"])
                self.assertEqual(after["messages"][:len(before["messages"])], before["messages"])
            self.assertEqual([schema for schema, _ in f.calls], [IntentDecision, IntentDecision])
            f.capture.assert_not_called()
        finally:
            f.tearDown()


if __name__ == "__main__":
    unittest.main()
