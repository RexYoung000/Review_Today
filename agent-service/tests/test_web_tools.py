import json
import os
import unittest
from unittest.mock import patch, Mock

import httpx
from agent_service import web_tools as web, tavily_tools
from agent_service.call_errors import WebToolError
from agent_service.execution_policy import budget_scope
from agent_service.service_diagnostics import diagnose


class IndependentWebTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.dict(os.environ, dict(REVIEW_TODAY_SEARCH_PROVIDER='tavily',
            REVIEW_TODAY_READ_PROVIDER='tavily', TAVILY_API_KEY='WEB_TEST_KEY'))
        self.config.start()
        self.addCleanup(self.config.stop)

    def transport(self, payload, *, status=200):
        self.requests = []
        def handle(request):
            self.requests.append(request)
            return httpx.Response(status, json=payload)
        return patch.object(tavily_tools, '_client', side_effect=lambda: httpx.Client(transport=httpx.MockTransport(handle)))

    def test_search_is_direct_and_model_independent(self):
        from agent_service import openai_client
        for model in ['deepseek-v4-flash', 'deepseek-v4-pro', 'different-provider']:
            with self.subTest(model=model), patch.dict(os.environ, {'REVIEW_TODAY_LLM_PROVIDER': model}), patch.object(openai_client, '_client') as llm, self.transport({'results': [{'url': 'https://example.com/a', 'title': 'A', 'content': 'snippet'}]}):
                result = json.loads(web.web_search_text('public topic'))
                self.assertEqual(result['protocol'], web.PROTOCOL)
                req = self.requests[0]
                self.assertEqual(str(req.url), 'https://api.tavily.com/search')
                self.assertEqual(req.headers['Authorization'], 'Bearer WEB_TEST_KEY')
                body = json.loads(req.content)
                self.assertNotIn('model', body)
                self.assertNotIn('messages', body)
                self.assertNotIn('tools', body)
                self.assertFalse(body['include_answer'])
                self.assertFalse(body['auto_parameters'])
                llm.assert_not_called()

    def test_no_configuration_never_falls_back_to_model(self):
        from agent_service import openai_client
        for provider, key, error in [('none', '', 'NOT_CONFIGURED'), ('tavily', '', 'NO_KEY'), ('unknown', 'key', 'UNSUPPORTED')]:
            with self.subTest(provider=provider), patch.dict(os.environ, {'REVIEW_TODAY_SEARCH_PROVIDER': provider, 'TAVILY_API_KEY': key,
                'REVIEW_TODAY_SEARCH_FALLBACKS': '', 'REVIEW_TODAY_TAVILY_KEYLESS': '0'}), patch.object(openai_client, '_client') as llm, patch.object(tavily_tools, '_client') as http:
                self.assertEqual(web.web_search_capability()['status'], 'unavailable')
                with self.assertRaisesRegex(WebToolError, error):
                    web.web_search_text('public topic')
                llm.assert_not_called(); http.assert_not_called()

    def test_search_allowlist_drops_private_urls_and_extra_fields(self):
        with self.transport({'answer': 'not evidence', 'results': [
            {'url': 'http://127.0.0.1/secret', 'content': 'SECRET'},
            {'url': 'https://example.com/a', 'title': 'A', 'content': 'snippet', 'raw_content': 'SECRET'},
            {'url': 'https://example.com/a', 'title': 'duplicate'}]}):
            result = web.web_search_text('topic')
        self.assertEqual(len(json.loads(result)['results']), 1)
        self.assertNotIn('SECRET', result)
        self.assertNotIn('not evidence', result)

    def test_extract_reads_body_and_uses_only_requested_url(self):
        with self.transport({'results': [{'url': 'https://example.com/a', 'raw_content': 'actual page body'}]}):
            title, body = web.read_public_url('https://example.com/a', limit=6)
        self.assertEqual(body, 'actual')
        req = self.requests[0]
        self.assertEqual(str(req.url), 'https://api.tavily.com/extract')
        self.assertEqual(json.loads(req.content)['urls'], ['https://example.com/a'])
        self.assertNotIn('query', json.loads(req.content))

    def test_extract_partial_failure_or_wrong_url_is_not_success(self):
        for results in [[], [{'url': 'https://example.com/other', 'raw_content': 'body'}], [{'url': 'https://example.com/a', 'content': 'snippet'}]]:
            with self.subTest(results=results), self.transport({'results': results, 'failed_results': [{'error': 'SECRET'}]}):
                with self.assertRaisesRegex(WebToolError, 'READ_FAILED'):
                    web.read_public_url('https://example.com/a')

    def test_remote_url_restrictions_before_network(self):
        for url in ['http://localhost', 'http://127.1', 'http://2130706433', 'http://0x7f000001', 'http://[::1]', 'http://x.internal/a', 'http://a.local', 'http://user:pass@example.com', 'http://example.com:8742', 'file:///tmp/a', 'http://foo\\@example.com', 'https://example.com/a\n']:
            with self.subTest(url=url), patch.object(tavily_tools, '_client') as http:
                with self.assertRaises(ValueError): web.read_public_url(url)
                http.assert_not_called()

    def test_local_ssrf_rejection_does_not_trigger_remote_fallback(self):
        with patch.dict(os.environ, {'REVIEW_TODAY_READ_PROVIDER': 'local'}), patch('agent_service.capture.fetch.fetch_public_url', side_effect=ValueError('RT.CAPTURE.SSRF')), patch.object(tavily_tools, '_client') as http:
            with self.assertRaisesRegex(ValueError, 'SSRF'): web.read_public_url('https://example.com')
            http.assert_not_called()

    def test_provider_error_drops_body_and_is_not_credential_retry(self):
        for status in [401, 403, 400]:
            with self.subTest(status=status), self.transport({'secret': 'PRIVATE'}, status=status):
                with self.assertRaises(WebToolError) as caught: web.web_search_text('topic')
                self.assertNotIn('PRIVATE', str(caught.exception))
                self.assertFalse(diagnose(caught.exception)['retryable'])

    def test_registration_closes_http_client_on_cancel(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={'results': []})))
        with patch.object(tavily_tools, '_client', return_value=client):
            def cancel(close): close()
            with self.assertRaises(RuntimeError): web.web_search_text('topic', on_cancel_handle=cancel)
        self.assertTrue(client.is_closed)

    def test_shared_attempt_budget_caps_search_requests(self):
        with self.transport({'results': []}), budget_scope() as budget:
            web.web_search_text('topic'); web.web_search_text('topic')
            with self.assertRaisesRegex(RuntimeError, 'ATTEMPTS_EXHAUSTED'): web.web_search_text('topic')
            self.assertEqual(len(self.requests), 2)

    def test_snippet_is_not_read_evidence(self):
        search = json.dumps({'protocol': web.PROTOCOL, 'results': [{'url': 'https://example.com/a', 'snippet': 'sounds verified'}]})
        with patch.object(web, 'read_public_url', side_effect=WebToolError('READ_FAILED')):
            self.assertEqual(web.read_search_evidence(search), [])
        self.assertEqual(web.read_search_evidence('model says https://example.com/a is verified'), [])

    def test_capture_wont_confirm_without_read_body(self):
        from agent_service.capture import verify_node
        search = json.dumps({'protocol': web.PROTOCOL, 'results': [{'url': 'https://example.com/a', 'snippet': 'claim'}]})
        with patch('agent_service.capture.fetch_public_url', side_effect=WebToolError('READ_FAILED')), patch('agent_service.capture._parse_capture_model') as model:
            result = verify_node({'raw_text': 'claim', 'search_runner': lambda _: search})
        self.assertEqual(result['outcome'], 'needs_attention')
        model.assert_not_called()

    def test_capture_confirms_only_after_body_read_and_assessed(self):
        from agent_service.capture import verify_node
        from agent_service.schemas import VerifyVerdict
        search = json.dumps({'protocol': web.PROTOCOL, 'results': [{'url': 'https://example.com/a', 'snippet': 'snippet'}]})
        with patch('agent_service.capture.fetch_public_url', return_value=('A', 'ACTUAL_BODY')), patch('agent_service.capture._parse_capture_model', return_value=VerifyVerdict(verdict='confirmed', reason='supported')) as model:
            result = verify_node({'raw_text': 'claim', 'search_runner': lambda _: search})
        self.assertEqual(result['outcome'], 'committing')
        self.assertIn('ACTUAL_BODY', model.call_args.args[1])
        self.assertNotIn('snippet', model.call_args.args[1])
