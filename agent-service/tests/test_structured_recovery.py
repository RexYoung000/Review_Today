"""Real adapter + isolated Harness recovery; transports return synthetic data."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, MagicMock, patch

from agent_service import openai_client as llm
from agent_service.conversation import ConversationHarness
from agent_service.conversation_store import ConversationStore
from agent_service.harness_store import HarnessStore
from agent_service.schemas import IntentDecision, ConversationOutput, SessionMessageRequest, RunActionRequest
from agent_service.structured_output import schema_repair_instruction


def greeting():
    return IntentDecision(intents=["greeting"], relation="continuation", scope="conversation",
                          rationale="问候", light_reply="你好，可以继续提问。")


def response(raw, request_id="request-safe-123"):
    return NS(status="completed", _request_id=request_id,
              output=[NS(content=[NS(type="output_text", text=raw)])])


class OutputDiagnosticTests(unittest.TestCase):
    def test_invalid_formats_are_classified_without_body_or_parser_message(self):
        cases = [("```json\n" + greeting().model_dump_json() + "\n```", "markdown_fence"),
                 ("PRIVATE_SECRET_PREFIX", "non_json"),
                 ('{"message":"PRIVATE_SECRET', "json_syntax"),
                 ('{"message":"PRIVATE_SECRET"}\nprivate_suffix', "trailing_content"),
                 ('{"message":"PRIVATE_SECRET\n"}', "json_syntax")]
        for raw, expected in cases:
            with self.subTest(expected=expected), self.assertRaises(llm.ModelCallError) as failure:
                llm._validate_output(IntentDecision, raw, response(raw))
            error = failure.exception
            self.assertEqual(error.code, "RT.MODEL.SCHEMA")
            diagnostic = json.loads(error.diagnostic)[0]
            self.assertEqual(diagnostic["output_format"], expected)
            self.assertEqual(diagnostic["chars"], len(raw))
            self.assertEqual(diagnostic["bytes"], len(raw.encode()))
            self.assertGreaterEqual(diagnostic["line"], 1)
            self.assertGreaterEqual(diagnostic["column"], 1)
            self.assertNotIn("PRIVATE_SECRET", error.diagnostic)
            self.assertNotIn("PRIVATE_SECRET", schema_repair_instruction(error))
            self.assertEqual(error.request_id, "request-safe-123")
            self.assertIn("完整的 JSON 对象", schema_repair_instruction(error))

    def test_invalid_enums_remain_field_errors_and_ids_are_allowlisted(self):
        raw = greeting().model_dump()
        raw["intents"] = ["PRIVATE_SECRET"]
        with self.assertRaises(llm.ModelCallError) as failure:
            llm._validate_output(IntentDecision, json.dumps(raw), response("", "https://private.invalid/key"))
        error = failure.exception
        self.assertIsNone(error.request_id)
        self.assertIn("literal_error", error.diagnostic)
        self.assertNotIn("PRIVATE_SECRET", error.diagnostic)
        self.assertNotIn("output_format", error.diagnostic)
        self.assertIn("修复标出的字段", schema_repair_instruction(error))

    def test_valid_json_with_markdown_inside_string_stays_valid(self):
        output = ConversationOutput(message='示例：\n```json\n{"a": 1}\n```')
        self.assertEqual(llm._validate_output(ConversationOutput, output.model_dump_json(), response("")), output)

    def test_evidence_length_repair_knows_character_limit_without_echoing_body(self):
        from agent_service.conversation_materials import MaterialReadiness
        raw=json.dumps(dict(can_proceed=True, findings=[dict(source_id='one',role='other',sufficient=True,
                                                           evidence='PRIVATE_SECRET ' * 30)]))
        with self.assertRaises(llm.ModelCallError) as failure:
            llm._validate_output(MaterialReadiness,raw,response(raw))
        error=failure.exception
        detail=json.loads(error.diagnostic)[0]
        self.assertEqual(detail['max_length'],240)
        self.assertEqual(detail['field'],['findings',0,'evidence'])
        self.assertNotIn('PRIVATE_SECRET',schema_repair_instruction(error))
        self.assertIn('字符计数',schema_repair_instruction(error))

    def test_streaming_final_uses_same_diagnostic_and_does_not_accept_fence(self):
        raw = "```json\n" + greeting().model_dump_json() + "\n```"
        manager = MagicMock()
        manager.__enter__.return_value = iter([
            NS(type="response.output_text.delta", delta=raw),
            NS(type="response.completed", response=response(raw)),
        ])
        client = Mock()
        client.responses.create.return_value = manager
        partials = []
        with patch.object(llm, "PROVIDER", "deepseek"), patch.object(llm, "_client", return_value=client), \
             self.assertRaises(llm.ModelCallError) as failure:
            llm.parse_model("rules", "你好", IntentDecision, on_partial=partials.append)
        self.assertEqual(partials, [])
        self.assertIn("markdown_fence", failure.exception.diagnostic)
        self.assertEqual(client.responses.create.call_count, 1)


class HarnessRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ConversationStore(HarnessStore(str(Path(self.tmp.name) / "isolated.sqlite3")))
        self.harness = ConversationHarness(self.store)
        self.sid = str(uuid.uuid4())
        self.client = Mock()
        for patched in [patch.object(llm, "PROVIDER", "deepseek"),
                        patch.object(llm, "_client", return_value=self.client),
                        patch("agent_service.conversation.require_model"),
                        patch("agent_service.conversation.run_capture", side_effect=AssertionError("No saves"))]:
            patched.start()
            self.addCleanup(patched.stop)

    def accept(self):
        return self.harness.accept(self.sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
                                   content="你好", thinking_strength="deep"))

    def state(self, accepted):
        data = self.store.get(self.sid)
        return data, data["runs"][accepted.run_id]

    def test_fence_repair_keeps_context_strength_schema_and_first_failure(self):
        raw = greeting().model_dump_json()
        self.client.responses.create.side_effect = [response("```json\n" + raw + "\n```"), response(raw)]
        accepted = self.accept()
        self.harness.drain(self.sid)
        data, run = self.state(accepted)
        self.assertEqual(run["status"], "completed")
        calls = [call.kwargs for call in self.client.responses.create.call_args_list]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["input"][1], calls[1]["input"][1])
        self.assertEqual(json.loads(calls[1]["input"][1]["content"])["current_inputs"], ["你好"])
        self.assertIn("代码围栏", calls[1]["input"][0]["content"])
        self.assertIn("第 1 行第 1 列", calls[1]["input"][0]["content"])
        self.assertNotIn(raw, calls[1]["input"][0]["content"])
        for key in ("model", "reasoning", "text", "max_output_tokens"):
            self.assertEqual(calls[0][key], calls[1][key])
        self.assertEqual(calls[1]["reasoning"], {"effort": "high"})
        failed = [e for e in data["events"] if e["stage"] == "model_attempt_failed"]
        self.assertEqual([e["attempt"] for e in failed], [1])
        self.assertEqual(failed[0]["payload"]["diagnostic"]["request_id"], "request-safe-123")
        self.assertIn("markdown_fence", failed[0]["detail_summary"])
        self.assertEqual(len([m for m in data["messages"] if m["role"] == "coach"]), 1)
        self.assertEqual(data["tasks"], {})

    def test_double_failure_is_bounded_persisted_and_manual_retry_can_resume(self):
        raw = "```json\n" + greeting().model_dump_json() + "\n```"
        self.client.responses.create.return_value = response(raw)
        accepted = self.accept()
        self.harness.drain(self.sid)
        data, run = self.state(accepted)
        self.assertEqual(self.client.responses.create.call_count, 2)
        self.assertEqual(run["status"], "retryable_failed")
        self.assertIsNone(run["intent"])
        self.assertFalse([m for m in data["messages"] if m["role"] == "coach"])
        self.assertEqual([e["attempt"] for e in data["events"] if e["stage"] == "model_attempt_failed"], [1, 2])
        reopened = ConversationStore(HarnessStore(str(Path(self.tmp.name) / "isolated.sqlite3"))).get(self.sid)
        self.assertEqual(reopened["runs"][accepted.run_id]["status"], "retryable_failed")
        self.client.responses.create.return_value = response(greeting().model_dump_json())
        self.harness.action(accepted.run_id, RunActionRequest(action_id=str(uuid.uuid4()), action="retry"))
        self.harness.drain(self.sid)
        self.assertEqual(self.state(accepted)[1]["status"], "completed")
        self.assertEqual(self.client.responses.create.call_count, 3)

    def test_stop_before_first_failure_prevents_repair_and_late_publication(self):
        accepted = self.accept()
        def stopped(**kwargs):
            self.harness.action(accepted.run_id, RunActionRequest(action_id=str(uuid.uuid4()), action="stop"))
            return response("```json\n" + greeting().model_dump_json() + "\n```")
        self.client.responses.create.side_effect = stopped
        self.harness.drain(self.sid)
        data, run = self.state(accepted)
        self.assertEqual(self.client.responses.create.call_count, 1)
        self.assertNotEqual(run["status"], "completed")
        self.assertFalse([m for m in data["messages"] if m["role"] == "coach"])

    def test_visible_preview_allows_only_one_buffered_repair(self):
        from agent_service.execution_policy import current_budget
        accepted = self.accept()
        # Failed repair stays private; the original preview is retained.
        with self.store.transaction(self.sid) as data:
            data["runs"][accepted.run_id]["status"] = "running"
        def partial_then_invalid(system, prompt, schema, **kwargs):
            current_budget.get().take()
            kwargs["on_partial"]({"message": "已显示正文"})
            raise llm.ModelCallError("SCHEMA", '[{"field": [], "type": "json_invalid"}]')
        with patch("agent_service.conversation.parse_model", side_effect=partial_then_invalid) as model, \
             self.assertRaises(llm.ModelCallError):
            self.harness._call(self.sid, accepted.run_id, 1, "answer", "rules", "{}", ConversationOutput)
        self.assertEqual(model.call_count, 2)
        data, run = self.state(accepted)
        self.assertEqual(run["active_response"]["text"], "已显示正文")
        self.assertEqual(len([e for e in data["events"] if e["stage"] == "model_attempt_failed"]), 2)
