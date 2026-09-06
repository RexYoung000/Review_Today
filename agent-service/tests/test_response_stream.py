"""Streaming previews never become authority or committed answers by themselves."""
import json
import threading
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from agent_service.conversation_store import Superseded
from agent_service.openai_client import ModelCallError, parse_model
from agent_service.response_projection import public_preview
from agent_service.schemas import ConversationOutput, IntentDecision
import tests.test_conversation_v2 as fixtures
import agent_service.main as main


class StreamingHarnessTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ConversationTests()
        self.f.setUp()
        self.f.decision = fixtures.intent("question")
        self.h = self.f.harness

    def tearDown(self):
        self.f.tearDown()

    def streaming_model(self, system, user, schema, **kw):
        result = self.f.model(system, user, schema, **kw)
        if schema is ConversationOutput:
            kw["on_partial"]({"message": "这是"})
            self.assertFalse([m for m in self.f.state()["messages"] if m["role"] == "coach"])
            self.assertIsNone(self.f.state()["pending"])
            kw["on_partial"]({"message": result.message})
        return result

    def test_preview_and_final_use_one_stable_id_and_ordered_fragments(self):
        with patch("agent_service.conversation.parse_model", side_effect=self.streaming_model):
            accepted = self.f.send("RAG 是什么")
        data = self.f.state()
        chunks = [e["payload"]["response"] for e in data["events"] if "response" in e["payload"]]
        self.assertGreaterEqual(len(chunks), 4)
        self.assertEqual([c["chunk_seq"] for c in chunks], list(range(len(chunks))))
        self.assertEqual(len({c["response_id"] for c in chunks}), 1)
        final = [m for m in data["messages"] if m["role"] == "coach"]
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]["message_id"], chunks[0]["response_id"])
        self.assertEqual(final[0]["content"], chunks[-1]["text"])
        self.assertEqual(chunks[-1]["status"], "complete")
        self.assertIsNotNone(data["runs"][accepted.run_id]["first_text_ms"])
        self.assertIsNone(data["runs"][accepted.run_id]["started_at"])
        self.assertNotIn("active_response", data["runs"][accepted.run_id])
        with self.f.store.transaction(self.f.sid) as stored:
            stored["last_acked_seq"] = self.f.store.last_seq(stored)
            self.f.store.compact_acknowledged(stored)
        acked = self.f.state()
        for event in acked["events"]:
            if event["stage"] == "response.delta":
                self.assertEqual(event["payload"]["response"]["text"], "")
        self.assertEqual([m["content"] for m in acked["messages"] if m["role"] == "coach"], ["这是本轮真实回答。\n\n你可以继续追问、尝试回答，或说“先跳过检查”；跳过不会标记为已掌握。"])

    def test_stop_fences_late_chunks_and_preserves_incomplete_history(self):
        accepted = self.f.send("RAG 是什么", drain=False)

        def model(system, user, schema, **kw):
            if schema is not ConversationOutput: return self.f.model(system, user, schema, **kw)
            kw["on_partial"]({"message": "先检索"})
            before = time.monotonic()
            self.f.control(accepted.run_id, "stop")
            self.assertLess(time.monotonic() - before, .1)
            kw["on_partial"]({"message": "迟到的内容不应发布"})
            self.fail("superseded generation must abort")

        with patch("agent_service.conversation.parse_model", side_effect=model):
            self.h.drain(self.f.sid)
        data = self.f.state()
        self.assertFalse([m for m in data["messages"] if m["role"] == "coach"])
        response = data["runs"][accepted.run_id]["active_response"]
        self.assertEqual(response["text"], "先检索")
        self.assertEqual(response["status"], "interrupted")
        self.assertTrue(data["paused"])

    def test_steer_closes_obsolete_transport_and_continues_same_run(self):
        entered = threading.Event()
        closed = threading.Event()
        answer_calls = 0

        def model(system, user, schema, **kw):
            nonlocal answer_calls
            if schema is not ConversationOutput: return self.f.model(system, user, schema, **kw)
            answer_calls += 1
            if answer_calls == 1:
                kw["on_cancel_handle"](closed.set)
                entered.set()
                self.assertTrue(closed.wait(1), "steering must close the obsolete request")
                return ConversationOutput(message="obsolete")
            return ConversationOutput(message="adjusted")

        with patch("agent_service.conversation.parse_model", side_effect=model):
            accepted = self.f.send("原问题", drain=False)
            worker = threading.Thread(target=self.h.drain, args=(self.f.sid,))
            worker.start()
            self.assertTrue(entered.wait(1))
            start = time.monotonic()
            self.f.send("补充条件", drain=False)
            self.assertLess(time.monotonic() - start, .1)
            worker.join(2)
        self.assertFalse(worker.is_alive())
        replies = [message["content"] for message in self.f.state()["messages"] if message["role"] == "coach"]
        self.assertEqual(replies, ["adjusted\n\n你可以继续追问、尝试回答，或说“先跳过检查”；跳过不会标记为已掌握。"])
        self.assertEqual(self.f.state()["runs"][accepted.run_id]["status"], "completed")

    def test_failure_then_retry_reuses_validated_intent_not_partial_answer(self):
        def failing(system, user, schema, **kw):
            if schema is not ConversationOutput: return self.f.model(system, user, schema, **kw)
            kw["on_partial"]({"message": "未完成预览"})
            raise ModelCallError("SCHEMA")
        with patch("agent_service.conversation.parse_model", side_effect=failing):
            accepted = self.f.send("RAG 是什么")
        data = self.f.state()
        self.assertEqual(data["runs"][accepted.run_id]["active_response"]["status"], "failed")
        self.assertFalse([m for m in data["messages"] if m["role"] == "coach"])
        self.f.control(accepted.run_id, "retry")
        self.f.calls.clear()
        with patch("agent_service.conversation.parse_model", side_effect=self.streaming_model):
            self.h.drain(self.f.sid)
        self.assertNotIn(IntentDecision, [schema for schema, _ in self.f.calls])
        self.assertEqual(len(self.f.state()["runs"][accepted.run_id]["attempt_durations"]), 2)

    def test_crash_recovery_preserves_preview_and_requires_explicit_resume(self):
        accepted = self.f.send("RAG 是什么", drain=False)
        with self.f.store.transaction(self.f.sid) as data:
            run = data["runs"][accepted.run_id]
            run.update(status="running", active_response=dict(response_id="stable", revision=1, chunk_seq=1, text="预览", status="streaming"))
        with patch.object(self.h, "start"):
            self.h.recover()
        run = self.f.state()["runs"][accepted.run_id]
        self.assertEqual(run["status"], "interrupted")
        self.assertEqual(run["active_response"]["text"], "预览")
        self.assertTrue(self.f.state()["paused"])

    def test_light_reply_in_all_modes_only_calls_router(self):
        for mode in fixtures.LABELS:
            self.f.sid = str(fixtures.uuid.uuid4())
            self.f.decision = fixtures.intent("thanks", light_reply="不客气，需要时继续问我。")
            self.f.calls.clear()
            self.f.send("谢谢", mode=mode)
            self.assertEqual([s for s, _ in self.f.calls], [IntentDecision])
            self.assertFalse(self.f.state()["tasks"])

    def test_defer_and_legacy_non_learning_self_report_never_call_coach(self):
        for name, reply in [("defer", "好的，你慢慢想。"),
                            ("self_report", "好的，你想好后直接告诉我即可。")]:
            with self.subTest(name=name):
                self.f.sid = str(fixtures.uuid.uuid4())
                self.f.decision = fixtures.intent(name, light_reply=reply)
                self.f.calls.clear()
                accepted = self.f.send("我思考一下")
                data = self.f.state()
                self.assertEqual([schema for schema, _ in self.f.calls], [IntentDecision])
                self.assertEqual([m["content"] for m in data["messages"] if m["role"] == "coach"], [reply])
                self.assertEqual(data["runs"][accepted.run_id]["status"], "completed")
                self.assertFalse(data["tasks"])
                self.assertIsNone(data["pending"])
                self.assertIsNone(data["draft"])

    def test_defer_without_model_reply_uses_safe_ack_and_preserves_active_task(self):
        self.f.decision = fixtures.intent("question", workflow="problem_solving", scope="learning")
        self.f.send("RAG 是什么", mode="problem_solving")
        before = self.f.state()["active_task_id"]
        before_task = dict(self.f.state()["tasks"][before])
        self.f.decision = fixtures.intent("defer")
        self.f.calls.clear()
        self.f.send("让我想一下", mode="problem_solving")
        data = self.f.state()
        self.assertEqual([schema for schema, _ in self.f.calls], [IntentDecision])
        self.assertEqual(data["active_task_id"], before)
        self.assertEqual(data["tasks"][before]["stage"], before_task["stage"])
        self.assertEqual(data["tasks"][before]["context"], before_task["context"])
        self.assertEqual([m["content"] for m in data["messages"] if m["role"] == "coach"][-1],
                         "好的，你慢慢想。准备好后继续。")

    def test_light_reply_never_bypasses_mixed_intents_or_pending_consent(self):
        for decision in [fixtures.intent("thanks", "confirm", light_reply="不客气"),
                         fixtures.intent("thanks", clarification="保存哪一项？", light_reply="不客气"),
                         fixtures.intent("greeting", needs_verification=True, light_reply="不客气"),
                         fixtures.intent("defer", "question", light_reply="好的")]:
            self.assertFalse(self.h._light_reply_allowed(decision, {}))
        self.f.decision = fixtures.intent("material", scope="organize")
        self.f.send("RAG 笔记")
        previous = self.f.state()["pending"]
        self.f.decision = fixtures.intent("thanks", light_reply="不客气。")
        self.f.send("谢谢")
        self.assertEqual(self.f.state()["pending"], previous)
        self.f.capture.assert_not_called()

    def test_sse_replays_same_event_page_and_validates_cursor(self):
        with patch("agent_service.conversation.parse_model", side_effect=self.streaming_model):
            self.f.send("RAG 是什么")
        with patch.object(main, "conversation_harness", self.h), patch.object(main, "start_probe"), patch.object(main, "resume_incomplete_tasks"), patch.object(self.h, "recover"), TestClient(main.app) as client:
            path = f"/v2/sessions/{self.f.sid}/events"
            response = client.get(path + "/stream?after_seq=1")
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers["content-type"])
            event = json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith("data: ")))
            self.assertEqual(event, client.get(path + "?after_seq=1").json())
            self.assertEqual(client.get(path + "/stream?after_seq=-1").status_code, 422)


class AdapterStreamingTests(unittest.TestCase):
    def test_compatible_whitespace_prelude_and_restart_before_content(self):
        client = MagicMock()
        stream = client.responses.create.return_value.__enter__.return_value
        stream.__iter__.return_value = iter([
            NS(type="response.output_text.delta", delta=" "),
            NS(type="response.created", response=NS(id="one")),
            NS(type="response.output_text.delta", delta="\n"),
            NS(type="response.created", response=NS(id="two")),
            NS(type="response.output_text.delta", delta='{"message":"真实正文"}'),
            NS(type="response.completed", response=NS(output=[], status="completed")),
        ])
        with patch("agent_service.openai_client._client", return_value=client):
            result = parse_model("s", "u", ConversationOutput, on_partial=lambda _: None)
        self.assertEqual(result.message, "真实正文")

    def test_response_replacement_after_output_is_protocol_failure(self):
        client = MagicMock()
        stream = client.responses.create.return_value.__enter__.return_value
        stream.__iter__.return_value = iter([
            NS(type="response.created", response=NS(id="one")),
            NS(type="response.output_text.delta", delta='{"message":"已经显示'),
            NS(type="response.created", response=NS(id="two")),
        ])
        with patch("agent_service.openai_client._client", return_value=client):
            with self.assertRaisesRegex(ModelCallError, "PROTOCOL"):
                parse_model("s", "u", ConversationOutput, on_partial=lambda _: None)
        client.responses.parse.assert_not_called()

    def test_disconnected_stream_without_completion_never_commits(self):
        client = MagicMock()
        stream = client.responses.create.return_value.__enter__.return_value
        stream.__iter__.return_value = iter([NS(type="response.output_text.delta", delta='{"message":"看似完整"}')])
        with patch("agent_service.openai_client._client", return_value=client):
            with self.assertRaisesRegex(ModelCallError, "INCOMPLETE"):
                parse_model("s", "u", ConversationOutput, on_partial=lambda _: None)
        client.responses.parse.assert_not_called()

    def test_partial_unicode_json_only_public_field_projection(self):
        client = MagicMock()
        response = ConversationOutput(message="中文😀 **未闭合", check_question="")
        raw = json.dumps(response.model_dump(), ensure_ascii=True)
        stream = client.responses.create.return_value.__enter__.return_value
        stream.__iter__.return_value = iter([NS(type="response.reasoning.delta", delta="hidden")]
                                            + [NS(type="response.output_text.delta", delta=ch) for ch in raw]
                                            + [NS(type="response.completed", response=NS(output=[], status="completed"))])
        previews = []
        with patch("agent_service.openai_client._client", return_value=client):
            final = parse_model("system", "user", ConversationOutput, on_partial=lambda value: previews.append(public_preview("answer", value)))
        self.assertEqual(final.message, response.message)
        self.assertIn("中文", previews)
        self.assertNotIn("hidden", "".join(previews))
        self.assertEqual(public_preview("intent", {"rationale": "internal"}), "")
        client.responses.parse.assert_not_called()

    def test_schema_failure_after_preview_never_falls_back(self):
        client = MagicMock()
        stream = client.responses.create.return_value.__enter__.return_value
        stream.__iter__.return_value = iter([NS(type="response.output_text.delta", delta='{"message":"hello'),
                                            NS(type="response.completed", response=NS(output=[], status="completed"))])
        with patch("agent_service.openai_client._client", return_value=client):
            with self.assertRaisesRegex(ModelCallError, "SCHEMA"):
                parse_model("s", "u", ConversationOutput, on_partial=lambda _: None)
        client.responses.parse.assert_not_called()

    def test_empty_stream_marks_buffered_without_switching_model(self):
        client = MagicMock()
        stream = client.responses.create.return_value.__enter__.return_value
        stream.__iter__.return_value = iter([NS(type="response.completed", response=NS(output=[], status="completed"))])
        client.responses.parse.return_value = NS(output_parsed=ConversationOutput(message="整段"), output=[])
        modes = []
        with patch("agent_service.openai_client._client", return_value=client):
            parse_model("s", "u", ConversationOutput, model="configured", on_partial=lambda _: None, on_transport=modes.append)
        self.assertEqual(modes, ["buffered"])
        self.assertEqual(client.responses.parse.call_args.kwargs["model"], "configured")
