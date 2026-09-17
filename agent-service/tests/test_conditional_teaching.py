import json
import threading
import time
import uuid
import unittest
from unittest.mock import patch, ANY
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
            self.decision = intent("answer", workflow="topic_exploration", scope="continue_goal", needs_verification=True)
            second = self.send("面试想学到，请核验出处")
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

    def test_structured_search_requires_exact_returned_url_not_prefix_or_title(self):
        self.decision = intent("question", needs_verification=True)
        search_data = json.dumps(dict(protocol="harness_web_tools_v1", results=[
            dict(url="https://example.com/rag/other", title="https://example.com/rag")]))
        with patch("agent_service.conversation.web_search_text", return_value=search_data), patch("agent_service.conditional_teaching.fetch_public_url") as fetch:
            accepted = self.send("RAG 是什么")
        fetch.assert_not_called()
        self.assertEqual(self.state()["runs"][accepted.run_id]["search_state"], "no_results")

    def test_preparation_failure_reuses_safe_intent_query(self):
        base = self.model
        def fail_preparation(system, prompt, schema, **kw):
            if schema is TeachingPreparation: raise ModelCallError("SCHEMA", "json_invalid")
            return base(system, prompt, schema, **kw)
        self.decision = intent("question", needs_verification=True, public_search_query="RAG")
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

    def test_failed_preparation_without_safe_query_does_not_claim_reuse_or_verification(self):
        base = self.model
        def fail_preparation(system, prompt, schema, **kw):
            if schema is TeachingPreparation: raise ModelCallError("SCHEMA", "json_invalid")
            return base(system, prompt, schema, **kw)
        self.decision = intent("question", needs_verification=True, public_search_query="")
        with patch("agent_service.conversation.parse_model", side_effect=fail_preparation), patch("agent_service.conversation.web_search_text") as search:
            accepted = self.send("解释一下我的私人资料")
        search.assert_not_called()
        run = self.state()["runs"][accepted.run_id]
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["search_state"], "not_called")
        self.assertIn("尚未进行网页核验", self.state()["messages"][-1]["content"])

    def test_failed_search_followup_has_no_repeated_notice_but_refresh_and_new_topic_do(self):
        self.decision = intent("question", needs_verification=True, public_search_query="RAG")
        with patch("agent_service.conversation.web_search_text", side_effect=ModelCallError("CONNECTION")) as search:
            first = self.send("RAG 是什么")
            self.assertIn("> [!NOTE]", self.state()["messages"][-1]["content"])
            self.decision = intent("followup", public_search_query="RAG")
            followup = self.send("追问，能举例吗")
            self.assertEqual(search.call_count, 2)
            run = self.state()["runs"][followup.run_id]
            self.assertEqual(run["search_state"], "not_called")
            self.assertEqual(run["teaching_evidence"]["state"], "insufficient")
            self.assertNotIn("> [!NOTE]", self.state()["messages"][-1]["content"])
            self.decision = intent("followup", public_search_query="RAG", refresh_sources=True)
            refreshed = self.send("追问，请重新查证")
            self.assertEqual(self.state()["runs"][refreshed.run_id]["search_state"], "failed")
            self.assertIn("> [!NOTE]", self.state()["messages"][-1]["content"])
            self.decision = intent("question", needs_verification=True)
            current = self.send("追问，现在的最新信息是什么")
            self.assertEqual(self.state()["runs"][current.run_id]["search_state"], "failed")
            self.assertIn("> [!NOTE]", self.state()["messages"][-1]["content"])

    def test_unavailable_service_has_own_state_and_never_calls_provider(self):
        self.decision = intent("question", needs_verification=True, public_search_query="RAG")
        with patch("agent_service.conversation.web_search_capability", return_value={"status": "unavailable"}), patch("agent_service.conversation.web_search_text") as search:
            result = self.send("RAG 是什么")
        search.assert_not_called()
        state = self.state()
        self.assertEqual(state["runs"][result.run_id]["search_state"], "unavailable")
        self.assertIn("网页检索服务不可用", state["messages"][-1]["content"])
        self.assertFalse(any(e["node"] == "search_attempt" for e in state["events"]))

    def test_new_topic_and_its_followup_do_not_reuse_previous_topic_sources(self):
        self.decision = intent('question', needs_verification=True, public_search_query='RAG')
        with patch('agent_service.conversation.web_search_text', return_value='https://example.com/rag'), patch('agent_service.conditional_teaching.fetch_public_url', return_value=('RAG', '检索再生成')):
            self.send('RAG 是什么')
        self.assertTrue(self.state()['teaching_context']['sources'])
        base = self.model
        def no_new_sources(system, user, schema, **kwargs):
            if schema is TeachingPreparation:
                return TeachingPreparation(concepts=[], public_query='', new_knowledge=False)
            return base(system, user, schema, **kwargs)
        with patch('agent_service.conversation.parse_model', side_effect=no_new_sources):
            for relation, content in [('new_topic','和弦是什么'), ('continuation','给刚才的和弦举个例子')]:
                self.decision = intent('question').model_copy(update={'relation':relation})
                result = self.send(content)
                self.assertFalse(self.state()['runs'][result.run_id]['teaching_sources'])
                self.assertNotIn('https://example.com/rag', self.state()['messages'][-1]['content'])

    def test_example_stays_plain_answer_and_keeps_same_session_evidence(self):
        self.decision = intent("question", needs_verification=True, public_search_query="RAG")
        with patch("agent_service.conversation.web_search_text", side_effect=ModelCallError("UNSUPPORTED")) as search:
            self.send("RAG 是什么")
            self.assertFalse(self.state()["tasks"])
            self.decision = intent("example", scope="learning", workflow="source_learning", public_search_query="RAG")
            result = self.send("追问，举例解释刚才的 RAG")
            self.assertEqual(search.call_count, 1)
        state = self.state()
        self.assertFalse(state["tasks"])
        self.assertEqual(state["runs"][result.run_id]["search_state"], "not_called")
        self.assertNotIn("[!NOTE]", state["messages"][-1]["content"])
        self.assertEqual(state["teaching_context"]["evidence"]["state"], "insufficient")

    def test_source_assessment_unsupported_is_failure_not_search_unavailable(self):
        base = self.model
        def fail_assessment(system, prompt, schema, **kw):
            if schema is EvidenceAssessmentV2: raise ModelCallError("UNSUPPORTED")
            return base(system, prompt, schema, **kw)
        self.decision = intent("question", needs_verification=True, public_search_query="RAG")
        with patch("agent_service.conversation.parse_model", side_effect=fail_assessment), patch("agent_service.conversation.web_search_text", return_value="https://example.com/rag"), patch("agent_service.conditional_teaching.fetch_public_url", return_value=("RAG", "检索再生成")):
            result = self.send("RAG 是什么")
        self.assertEqual(self.state()["runs"][result.run_id]["search_state"], "failed")

    def test_search_success_with_blocked_read_is_insufficient_not_empty_search(self):
        self.decision = intent("question", needs_verification=True, public_search_query="RAG")
        prompts = []
        base = self.model
        def inspect(system, prompt, schema, **kwargs):
            prompts.append(prompt)
            return base(system, prompt, schema, **kwargs)
        with patch("agent_service.conversation.parse_model", side_effect=inspect), patch("agent_service.conversation.web_search_text", return_value="https://example.com/rag"), patch("agent_service.conditional_teaching.fetch_public_url", side_effect=ValueError("RT.CAPTURE.SSRF")):
            result = self.send("RAG 是什么")
        state = self.state(); run = state["runs"][result.run_id]
        self.assertEqual(run["search_state"], "insufficient")
        self.assertEqual(run["teaching_evidence"]["sources"], [])
        self.assertIn("网页未能读取", run["verification_notice"])
        self.assertTrue(any("本轮实际已读网页 URL：[]" in p for p in prompts))
        self.assertTrue(any(e.get("detail_summary") == "public_address_required" for e in state["events"]))

    def test_unread_links_are_filtered_in_both_stream_and_final_answer(self):
        from agent_service.schemas import ConversationOutput
        base = self.model
        invented = "说明。\n\n[官方文档](https://unread.example/doc)"
        def streamed(system, prompt, schema, **kwargs):
            if schema is ConversationOutput:
                for end in range(1, len(invented) + 1):
                    kwargs['on_partial']({'message': invented[:end]})
                return ConversationOutput(message=invented)
            return base(system, prompt, schema, **kwargs)
        self.decision = intent("question", needs_verification=True, public_search_query="RAG")
        with patch("agent_service.conversation.parse_model", side_effect=streamed), patch("agent_service.conversation.web_search_text", return_value="https://example.com/rag"), patch("agent_service.conditional_teaching.fetch_public_url", side_effect=ValueError("RT.CAPTURE.SSRF")):
            result = self.send("RAG 是什么")
        state = self.state()
        final = state['messages'][-1]['content']
        self.assertIn('官方文档（链接未核验）', final)
        self.assertNotIn('https://unread', final)
        for event in state['events']:
            if event['node'].startswith('response.'):
                self.assertNotIn('https://unread', json.dumps(event))

    def test_independent_results_flow_through_fetch_assessment_and_citation(self):
        from agent_service.web_tools import SearchResult
        from unittest.mock import Mock
        self.decision = intent("question", needs_verification=True, public_search_query="RAG")
        backend = Mock(name="backend")
        backend.name = "test"
        backend.search.return_value = [SearchResult("https://example.com/rag", "RAG 原文")]
        with patch("agent_service.web_tools._backend", return_value=backend), patch("agent_service.conditional_teaching.fetch_public_url", return_value=("RAG 原文", "先检索相关片段，再生成回答")) as fetch:
            result = self.send("RAG 是什么")
        state = self.state(); run = state["runs"][result.run_id]
        self.assertEqual(run["search_state"], "verified")
        fetch.assert_called_once_with("https://example.com/rag", on_cancel_handle=ANY)
        self.assertIn("https://example.com/rag", state["messages"][-1]["content"])
        self.assertNotIn("model", backend.search.call_args.kwargs)

    def test_direct_search_extract_assessment_and_citation(self):
        import os
        import httpx
        from agent_service import tavily_tools
        self.decision = intent("question", needs_verification=True, public_search_query="RAG")
        requests = []
        def transport(request):
            requests.append(request)
            if request.url.path == "/search":
                return httpx.Response(200, json={"results": [{"url": "https://example.com/rag", "title": "RAG 原文", "content": "摘要"}]})
            self.assertEqual(request.url.path, "/extract")
            return httpx.Response(200, json={"results": [{"url": "https://example.com/rag", "raw_content": "先检索相关片段，再生成回答"}]})
        with patch.dict(os.environ, {"REVIEW_TODAY_SEARCH_PROVIDER": "tavily", "REVIEW_TODAY_READ_PROVIDER": "tavily", "TAVILY_API_KEY": "WEB_TEST"}), patch.object(tavily_tools, "_client", side_effect=lambda: httpx.Client(transport=httpx.MockTransport(transport))):
            accepted = self.send("RAG 是什么")
        data = self.state()
        self.assertEqual(data["runs"][accepted.run_id]["search_state"], "verified")
        self.assertEqual([str(r.url) for r in requests], ["https://api.tavily.com/search", "https://api.tavily.com/extract"])
        self.assertTrue(all('model' not in json.loads(r.content) for r in requests))
        self.assertIn("https://example.com/rag", data["messages"][-1]["content"])

    def test_search_quota_error_is_not_retried_or_presented_as_verified(self):
        from agent_service.call_errors import WebToolError
        self.decision = intent("question", needs_verification=True, public_search_query="RAG")
        with patch("agent_service.conversation.web_search_text", side_effect=WebToolError("RATE_LIMIT")) as search:
            accepted = self.send("RAG 是什么")
        run = self.state()["runs"][accepted.run_id]
        self.assertEqual(search.call_count, 1)
        self.assertEqual(run["search_state"], "failed")
        self.assertIn("使用限额", run["teaching_evidence"]["summary"])
        self.assertEqual(run["teaching_evidence"]["sources"], [])

    def test_official_domains_exclude_mirrors_despite_misleading_titles(self):
        self.decision = intent("question", needs_verification=True, public_search_query="Python official documentation")
        base = self.model
        def models(system, prompt, schema, **kw):
            if schema is TeachingPreparation:
                return TeachingPreparation(concepts=["Python"], public_query="Python list", official_sources_required=True, source_domains=["python.org"])
            if schema is SourceList:
                return SourceList(candidates=[dict(url="https://pythonlang.cn/docs", title="Python.org official"),
                    dict(url="https://docs.python.org/3/", title="Python"),
                    dict(url="https://python.org.evil.com/a", title="Python.org")])
            if schema is EvidenceAssessmentV2:
                self.assertIn("抓取时间", system)
                self.assertEqual(json.loads(prompt)["allowed_domains"], ["python.org"])
                return EvidenceAssessmentV2(state="supported", summary="官方基础内容", sources=["https://docs.python.org/3/"])
            return base(system,prompt,schema,**kw)
        results = json.dumps(dict(protocol="harness_web_tools_v1", results=[dict(url=u) for u in ["https://pythonlang.cn/docs","https://docs.python.org/3/","https://python.org.evil.com/a"]]))
        with patch("agent_service.conversation.parse_model", side_effect=models), patch("agent_service.conversation.web_search_text", return_value=results) as search, patch("agent_service.conditional_teaching.fetch_public_url", return_value=("Python", "正文")) as read:
            accepted = self.send("请查阅 Python 官方文档")
        self.assertIn("site:python.org", search.call_args.args[0])
        read.assert_called_once_with("https://docs.python.org/3/", on_cancel_handle=ANY)
        self.assertEqual(self.state()["runs"][accepted.run_id]["teaching_evidence"]["sources"], ["https://docs.python.org/3/"])

    def test_unknown_official_domain_cannot_be_inferred_from_search_titles(self):
        self.decision = intent("question", needs_verification=True, public_search_query="unknown official release")
        base = self.model
        def models(system, prompt, schema, **kw):
            if schema is TeachingPreparation:
                return TeachingPreparation(concepts=["产品"], public_query="product", official_sources_required=True)
            return base(system, prompt, schema, **kw)
        with patch("agent_service.conversation.parse_model", side_effect=models), patch("agent_service.conversation.web_search_text") as search:
            accepted = self.send("请核对这个产品的官网资料")
        search.assert_not_called()
        run = self.state()["runs"][accepted.run_id]
        self.assertEqual(run["teaching_evidence"]["state"], "insufficient")
        self.assertIn("官方来源", run["teaching_evidence"]["summary"])

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
            calls.append((system, prompt))
            if len(calls) == 1: raise ModelCallError("SCHEMA", diagnostic)
            return intent("greeting", light_reply="你好")
        with patch("agent_service.conversation.parse_model", side_effect=invalid):
            accepted = self.send()
        self.assertEqual(len(calls), 2)
        self.assertIn("literal_error", calls[-1][0])
        self.assertEqual(calls[0][1], calls[1][1])
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
        self.decision = intent("question", needs_verification=True)
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
                prompts.append((system, prompt))
                if len(prompts) == 1:
                    return intent("answer", scope="continue_goal").model_copy(update={"answer_evidence": "B"})
                return intent("followup", scope="continue_goal")
            return base(system, prompt, schema, **kw)
        with patch("agent_service.conversation.parse_model", side_effect=fabricated_answer), patch("agent_service.conversation.web_search_text", side_effect=ModelCallError("UNSUPPORTED")):
            accepted = self.send("我还想听一个例子")
        self.assertEqual(len(prompts), 2)
        self.assertIn("answer_evidence", prompts[-1][0])
        self.assertEqual(prompts[0][1], prompts[-1][1])
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
        self.decision = intent("question", needs_verification=True)
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

    def test_failover_success_records_actual_provider_without_failure_notice(self):
        import os
        from unittest.mock import Mock
        from agent_service import web_resilience
        from agent_service.web_tools import SearchResult
        from agent_service.call_errors import WebToolError
        backends={name:Mock() for name in ['exa','tavily']}
        backends['exa'].search.side_effect=WebToolError('RATE_LIMIT')
        backends['tavily'].search.return_value=[SearchResult('https://example.com/rag','RAG')]
        backends['tavily'].read.return_value=('RAG','先检索再生成')
        self.decision=intent('question',needs_verification=True,public_search_query='RAG')
        with patch.dict(os.environ,{'REVIEW_TODAY_SEARCH_PROVIDER':'exa','REVIEW_TODAY_SEARCH_FALLBACKS':'tavily','REVIEW_TODAY_READ_PROVIDER':'exa','REVIEW_TODAY_READ_FALLBACKS':'tavily'}), patch.object(web_resilience,'_states',{}), patch('agent_service.web_tools._backend',side_effect=lambda name:backends[name]):
            result=self.send('RAG 是什么')
        state=self.state();run=state['runs'][result.run_id]
        self.assertEqual(run['search_state'],'verified')
        self.assertEqual(run['verification_notice'],'')
        self.assertEqual(run['teaching_sources'][0]['content_kind'],'page_text')
        events=[e for e in state['events'] if e['node']=='web_provider']
        self.assertTrue(any(e['payload']['provider']=='tavily' and e['payload']['operation']=='read' and e['payload']['status']=='succeeded' for e in events))
        public=next(e for e in state['events'] if e['node']=='public_search')
        self.assertEqual(public['payload']['web_provider'],'tavily')

    def test_brave_chunks_recovery_never_becomes_full_page_evidence(self):
        self.decision=intent('question',needs_verification=True,public_search_query='RAG')
        from agent_service.call_errors import WebToolError
        chunks=[dict(url='https://example.com/rag',title='RAG',content='相关正文片段',provider='brave',content_kind='extracted_chunks')]
        with patch('agent_service.conversation.web_search_text',return_value='https://example.com/rag'), patch('agent_service.conditional_teaching.fetch_public_url',side_effect=WebToolError('CHAIN_FAILED')), patch('agent_service.web_tools.web_context_pages',return_value=chunks) as recovery:
            result=self.send('RAG 是什么')
        run=self.state()['runs'][result.run_id]
        recovery.assert_called_once()
        self.assertEqual(run['teaching_evidence']['state'],'scoped')
        self.assertIn('未读取指定网页全文',run['teaching_evidence']['summary'])
        self.assertEqual(run['teaching_sources'][0]['content_kind'],'extracted_chunks')
        self.assertNotIn('https://example.com/rag',run.get('source_cache',{}))
