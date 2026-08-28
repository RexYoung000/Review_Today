from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent_service.openai_client import parse_model
from agent_service.schemas import IntentClass


class ParseModelCompatibilityTests(unittest.TestCase):
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

    def test_fails_when_both_structured_endpoints_return_empty(self) -> None:
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=None)
        client.chat.completions.parse.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=None))]
        )

        with patch("agent_service.openai_client._client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "RT.CAPTURE.MODEL_FAILED"):
                parse_model("system", "user", IntentClass)


if __name__ == "__main__":
    unittest.main()
