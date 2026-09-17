import json
import unittest
from unittest.mock import patch

import httpx

from agent_service import deepseek_search as search
from agent_service.execution_policy import budget_scope
from agent_service.openai_client import ModelCallError
from agent_service.service_diagnostics import diagnose


def call(identifier="s1"):
    return dict(type="server_tool_use", name="web_search", id=identifier, input={"query": "public"})


def result(content=None, identifier="s1"):
    return dict(type="web_search_tool_result", tool_use_id=identifier,
                content=content if content is not None else [dict(type="web_search_result", title="Python", url="https://docs.python.org/3/tutorial/datastructures.html", encrypted_content="PRIVATE")])


class SearchEvidenceTests(unittest.TestCase):
    def test_tool_stop_with_real_results_is_usable_and_sanitized(self):
        value = search.search_results(dict(stop_reason="tool_use", content=[
            {"type": "thinking", "thinking": "PRIVATE"}, call(), result(),
            {"type": "text", "text": "https://invented.example/ PRIVATE"}]))
        self.assertNotIn("PRIVATE", value)
        self.assertNotIn("invented", value)
        self.assertEqual(len(json.loads(value)["results"]), 1)

    def test_text_only_unmatched_results_and_missing_result_cannot_prove_search(self):
        for blocks, code in [([{"type": "text", "text": "https://docs.python.org"}], "UNSUPPORTED"),
                             ([result()], "UNSUPPORTED"), ([call(), result(identifier="wrong")], "INCOMPLETE")]:
            with self.subTest(code=code), self.assertRaisesRegex(ModelCallError, code):
                search.search_results({"content": blocks})

    def test_completed_empty_list_is_distinct_from_failed_tool(self):
        self.assertEqual(json.loads(search.search_results({"content": [call(), result([])]}))["results"], [])
        for error in ["max_uses_exceeded", "unavailable", "SECRET_ERROR_BODY"]:
            with self.subTest(error=error), self.assertRaises(ModelCallError) as raised:
                search.search_results({"content": [call(), result({"type": "web_search_tool_result_error", "error_code": error})]})
            self.assertFalse(diagnose(raised.exception)["retryable"])
            self.assertNotIn(error, str(raised.exception))

    def test_limit_after_results_preserves_partial_results_without_continuation(self):
        value = json.loads(search.search_results({"content": [call(), result(), call("s2"),
            result({"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}, "s2")]}))
        self.assertTrue(value["partial"])
        self.assertEqual(value["errors"], ["max_uses_exceeded"])
        self.assertEqual(len(value["results"]), 1)

    def test_invalid_urls_and_malformed_payload_are_not_empty_success(self):
        for url in ["javascript:alert(1)", "https://key:secret@example.com", "https://[bad", "https://example.com/ bad"]:
            with self.subTest(url=url), self.assertRaisesRegex(ModelCallError, "SEARCH_FAILED"):
                search.search_results({"content": [call(), result([{"type": "web_search_result", "url": url}])]})
        for payload in [None, {}, {"content": "text"}]:
            with self.assertRaisesRegex(ModelCallError, "PROTOCOL"):
                search.search_results(payload)


class SearchTransportTests(unittest.TestCase):
    def invoke(self, handler, **kwargs):
        client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
        with patch.object(search, "_client", return_value=client), patch.object(search, "openai_key", return_value="TEST_KEY"):
            return search.web_search_text("public topic", model="deepseek-v4-pro", **kwargs)

    def test_same_provider_model_bounded_tools_budget_and_cancel(self):
        requests, handles = [], []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"content": [call(), result()]})
        with budget_scope() as budget:
            self.invoke(handler, reasoning_effort="high", on_cancel_handle=handles.append)
            self.assertEqual(budget.attempts, 1)
        self.assertEqual(len(handles), 1)
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(str(request.url), search.ENDPOINT)
        self.assertEqual(request.headers["x-api-key"], "TEST_KEY")
        body = json.loads(request.content)
        self.assertEqual(body["model"], "deepseek-v4-pro")
        self.assertEqual(body["thinking"]["type"], "enabled")
        self.assertEqual(body["tools"][0]["max_uses"], 2)
        handles[0]()  # closing twice remains safe

    def test_http_errors_and_redirect_never_expose_body_or_forward_key(self):
        for status in [302, 401, 403, 429, 500]:
            requests = []
            def handler(request):
                requests.append(request)
                return httpx.Response(status, text="PRIVATE_KEY_AND_BODY", headers={"location": "https://other.example/"})
            with self.subTest(status=status), self.assertRaises(ModelCallError) as raised:
                self.invoke(handler)
            self.assertEqual(len(requests), 1)
            self.assertEqual(raised.exception.diagnostic, f"HTTP {status}")
            self.assertNotIn("PRIVATE", str(raised.exception))

    def test_missing_key_never_opens_connection(self):
        with patch.object(search, "openai_key", return_value=""), patch.object(search, "_client") as client:
            with self.assertRaisesRegex(RuntimeError, "NO_KEY"):
                search.web_search_text("query", model="deepseek-v4-flash")
            client.assert_not_called()

    def test_timeout_and_invalid_json_are_distinct(self):
        def timeout(request):
            raise httpx.ReadTimeout("PRIVATE", request=request)
        with self.assertRaisesRegex(ModelCallError, "TIMEOUT"):
            self.invoke(timeout)
        with self.assertRaisesRegex(ModelCallError, "PROTOCOL"):
            self.invoke(lambda r: httpx.Response(200, text="not json"))

    def test_shared_attempt_limit_and_deadline_prevent_request(self):
        for expired in [False, True]:
            requests = []
            with budget_scope() as budget:
                budget.attempts = 2
                budget.expired = expired
                with self.assertRaisesRegex(ModelCallError, "TIMEOUT" if expired else "ATTEMPTS_EXHAUSTED"):
                    self.invoke(lambda r: requests.append(r))
            self.assertEqual(requests, [])
