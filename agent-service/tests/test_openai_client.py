from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent_service.openai_client import parse_model
from agent_service.schemas import IntentClass


class ParseModelCompatibilityTests(unittest.TestCase):
    def test_deep_reasoning_survives_endpoint_compatibility(self):
        parsed = IntentClass(intent="remember_content")
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=None)
        client.chat.completions.parse.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))])
        with patch("agent_service.openai_client._client", return_value=client):
            parse_model("system", "user", IntentClass, reasoning_effort="high")
        self.assertEqual(client.responses.parse.call_args.kwargs["reasoning"], {"effort": "high"})
        self.assertEqual(client.chat.completions.parse.call_args.kwargs["reasoning_effort"], "high")

    def test_returns_responses_structured_output_without_fallback(self) -> None:
        parsed = IntentClass(intent="remember_content")
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=parsed)

        with patch("agent_service.openai_client._client", return_value=client):
            result = parse_model("system", "user", IntentClass)

        self.assertIs(result, parsed)
        client.chat.completions.parse.assert_not_called()

    def test_falls_back_when_responses_completes_without_output(self) -> None:
        parsed = IntentClass(intent="remember_content")
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=None)
        client.chat.completions.parse.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))]
        )

        with patch("agent_service.openai_client._client", return_value=client):
            result = parse_model("system", "user", IntentClass)

        self.assertIs(result, parsed)
        client.chat.completions.parse.assert_called_once()
        messages = client.chat.completions.parse.call_args.kwargs["messages"]
        self.assertEqual([message["role"] for message in messages], ["system", "user"])

    def test_output_reserve_is_enforced_on_responses_and_compatible_fallback(self) -> None:
        parsed = IntentClass(intent="remember_content")
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=None)
        client.chat.completions.parse.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))])
        with patch("agent_service.openai_client._client", return_value=client):
            parse_model("system", "user", IntentClass, max_output_tokens=4096)
        self.assertEqual(client.responses.parse.call_args.kwargs['max_output_tokens'], 4096)
        self.assertEqual(client.chat.completions.parse.call_args.kwargs['max_completion_tokens'], 4096)

    def test_fails_when_both_structured_endpoints_return_empty(self) -> None:
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=None)
        client.chat.completions.parse.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=None))]
        )

        with patch("agent_service.openai_client._client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "RT.MODEL.EMPTY"):
                parse_model("system", "user", IntentClass)

    def test_refusal_is_not_retried_as_empty_output(self) -> None:
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=None, output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])])
        with patch("agent_service.openai_client._client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "RT.MODEL.REFUSAL"):
                parse_model("system", "user", IntentClass)
        client.chat.completions.parse.assert_not_called()

    def test_incomplete_response_is_not_a_success(self) -> None:
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=None, status="incomplete")
        with patch("agent_service.openai_client._client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "RT.MODEL.INCOMPLETE"):
                parse_model("system", "user", IntentClass)
        client.chat.completions.parse.assert_not_called()

    def test_probe_requires_actual_structured_value(self) -> None:
        from agent_service.openai_client import model_is_callable
        with patch("agent_service.openai_client.parse_model", return_value=SimpleNamespace(ready=False)) as parse:
            self.assertFalse(model_is_callable("configured-role"))
            self.assertEqual(parse.call_args.kwargs["model"], "configured-role")


class WebSearchEvidenceTests(unittest.TestCase):
    def test_only_completed_tool_and_response_with_text_can_succeed(self):
        from agent_service import openai_client as llm
        cases = [
            ("completed", [], "https://example.org model guess", "UNSUPPORTED"),
            ("incomplete", [SimpleNamespace(type="web_search_call", status="completed")], "source", "INCOMPLETE"),
            ("completed", [SimpleNamespace(type="web_search_call", status="failed")], "source", "UNSUPPORTED"),
            ("completed", [SimpleNamespace(type="web_search_call", status="completed")], "", "EMPTY"),
            ("completed", [SimpleNamespace(type="web_search_call", status="completed")], "https://example.org real source", None),
        ]
        for status, output, text, error in cases:
            client = Mock()
            client.responses.create.return_value = SimpleNamespace(status=status, output=output, output_text=text)
            with self.subTest(error=error), patch.object(llm, "PROVIDER", "openai_compatible"), patch.object(llm, "_client", return_value=client):
                if error:
                    with self.assertRaisesRegex(llm.ModelCallError, "RT.MODEL." + error):
                        llm.web_search_text("public topic")
                else:
                    self.assertEqual(llm.web_search_text("public topic", reasoning_effort="high"), text)
                    self.assertEqual(client.responses.create.call_args.kwargs["reasoning"], {"effort": "high"})
                self.assertEqual(client.responses.create.call_count, 1)


if __name__ == "__main__":
    unittest.main()
