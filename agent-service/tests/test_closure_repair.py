"""Product regressions from the M1 audit. No provider or real user database."""
import unittest
import uuid
from copy import deepcopy
from unittest.mock import patch

from tests import test_conversation_v2 as fixture
from tests.test_conversation_v2 import intent


class ClosureRepairTests(unittest.TestCase):
    setUp = fixture.ConversationTests.setUp
    tearDown = fixture.ConversationTests.tearDown
    model = fixture.ConversationTests.model
    send = fixture.ConversationTests.send
    state = fixture.ConversationTests.state
    control = fixture.ConversationTests.control

    def test_fetched_source_is_reused_on_generation_retry_and_refresh_has_version(self):
        from agent_service.openai_client import ModelCallError
        from agent_service.schemas import ConversationOutput
        self.decision = intent("material", workflow="source_learning", scope="learning")
        def fail_answer(*args, **kwargs):
            if issubclass(args[2], ConversationOutput): raise ModelCallError("TIMEOUT")
            return self.model(*args, **kwargs)
        with patch("agent_service.conversation.fetch_public_url", return_value=("公开资料", "版本一")) as fetch:
            with patch("agent_service.conversation.parse_model", side_effect=fail_answer):
                accepted = self.send("https://example.com/rag", mode="source_learning")
            self.assertEqual(fetch.call_count, 1)
            self.control(accepted.run_id, "retry")
            self.harness.drain(self.sid)
            self.assertEqual(fetch.call_count, 1, "retry must reuse the completed fetch step")
            task = self.state()["tasks"][self.state()["active_task_id"]]
            original = deepcopy(next(s for s in task["context"]["sources"] if s.get("url") == "https://example.com/rag"))
            self.decision = intent("followup", refresh_sources=True)
            fetch.return_value = ("公开资料", "版本二")
            with self.store.transaction(self.sid) as data:
                data["tasks"][data["active_task_id"]]["context"]["selected_sources"] = ["https://example.com/rag"]
            self.send("刷新资料再解释")
            self.assertEqual(fetch.call_count, 2, "explicit refresh must read a new page snapshot")
        task = self.state()["tasks"][self.state()["active_task_id"]]
        public = [s for s in task["context"]["sources"] if s.get("url") == "https://example.com/rag"]
        self.assertEqual(len(public), 1)
        self.assertEqual(public[0]["type"], "public_source")
        self.assertEqual(public[0]["source_id"], original["source_id"])
        self.assertEqual(public[0]["version"], 2)
        self.assertEqual(public[0]["content"], "版本二")
        self.assertEqual(task["context"]["source_history"], [original])

    def test_mixed_material_keeps_generated_identity(self):
        self.decision = intent("goal", workflow="source_learning", scope="learning", direct_teaching=True)
        self.send("直接教我 RAG")
        original = deepcopy(self.state()["tasks"][self.state()["active_task_id"]]["context"]["sources"][0])
        self.decision = intent("material", "followup")
        result = self.send("补充资料：检索可能采用关键词与向量混合")
        task = self.state()["tasks"][self.state()["active_task_id"]]
        self.assertEqual({s["type"] for s in task["context"]["sources"]}, {"agent_generated", "user_material"})
        self.assertEqual(next(s for s in task["context"]["sources"] if s["type"] == "agent_generated"), original)
        self.assertEqual(self.state()["runs"][result.run_id]["answer_source_type"], "mixed")
        answer = next(payload for schema, payload in reversed(self.calls)
                      if issubclass(schema, fixture.ConversationOutput))
        self.assertEqual(next(s for s in answer["sources"] if s["type"] == "agent_generated"), original)

    def test_mixed_source_retry_preserves_generated_identity_without_duplicates(self):
        from agent_service.openai_client import ModelCallError
        self.decision = intent("goal", workflow="source_learning", scope="learning", direct_teaching=True)
        self.send("直接教我 RAG")
        original = deepcopy(self.state()["tasks"][self.state()["active_task_id"]]["context"]["sources"][0])
        self.decision = intent("material", "followup")
        def fail_answer(*args, **kwargs):
            if issubclass(args[2], fixture.ConversationOutput):
                raise ModelCallError("TIMEOUT")
            return self.model(*args, **kwargs)
        with patch("agent_service.conversation.parse_model", side_effect=fail_answer):
            result = self.send("补充资料：检索可能采用关键词与向量混合")
        self.assertEqual(self.state()["runs"][result.run_id]["status"], "retryable_failed")
        self.control(result.run_id, "retry")
        self.harness.drain(self.sid)
        sources = self.state()["tasks"][self.state()["active_task_id"]]["context"]["sources"]
        self.assertEqual(len(sources), 2)
        self.assertEqual(next(s for s in sources if s["type"] == "agent_generated"), original)
        self.assertEqual(self.state()["runs"][result.run_id]["status"], "completed")
        reopened = fixture.ConversationStore(fixture.HarnessStore(self.tmp.name + "/test.sqlite3"))
        restored = reopened.get(self.sid)
        self.assertEqual(restored["tasks"][restored["active_task_id"]]["context"]["sources"], sources)

    def test_generated_lecture_is_not_evidence_for_missing_supplied_material(self):
        from agent_service.conversation_materials import MaterialReadiness
        self.decision = intent("goal", workflow="source_learning", scope="learning", direct_teaching=True)
        self.send("直接教我 RAG")
        original = deepcopy(self.state()["tasks"][self.state()["active_task_id"]]["context"]["sources"][0])
        self.decision = intent("material", "followup")
        with patch("agent_service.conversation.fetch_public_url", return_value=("登录", "请先登录")):
            result = self.send("https://example.com/rag")
        run = self.state()["runs"][result.run_id]
        self.assertFalse(run["material_readiness"]["can_proceed"])
        assessment = next(payload for schema, payload in reversed(self.calls) if schema is MaterialReadiness)
        self.assertFalse(any(s["type"] == "agent_generated" for s in assessment["sources"]))
        sources = self.state()["tasks"][self.state()["active_task_id"]]["context"]["sources"]
        self.assertEqual(next(s for s in sources if s["type"] == "agent_generated"), original)

    def test_search_uses_minimal_public_topic_not_private_material(self):
        self.decision = intent("question", needs_verification=True, public_search_query="贷款基准利率 官方标准")
        with patch("agent_service.conversation.web_search_text", return_value="") as search:
            self.send("私人材料：客户电话 13812345678。请解释当前贷款基准利率。")
            self.assertNotIn("13812345678", search.call_args.args[0])
            self.assertNotIn("私人材料", search.call_args.args[0])
        self.assertEqual(self.harness._public_query("私人电话 13812345678"), "")

    def test_mastery_complete_before_optional_save_and_decline_clears_action(self):
        self.decision = intent("question", workflow="problem_solving")
        self.send("RAG 是什么", mode="problem_solving")
        self.decision = intent("answer")
        self.send("我刚接触，需要理解检索与生成的关系")
        self.send("先检索后生成")
        self.send("换成企业资料需要考虑权限和召回质量")
        task = next(iter(self.state()["tasks"].values()))
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["context"]["understanding"], "verified")
        self.send("暂不保存", operation={**self.state()["pending"], "kind": "reject_save"})
        task = next(iter(self.state()["tasks"].values()))
        self.assertEqual(task["status"], "completed")
        self.assertIsNone(task["required_action"])
        self.assertIsNone(self.state()["pending"])
        self.capture.assert_not_called()

    def test_generated_source_survives_skipped_check(self):
        self.decision = intent("goal", workflow="source_learning", scope="learning", direct_teaching=True)
        self.send("直接教我 RAG")
        self.decision = intent("skip_check")
        self.send("先跳过检查")
        task = next(iter(self.state()["tasks"].values()))
        self.assertEqual(task["context"]["source_type"], "agent_generated")
        self.assertNotEqual(task["context"]["understanding"], "verified")
        self.assertTrue(task["context"]["learning_plan"]["steps"])

    def test_archive_blocks_all_execution_restore_does_not_resume(self):
        run = self.send(drain=False)
        self.harness.session_action(self.sid, str(uuid.uuid4()), "archive", 1)
        with self.assertRaisesRegex(ValueError, "ARCHIVED"):
            self.send("新问题")
        with self.assertRaisesRegex(ValueError, "ARCHIVED"):
            self.control(run.run_id, "resume")
        self.harness.session_action(self.sid, str(uuid.uuid4()), "restore", 2)
        self.harness.drain(self.sid)
        self.assertEqual(self.state()["runs"][run.run_id]["status"], "interrupted")
        self.assertEqual(self.calls, [])

    def test_snapshot_restore_is_read_only_and_idempotent(self):
        self.send("你好")
        snapshot = self.harness.export_snapshot(self.sid)
        self.assertEqual(snapshot["schema_version"], 1)
        with self.assertRaisesRegex(ValueError, "EXISTS"):
            self.harness.restore_snapshot(self.sid, snapshot)
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        fresh = ConversationHarness(ConversationStore(HarnessStore(self.tmp.name + "/restored.sqlite3")))
        calls = len(self.calls)
        first = fresh.restore_snapshot(self.sid, snapshot)
        repeated = fresh.restore_snapshot(self.sid, snapshot)
        self.assertEqual(first, repeated)
        self.assertEqual(len(self.calls), calls)
        self.assertTrue(first["checkpoint"]["paused"])
        self.assertIsNone(first["checkpoint"]["pending"])

    def test_summary_failure_does_not_fail_success(self):
        for i in range(12):
            self.send(f"你好 {i}")
        with self.store.transaction(self.sid) as data:
            for m in data["messages"]:
                if m["role"] == "user": m["content"] = "a" * 42000
        with patch("agent_service.conversation.parse_model", side_effect=RuntimeError("secret failure")):
            self.harness.maintain_summary(self.sid)
        self.assertTrue(all(r["status"] == "completed" for r in self.state()["runs"].values()))
        self.assertFalse(self.state()["paused"])
        self.assertIn("summary_error", self.state())

    def test_replaced_plan_does_not_inherit_old_question_verification(self):
        from agent_service.learning_progress import set_plan
        self.decision = intent("goal", workflow="source_learning", scope="learning", direct_teaching=True)
        self.send("直接教我 RAG")
        with self.store.transaction(self.sid) as data:
            set_plan(data["tasks"][data["active_task_id"]], ["检索", "生成"])
        self.decision = intent("answer")
        self.send("检索是从资料中取得相关片段")
        task = self.state()["tasks"][self.state()["active_task_id"]]
        self.assertEqual(task["context"]["learning_plan"]["steps"][0]["understanding"], "unknown")
        self.assertEqual(task["context"]["learning_plan"]["steps"][1]["state"], "pending")
        self.assertNotEqual(task["status"], "completed")
        self.assertIsNone(self.state()["pending"])

    def test_ack_does_not_discard_context_before_summary(self):
        for i in range(20):
            self.send(f"问候 {i}")
        count = len(self.state()["messages"])
        with self.store.transaction(self.sid) as data:
            data["last_acked_seq"] = self.store.last_seq(data)
            self.store.compact_acknowledged(data)
        self.assertEqual(len(self.state()["messages"]), count)

    def test_archive_revokes_pending_save_even_after_restore(self):
        self.decision = intent("material", scope="organize")
        self.send("RAG 整理资料")
        self.assertIsNotNone(self.state()["pending"])
        self.harness.session_action(self.sid, str(uuid.uuid4()), "archive", 1)
        self.harness.session_action(self.sid, str(uuid.uuid4()), "restore", 2)
        self.assertIsNone(self.state()["pending"])
        self.assertTrue(self.state()["draft"]["invalidated"])

    def test_missing_checkpoint_cannot_silently_create_fresh_session(self):
        from agent_service.schemas import SessionMessageRequest
        with self.assertRaisesRegex(ValueError, "CHECKPOINT_REQUIRED"):
            self.harness.accept(self.sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="继续", expected_event_seq=50))
        self.assertIsNone(self.state())

    def test_session_lifecycle_rejects_old_client_even_after_restore(self):
        from agent_service.schemas import SessionMessageRequest
        self.send()
        self.harness.session_action(self.sid, str(uuid.uuid4()), "archive", 1)
        self.harness.session_action(self.sid, str(uuid.uuid4()), "restore", 2)
        with self.assertRaisesRegex(ValueError, "VERSION_CONFLICT"):
            self.harness.accept(self.sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="旧请求", lifecycle_revision=0))
