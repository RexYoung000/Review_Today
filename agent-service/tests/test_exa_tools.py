import json
import os
import unittest
from unittest.mock import patch

import httpx
from agent_service import exa_tools as exa, web_tools as web
from agent_service.call_errors import WebToolError
from agent_service.execution_policy import budget_scope
from agent_service.service_diagnostics import diagnose

URL = 'https://docs.python.org/3/tutorial/datastructures.html'
SEARCH = f'Title: Python docs\nURL: {URL}\nPublished: N/A\nAuthor: N/A\nHighlights:\nappend adds one item'
PAGE = f'# Python docs\nURL: {URL}\n\nACTUAL page body'


class Chunks(httpx.SyncByteStream):
    def __init__(self, text): self.text = text
    def __iter__(self):
        raw = self.text.encode()
        for n in range(0, len(raw), 7): yield raw[n:n+7]


class ExaTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.dict(os.environ, {'REVIEW_TODAY_SEARCH_PROVIDER': 'exa', 'REVIEW_TODAY_READ_PROVIDER': 'exa'})
        self.config.start(); self.addCleanup(self.config.stop)
        self.requests = []

    def transport(self, text=SEARCH, *, sse=True, tool_error=False, status=200, wrong_id=False, rpc_error=False, session=False):
        def handler(request):
            if request.method == 'DELETE': return httpx.Response(200)
            body = json.loads(request.content); self.requests.append(body)
            self.assertEqual(str(request.url), exa.ENDPOINT)
            self.assertNotIn('authorization', request.headers)
            self.assertNotIn('x-api-key', request.headers)
            if body['method'] == 'notifications/initialized': return httpx.Response(202)
            if body['method'] == 'initialize':
                result = dict(protocolVersion=exa.VERSION, capabilities={'tools': {}}, serverInfo={'name': 'exa', 'version': 'test'})
            else:
                self.assertEqual(request.headers['mcp-protocol-version'], exa.VERSION)
                if session: self.assertEqual(request.headers['mcp-session-id'], 'test-session')
                if status != 200: return httpx.Response(status, text='SECRET provider body')
                result = dict(content=[{'type': 'text', 'text': text}], isError=tool_error)
            payload = dict(jsonrpc='2.0', id=77 if wrong_id and body['method']=='tools/call' else body['id'], result=result)
            if rpc_error and body['method']=='tools/call': payload = dict(jsonrpc='2.0', id=body['id'], error={'message': 'SECRET'})
            headers = {'mcp-session-id': 'test-session'} if session else {}
            if sse:
                headers['content-type'] = 'text/event-stream'
                data = 'event: message\r\ndata: '+json.dumps(payload,ensure_ascii=False)+'\r\n\r\n'
                return httpx.Response(200, headers=headers, stream=Chunks(data))
            return httpx.Response(200, headers=headers, json=payload)
        return patch.object(exa, '_client', side_effect=lambda: httpx.Client(transport=httpx.MockTransport(handler)))

    def test_sse_and_json_handshake_tool_call_do_not_use_models(self):
        from agent_service import openai_client
        for sse in [True, False]:
            with self.subTest(sse=sse), self.transport(sse=sse, session=True), patch.object(openai_client, '_client') as model:
                result = json.loads(web.web_search_text('Python list'))
                self.assertEqual(result['results'][0]['url'], URL)
                call = self.requests[-1]
                self.assertEqual(call['params'], {'name':'web_search_exa','arguments':{'query':'Python list','numResults':5}})
                self.assertNotIn('model', json.dumps(call))
                model.assert_not_called()

    def test_read_body_must_match_requested_url(self):
        for text, success in [(PAGE, True), (PAGE.replace(URL, URL+'/other'), False), ('search snippet only', False), (f'# Docs\nURL: {URL}\n\n ', False)]:
            with self.subTest(text=text), self.transport(text):
                if success:
                    self.assertEqual(web.read_public_url(URL), ('Python docs', 'ACTUAL page body'))
                    self.assertEqual(self.requests[-1]['params']['arguments']['urls'], [URL])
                else:
                    with self.assertRaisesRegex(WebToolError, 'READ_FAILED'): web.read_public_url(URL)

    def test_tool_error_rate_limit_and_auth_are_sanitized_nonretryable(self):
        for text, code in [('429 rate limit SECRET', 'RATE_LIMIT'), ('401 authentication SECRET', 'AUTH_REQUIRED'), ('upstream failed SECRET', 'TOOL_FAILED')]:
            with self.subTest(code=code), self.transport(text, tool_error=True):
                with self.assertRaises(WebToolError) as caught: web.web_search_text('topic')
                self.assertTrue(caught.exception.code.endswith(code))
                self.assertNotIn('SECRET', str(caught.exception))
                self.assertFalse(diagnose(caught.exception)['retryable'])

    def test_http_429_does_not_retry_or_fallback(self):
        with self.transport(status=429), patch('agent_service.tavily_tools._client') as other:
            with self.assertRaisesRegex(WebToolError, 'RATE_LIMIT') as caught: web.web_search_text('topic')
            self.assertFalse(diagnose(caught.exception)['retryable'])
            other.assert_not_called()

    def test_protocol_does_not_accept_wrong_rpc_id_or_rpc_error(self):
        for kw, code in [({'wrong_id':True},'INCOMPLETE'), ({'rpc_error':True},'PROTOCOL')]:
            with self.subTest(kw=kw), self.transport(**kw):
                with self.assertRaisesRegex(WebToolError, code): web.web_search_text('topic')

    def test_malformed_search_text_cannot_become_sources(self):
        with self.transport('I think https://example.com is a good source'):
            with self.assertRaisesRegex(WebToolError, 'PROTOCOL'): web.web_search_text('topic')

    def test_explicit_empty_results_are_not_a_protocol_error(self):
        with self.transport('No results found.'):
            self.assertEqual(json.loads(web.web_search_text('topic'))['results'], [])

    def test_private_url_rejected_before_contacting_service(self):
        with patch.object(exa, '_client') as client:
            with self.assertRaises(ValueError): web.read_public_url('http://127.0.0.1/private')
            client.assert_not_called()

    def test_response_limit_and_missing_sse_frame(self):
        with self.transport(), patch.object(exa, 'MAX_BYTES', 20):
            with self.assertRaisesRegex(WebToolError, 'PROTOCOL'): web.web_search_text('topic')

    def test_cancel_before_network_never_retries(self):
        with self.transport():
            with self.assertRaisesRegex(WebToolError, 'CANCELLED'):
                web.web_search_text('topic', on_cancel_handle=lambda close: close())
            self.assertEqual(self.requests, [])

    def test_budget_counts_tool_attempts_not_handshake_posts(self):
        with self.transport(), budget_scope() as budget:
            web.web_search_text('topic'); web.web_search_text('topic')
            self.assertEqual(budget.attempts, 2)
            with self.assertRaisesRegex(RuntimeError, 'ATTEMPTS_EXHAUSTED'): web.web_search_text('topic')
            self.assertEqual(len(self.requests), 6)
