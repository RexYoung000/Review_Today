import json
import threading
import time
import uuid
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from tests import test_conversation_v2 as fixture
from tests.test_conversation_v2 import intent
from agent_service.schemas import TeachingPreparation, SourceList, EvidenceAssessmentV2, MemoryChoice, MemoryResultsRequest, IntentDecision
from agent_service.openai_client import ModelCallError, schema_diagnostic
from agent_service.conversation_store import Superseded, ConversationStore
from agent_service.conversation import ConversationHarness


class ConditionalTeachingTests(unittest.TestCase):
    setUp = fixture.ConversationTests.setUp
    tearDown = fixture.ConversationTests.tearDown
    send = fixture.ConversationTests.send
    state = fixture.ConversationTests.state
    control = fixture.ConversationTests.control

    def model(self, system, user, schema, **kw):
        if schema is TeachingPreparation:
            return TeachingPreparation(concepts=["RAG", "检索"], public_query="RAG 检索增强生成", new_knowledge="追问" not in user)
        if schema is SourceList:
            return SourceList(candidates=[dict(url="https://example.com/rag", title="RAG 原文")])
        if schema is EvidenceAssessmentV2:
            return EvidenceAssessmentV2(state="supported", summary="支持基础原理", sources=["https://example.com/rag"])
        if schema is MemoryChoice:
            return MemoryChoice(selections=[])
        return fixture.ConversationTests.model(self, system, user, schema, **kw)

    def test_original_three_turns_search_read_once_single_source_and_reuse(self):
        with patch("agent_service.conversation.web_search_text", return_value="RAG 原文 https://example.com/rag") as search, patch("agent_service.conditional_teaching.fetch_public_url", return_value=("RAG 原文", "先检索相关片段，再生成回答")) as fetch:
            self.decision = intent("goal", workflow="topic_exploration", scope="learning")
            self.send("我想弄懂一个概念：RAG")
            search.assert_not_called()
            self.decision = intent("answer", workflow="topic_exploration", scope="continue_goal")
            second = self.send("面试想学到")
            self.decision = intent("continue", workflow="source_learning", scope="continue_goal", direct_teaching=True)
            third = self.send("直接教我")
        self.assertEqual(search.call_count, 1)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(self.state()["runs"][second.run_id]["search_state"], "verified")
        self.assertEqual(self.state()["runs"][third.run_id]["status"], "completed")
        self.assertIsNone(self.state()["pending"])
        self.assertNotIn("互补来源", str(self.state()["messages"]))
        self.assertFalse(any(e["stage"] == "memory_lookup" for e in self.state()["events"]))

    def test_preparation_keeps_subject_separate_from_learning_purpose(self):
        base = self.model
        preparations = []
        def capture(system, prompt, schema, **kw):
            if schema is TeachingPreparation:
                preparations.append(json.loads(prompt))
            return base(system, prompt, schema, **kw)
        self.decision = intent("goal", workflow="topic_exploration", scope="learning")
        self.send("我想弄懂一个概念：RAG")
        self.decision = intent("answer", workflow="topic_exploration", scope="continue_goal")
        with patch("agent_service.conversation.parse_model", side_effect=capture), patch("agent_service.conversation.web_search_text", side_effect=ModelCallError("UNSUPPORTED")):
            self.send("面试想学到")
        self.assertIn("RAG", preparations[0]["topic"])
        self.assertEqual(preparations[0]["learning_purpose"], "面试想学到")

    def test_preparation_failure_reuses_safe_intent_query(self):
        base = self.model
        def fail_preparation(system, prompt, schema, **kw):
            if schema is TeachingPreparation: raise ModelCallError("SCHEMA", "json_invalid")
            return base(system, prompt, schema, **kw)
        self.decision = intent("question", public_search_query="RAG")
        with patch("agent_service.conversation.parse_model", side_effect=fail_preparation), patch("agent_service.conversation.web_search_text", return_value="https://example.com/rag") as search, patch("agent_service.conditional_teaching.fetch_public_url", return_value=("RAG", "检索再生成")):
            accepted = self.send("我的私人资料怎么理解")
        self.assertEqual(search.call_args.args[0], "RAG")
        self.assertEqual(self.state()["runs"][accepted.run_id]["search_state"], "verified")
        self.assertEqual(self.state()["runs"][accepted.run_id]["status"], "completed")

    def test_search_failure_is_bounded_and_stable_teaching_continues(self):
        self.decision = intent("question", needs_verification=True)
        with patch("agent_service.conversation.web_search_text", side_effect=ModelCallError("CONNECTION")) as search:
            accepted = self.send("RAG 是什么")
        self.assertEqual(search.call_count, 2)
        run = self.state()["runs"][accepted.run_id]
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["search_state"], "failed")
        self.assertEqual(run["teaching_evidence"]["state"], "insufficient")

    def test_uncertain_empty_question_cannot_execute_save(self):
        self.decision = intent("goal").model_copy(update={"relation": "uncertain"})
        with patch("agent_service.conversation.web_search_text") as search:
            self.send("这个吧")
        self.assertEqual(self.state()["tasks"], {})
        search.assert_not_called()
        self.assertIn("希望", self.state()["messages"][-1]["content"])

    def test_schema_diagnostic_hides_invalid_literal_and_repairs_once(self):
        raw = intent("goal").model_dump(); raw["intents"] = ["PRIVATE_SECRET"]
        try:
            IntentDecision.model_validate(raw)
        except ValidationError as error:
            diagnostic = schema_diagnostic(error)
        self.assertNotIn("PRIVATE_SECRET", diagnostic)
        self.assertIn('"intents", 0', diagnostic)
        calls = []
        def invalid(system, prompt, schema, **kw):
            calls.append(prompt)
            if len(calls) == 1: raise ModelCallError("SCHEMA", diagnostic)
            return intent("greeting", light_reply="你好")
        with patch("agent_service.conversation.parse_model", side_effect=invalid):
            accepted = self.send()
        self.assertEqual(len(calls), 2)
        self.assertIn("literal_error", calls[-1])
        self.assertEqual(self.state()["runs"][accepted.run_id]["status"], "completed")
        attempts = [e["attempt"] for e in self.state()["events"] if e["stage"] == "model_attempt"]
        self.assertEqual(attempts, [1, 2])

    def test_lookup_roundtrip_empty_result_idempotent_and_stale_rejected(self):
        self.decision = intent("question")
        from agent_service.schemas import SessionMessageRequest
        body = SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="RAG", context={"memory_lookup_available": True})
        accepted = self.harness.accept(self.sid, body)
        with patch("agent_service.conversation.web_search_text", side_effect=ModelCallError("UNSUPPORTED")):
            worker = threading.Thread(target=self.harness.drain, args=(self.sid,))
            worker.start()
            deadline = time.monotonic() + 3
            request = None
            while time.monotonic() < deadline:
                request = self.state()["runs"][accepted.run_id].get("memory_lookup")
                if request: break
                time.sleep(.01)
            self.assertIsNotNone(request)
            response = MemoryResultsRequest(request_id=request["request_id"], revision=1, lifecycle_revision=0, candidates=[])
            self.harness.memory_results(accepted.run_id, response)
            self.harness.memory_results(accepted.run_id, response)
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.harness.session_action(self.sid, str(uuid.uuid4()), "archive", 1)
        with self.assertRaisesRegex(ValueError, "STALE"):
            self.harness.memory_results(accepted.run_id, response)

    def test_delete_is_durable_and_old_snapshots_accept_and_legacy_cannot_revive(self):
        self.decision = intent("greeting", light_reply="你好")
        accepted = self.send()
        snapshot = self.harness.export_snapshot(self.sid)
        self.harness.session_action(self.sid, str(uuid.uuid4()), "archive", 1)
        result = self.harness.session_action(self.sid, str(uuid.uuid4()), "delete", 2)
        self.assertEqual(result["status"], "deleted")
        self.assertEqual(self.harness.session_action(self.sid, str(uuid.uuid4()), "delete", 2), result)
        self.assertIsNone(self.state())
        fresh = ConversationHarness(ConversationStore(self.tasks))
        with self.assertRaisesRegex(ValueError, "DELETED"): fresh.restore_snapshot(self.sid, snapshot)
        with self.assertRaisesRegex(ValueError, "DELETED"): self.send()
        with self.assertRaises(Superseded):
            with self.store.transaction(self.sid, accepted.run_id, 1): pass
        self.assertEqual(self.tasks.list_for_session(self.sid) if hasattr(self.tasks, 'list_for_session') else [], [])

    def test_conflicting_sources_remain_unverified(self):
        base = self.model
        def conflicting(system, prompt, schema, **kw):
            if schema is EvidenceAssessmentV2:
                return EvidenceAssessmentV2(state="conflicting", summary="两种定义的范围不同", sources=["https://example.com/rag"])
            return base(system, prompt, schema, **kw)
        self.decision = intent("question")
        with patch("agent_service.conversation.parse_model", side_effect=conflicting), patch("agent_service.conversation.web_search_text", return_value="https://example.com/rag"), patch("agent_service.conditional_teaching.fetch_public_url", return_value=("资料", "范围差异")):
            accepted = self.send("RAG 是什么")
        self.assertEqual(self.state()["runs"][accepted.run_id]["search_state"], "conflicting")
        self.assertIn("范围", self.state()["messages"][-1]["content"])

    def test_optional_lookup_times_out_without_blocking_lesson_and_rejects_late_result(self):
        from agent_service.schemas import SessionMessageRequest
        self.decision = intent("question")
        accepted = self.harness.accept(self.sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="RAG", context={"memory_lookup_available": True}))
        with patch("agent_service.conditional_teaching.MEMORY_LOOKUP_TIMEOUT", .02), patch("agent_service.conversation.web_search_text", side_effect=ModelCallError("UNSUPPORTED")):
            self.harness.drain(self.sid)
        run = self.state()["runs"][accepted.run_id]
        self.assertEqual(run["status"], "completed")
        request = run["memory_lookup"]
        self.assertEqual(request["state"], "timed_out")
        with self.assertRaisesRegex(ValueError, "STALE"):
            self.harness.memory_results(accepted.run_id, MemoryResultsRequest(request_id=request["request_id"], revision=1, lifecycle_revision=0))

    def test_active_session_cannot_be_deleted(self):
        self.decision = intent("greeting", light_reply="你好")
        self.send()
        with self.assertRaisesRegex(ValueError, "NOT_ARCHIVED"):
            self.harness.session_action(self.sid, str(uuid.uuid4()), "delete", 1)
        self.assertIsNotNone(self.state())

    def test_direct_teaching_control_never_grades_an_unanswered_question(self):
        from agent_service.schemas import MasteryEvaluation
        self.decision = intent("goal", workflow="source_learning", scope="learning", direct_teaching=True)
        with patch("agent_service.conversation.web_search_text", side_effect=ModelCallError("UNSUPPORTED")):
            self.send("直接教我 RAG")
            self.calls.clear()
            # Even a model that would mistake this for option B must not grade it.
            self.decision = intent("answer", scope="continue_goal")
            accepted = self.send("直接教我！")
        run = self.state()["runs"][accepted.run_id]
        self.assertEqual(run["status"], "completed")
        self.assertTrue(run["intent"]["direct_teaching"])
        self.assertFalse(any(schema in {IntentDecision, MasteryEvaluation} for schema, _ in self.calls))

    def test_answer_must_quote_current_input_before_grading(self):
        self.decision = intent("goal", workflow="source_learning", scope="learning", direct_teaching=True)
        with patch("agent_service.conversation.web_search_text", side_effect=ModelCallError("UNSUPPORTED")):
            self.send("直接教我 RAG")
        base = self.model
        prompts = []
        def fabricated_answer(system, prompt, schema, **kw):
            if schema is IntentDecision:
                prompts.append(prompt)
                if len(prompts) == 1:
                    return intent("answer", scope="continue_goal").model_copy(update={"answer_evidence": "B"})
                return intent("followup", scope="continue_goal")
            return base(system, prompt, schema, **kw)
        with patch("agent_service.conversation.parse_model", side_effect=fabricated_answer), patch("agent_service.conversation.web_search_text", side_effect=ModelCallError("UNSUPPORTED")):
            accepted = self.send("我还想听一个例子")
        self.assertEqual(len(prompts), 2)
        self.assertIn("answer_evidence", prompts[-1])
        self.assertEqual(self.state()["runs"][accepted.run_id]["intent"]["intents"], ["followup"])
        self.assertEqual(self.state()["runs"][accepted.run_id]["status"], "completed")

    def test_missing_query_uses_public_concept_and_reports_no_results_truthfully(self):
        base = self.model
        def missing_query(system, prompt, schema, **kw):
            if schema is TeachingPreparation:
                return TeachingPreparation(concepts=["RAG"], public_query="")
            if schema is SourceList:
                return SourceList(candidates=[])
            return base(system, prompt, schema, **kw)
        self.decision = intent("question")
        with patch("agent_service.conversation.parse_model", side_effect=missing_query), patch("agent_service.conversation.web_search_text", return_value="无合适结果") as search:
            accepted = self.send("我的私人草稿里的这个技术概念怎么解释")
        self.assertEqual(search.call_args.args[0], "RAG")
        self.assertEqual(self.state()["runs"][accepted.run_id]["search_state"], "no_results")

    def test_exhausted_schema_repair_stays_retryable_with_diagnostic(self):
        with patch("agent_service.conversation.parse_model", side_effect=ModelCallError("SCHEMA", "field=intents; literal_error")) as model:
            accepted = self.send()
        self.assertEqual(model.call_count, 2)
        self.assertEqual(self.state()["runs"][accepted.run_id]["status"], "retryable_failed")
        self.assertTrue(any("intents" in e["detail_summary"] for e in self.state()["events"]))
