"""Offline provider boundary tests; no real key or user data."""
import json
import os
from pathlib import Path
import runpy
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock, patch

from pydantic import BaseModel
from agent_service import openai_client as llm


class Reply(BaseModel):
    message: str
    ready: bool


class DeepSeekConfigTests(unittest.TestCase):
    def config(self, env):
        with patch.dict(os.environ, env, clear=True), patch("dotenv.load_dotenv"), \
             patch("agent_service.certs.install_trust_store", return_value="test-ca"):
            values = runpy.run_path(str(Path(llm.__file__).with_name("config.py")))
            values["resolved_key"] = values["openai_key"]()
            return values

    def test_deepseek_does_not_inherit_old_endpoint_models_or_key(self):
        values = self.config({"REVIEW_TODAY_LLM_PROVIDER": "deepseek", "OPENAI_API_KEY": "old-test-key",
                              "OPENAI_BASE_URL": "https://old-provider.invalid", "OPENAI_ROUTER_MODEL": "old-router",
                              "DEEPSEEK_API_KEY": "deepseek-test-key"})
        self.assertEqual(values["BASE_URL"], "https://api.deepseek.com")
        self.assertEqual(values["ROUTER_MODEL"], "deepseek-flash")
        self.assertEqual(values["COACH_MODEL"], "deepseek-v4-flash")
        self.assertEqual(values["RISK_MODEL"], "deepseek-v4-pro")
        self.assertEqual(values["MODEL"], "deepseek-v4-flash")
        self.assertEqual(values["resolved_key"], "deepseek-test-key")

    def test_missing_deepseek_key_does_not_fall_back_to_old_key(self):
        self.assertEqual(self.config({"REVIEW_TODAY_LLM_PROVIDER": "deepseek", "OPENAI_API_KEY": "old-test-key"})["resolved_key"], "")

    def test_default_provider_preserves_explicit_existing_config(self):
        values = self.config({"OPENAI_BASE_URL": "https://old-provider.invalid", "OPENAI_API_KEY": "old-test-key",
                              "OPENAI_ROUTER_MODEL": "old-router", "DEEPSEEK_API_KEY": "unselected-test-key"})
        self.assertEqual(values["BASE_URL"], "https://old-provider.invalid")
        self.assertEqual(values["ROUTER_MODEL"], "old-router")
        self.assertEqual(values["resolved_key"], "old-test-key")

    def test_unknown_provider_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "RT.CONFIG.PROVIDER_UNSUPPORTED"):
            self.config({"REVIEW_TODAY_LLM_PROVIDER": "typo"})


class DeepSeekTransportTests(unittest.TestCase):
    def setUp(self):
        self.provider = patch.object(llm, "PROVIDER", "deepseek", create=True)
        self.provider.start()
        self.addCleanup(self.provider.stop)

    def test_system_rules_and_persistent_strength_mapping(self):
        for effort, expected in [(None, "none"), ("high", "high")]:
            with self.subTest(effort=effort):
                client = Mock()
                client.responses.create.return_value = NS(output=[NS(content=[NS(type="output_text", text=Reply(message="回答", ready=True).model_dump_json())])])
                with patch.object(llm, "_client", return_value=client):
                    llm.parse_model("system rules", "untrusted user input", Reply, model="deepseek-v4-flash", reasoning_effort=effort)
                params = client.responses.create.call_args.kwargs
                self.assertEqual(params["input"][0]["role"], "system")
                self.assertTrue(params["input"][0]["content"].startswith("system rules\n"))
                self.assertIn("JSON Schema", params["input"][0]["content"])
                self.assertEqual(params["input"][1]["role"], "user")
                self.assertEqual(params["reasoning"], {"effort": expected})

    def test_empty_success_does_not_silently_change_endpoint(self):
        client = Mock()
        client.responses.create.return_value = NS(output=[])
        with patch.object(llm, "_client", return_value=client), self.assertRaisesRegex(llm.ModelCallError, "RT.MODEL.EMPTY"):
            llm.parse_model("rules", "question", Reply)
        client.chat.completions.parse.assert_not_called()

    def test_real_deltas_not_reasoning_reach_preview_and_final_is_validated(self):
        client = Mock()
        final = Reply(message="你好，RAG。", ready=True)
        content = final.model_dump_json()
        response = NS(id="answer-1", status="completed", output=[NS(content=[NS(type="output_text", text=content)])])
        events = [NS(type="response.created", response=NS(id="answer-1")),
                  NS(type="response.reasoning_text.delta", delta="private reasoning"),
                  NS(type="response.output_text.delta", delta='{"message":"你'),
                  NS(type="response.output_text.delta", delta='好，RAG。","ready":true}'),
                  NS(type="response.completed", response=response)]
        manager = MagicMock()
        manager.__enter__.return_value = iter(events)
        client.responses.create.return_value = manager
        partials, transports = [], []
        with patch.object(llm, "_client", return_value=client):
            result = llm.parse_model("rules", "question", Reply, reasoning_effort="high", on_partial=partials.append, on_transport=transports.append)
        self.assertEqual(result, final)
        self.assertEqual(partials[0]["message"], "你")
        self.assertNotIn("private", json.dumps(partials))
        self.assertEqual(transports, ["streaming"])
        params = client.responses.create.call_args.kwargs
        self.assertEqual(params["reasoning"], {"effort": "high"})
        self.assertEqual(params["input"][0]["role"], "system")

    def test_search_uses_anthropic_adapter_without_old_provider_or_model_switch(self):
        for model in ["deepseek-v4-flash", "deepseek-v4-pro"]:
            with self.subTest(model=model), patch.object(llm, "_client") as client, patch("agent_service.deepseek_search.web_search_text", return_value="results") as search:
                self.assertEqual(llm.web_search_capability()["protocol"], "anthropic_messages")
                self.assertEqual(llm.web_search_text("public query", model=model), "results")
                search.assert_called_once_with("public query", model=model, reasoning_effort=None, on_cancel_handle=None)
                client.assert_not_called()

    def test_voice_is_not_sent_to_unverified_provider(self):
        with patch.object(llm, "_client") as client, self.assertRaisesRegex(llm.ModelCallError, "RT.MODEL.UNSUPPORTED"):
            llm.transcribe_audio(b"audio", "recording.wav")
        client.assert_not_called()

    def test_nullable_plan_references_are_expanded_without_weakening_constraints(self):
        from agent_service.schemas import ConversationOutput
        fmt = llm._text_format(ConversationOutput)
        self.assertTrue(fmt["strict"])
        self.assertNotIn('"$ref"', json.dumps(fmt))
        plan, null = fmt["schema"]["properties"]["learning_plan"]["anyOf"]
        self.assertEqual(plan["type"], "object")
        self.assertEqual(null, {"type": "null"})
        self.assertIn("steps", plan["required"])
        self.assertEqual(plan["properties"]["steps"]["maxItems"], 8)
        self.assertFalse(plan["additionalProperties"])

    def test_final_schema_is_still_required_for_nonstreaming_output(self):
        client = Mock()
        client.responses.create.return_value = NS(output=[NS(content=[NS(type="output_text", text='{"message":"hi"}')])])
        with patch.object(llm, "_client", return_value=client), self.assertRaisesRegex(llm.ModelCallError, "RT.MODEL.SCHEMA"):
            llm.parse_model("rules", "question", Reply)
        self.assertEqual(client.responses.create.call_count, 1)

    def test_recursive_schema_fails_explicitly(self):
        recursive = {"type": "json_schema", "schema": {"$defs": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/$defs/Node"}}}}, "$ref": "#/$defs/Node"}}
        with patch.object(llm, "type_to_text_format_param", return_value=recursive), self.assertRaisesRegex(llm.ModelCallError, "RT.MODEL.UNSUPPORTED"):
            llm._text_format(Reply)


class DeepSeekCapabilityTests(unittest.TestCase):
    def test_shared_model_is_probed_once_per_strength_and_deep_failure_is_separate(self):
        from agent_service import model_capabilities as cap
        states = {role: dict(model="deepseek-v4-flash", status="checking") for role in ("router", "coach")}
        states["risk"] = dict(model="deepseek-v4-pro", status="checking")

        def call(model, *, reasoning_effort=None):
            if model == "deepseek-v4-flash" and reasoning_effort == "high":
                raise llm.ModelCallError("UNSUPPORTED")
            return True

        with patch.object(cap, "PROVIDER", "deepseek"), patch.object(cap, "_state", states), \
             patch.object(cap, "openai_key", return_value="test-only-key"), patch.object(cap, "model_is_callable", side_effect=call) as probe:
            cap.probe()
            self.assertEqual(probe.call_count, 4)
            cap.require_model("deepseek-v4-flash", thinking_strength="smart")
            cap.require_model("deepseek-v4-pro", thinking_strength="deep")
            with self.assertRaisesRegex(llm.ModelCallError, "RT.MODEL.UNAVAILABLE"):
                cap.require_model("deepseek-v4-flash", thinking_strength="deep")
            self.assertEqual(cap.snapshot()["coach"]["status"], "ready")
            states["coach"]["strengths"]["deep"]["streaming"] = "unavailable"
            self.assertNotIn("streaming", states["router"]["strengths"]["deep"])

    def test_high_transport_probe_failure_schedules_recheck_not_downgrade(self):
        from agent_service import model_capabilities as cap
        states = {role: dict(model=role, status="ready", retryable=False,
                            strengths={"deep": dict(status="ready", retryable=False)}) for role in ("router", "coach", "risk")}

        def stream(model, *, reasoning_effort=None):
            if reasoning_effort == "high":
                raise llm.ModelCallError("CONNECTION")
            return dict(ready=True, streaming="ready")

        with patch.object(cap, "PROVIDER", "deepseek"), patch.object(cap, "_state", states), \
             patch.object(cap, "probe"), patch.object(cap, "model_stream_capability", side_effect=stream), \
             patch.object(cap, "_retry_attempt", 0), patch.object(cap, "_next_probe", 0), \
             patch.object(cap.time, "time", return_value=100), \
             patch("agent_service.conversation.conversation_harness.start"):
            cap.probe_with_streaming()
            self.assertEqual(states["coach"]["streaming"], "ready")
            self.assertTrue(states["coach"]["strengths"]["deep"]["stream_retryable"])
            self.assertEqual(cap._next_probe, 110)


if __name__ == "__main__":
    unittest.main()
