"""Standalone Search/Fetch contracts and real routing with local HTTP transport."""
import json
import os
import threading
import time
import unittest
from unittest.mock import Mock, patch

import httpx

from agent_service import deepseek_web_tools as deepseek, web_tools as web, web_resilience as policy
from agent_service.call_errors import WebToolError
from agent_service.service_diagnostics import diagnose
from agent_service.source_content import PageRead

URL = 'https://docs.python.org/3/tutorial/datastructures.html'
BODY = '# Lists\n\nLists are mutable sequences. append adds an item to the end of the list.'


class DeepSeekWebTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, dict(
            REVIEW_TODAY_SEARCH_PROVIDER='deepseek', REVIEW_TODAY_READ_PROVIDER='deepseek',
            REVIEW_TODAY_SEARCH_FALLBACKS='', REVIEW_TODAY_READ_FALLBACKS='',
            REVIEW_TODAY_BROWSER_FALLBACK='0', DEEPSEEK_WEB_API_KEY='WEB_TEST_KEY',
            DEEPSEEK_API_KEY='MODEL_KEY_MUST_NOT_BE_USED'))
        env.start(); self.addCleanup(env.stop)
        states = patch.object(policy, '_states', {})
        states.start(); self.addCleanup(states.stop)
        self.requests = []

    def transport(self, payload=None, *, status=200, headers=None, handler=None):
        def handle(request):
            self.requests.append(request)
            return handler(request) if handler else httpx.Response(status, json=payload, headers=headers)
        return patch.object(deepseek, '_client', side_effect=lambda:
                            httpx.Client(transport=httpx.MockTransport(handle)))

    def fresh(self):
        policy._states.clear()

    def test_direct_search_is_model_independent_and_sends_only_public_query(self):
        for model in ['deepseek', 'openai_compatible']:
            self.fresh()
            with self.subTest(model=model), patch.dict(os.environ, {'REVIEW_TODAY_LLM_PROVIDER': model}), \
                    patch('agent_service.openai_client._client') as llm, self.transport({'results': [
                        dict(url=URL, title='Python', summary='long summary', snippet='short',
                             content='NOT_FETCHED', authority=4, rerank_score=3)]}):
                result = json.loads(web.web_search_text('Python lists site:docs.python.org'))
                self.assertEqual(result['protocol'], web.PROTOCOL)
                self.assertEqual(result['provider'], 'deepseek')
                self.assertEqual(result['results'], [dict(url=URL, title='Python', snippet='long summary')])
                req = self.requests[-1]
                self.assertEqual(str(req.url), deepseek.BASE_URL + 'search')
                self.assertEqual(req.headers['authorization'], 'Bearer WEB_TEST_KEY')
                self.assertEqual(req.headers['content-type'], 'application/json')
                self.assertEqual(json.loads(req.content), dict(
                    query='Python lists site:docs.python.org', count=5, need_content=False))
                self.assertNotIn('NOT_FETCHED', json.dumps(result))
                llm.assert_not_called()

    def test_search_deduplicates_filters_private_urls_and_ignores_extra_fields(self):
        with self.transport({'answer': 'NOT_EVIDENCE', 'results': [
            dict(url='http://127.0.0.1/private', content='PRIVATE'),
            dict(url=URL, title='T' * 400, summary='S' * 2000),
            dict(url=URL, title='duplicate'),
            dict(url='https://example.com/?token=private', snippet='PRIVATE'),
            dict(url='https://example.com/public', title='', snippet='fallback summary')]}):
            result = json.loads(web.web_search_text('Python lists'))
        self.assertEqual(len(result['results']), 2)
        self.assertEqual(len(result['results'][0]['title']), 300)
        self.assertEqual(len(result['results'][0]['snippet']), 1500)
        self.assertEqual(result['results'][1]['snippet'], 'fallback summary')
        self.assertEqual(result['results'][1]['title'], 'https://example.com/public')
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('NOT_EVIDENCE', json.dumps(result))

    def test_128_unicode_characters_are_sent_unchanged(self):
        query = '公开概念' * 32
        with self.transport({'results': []}):
            result = json.loads(web.web_search_text(query))
        self.assertEqual(result['results'], [])
        self.assertEqual(json.loads(self.requests[0].content)['query'], query)

    def test_long_query_skips_deepseek_and_preserves_filters_for_explicit_fallback(self):
        query = '公开概念' * 32 + ' site:docs.python.org -site:example.com'
        fallback = Mock()
        fallback.search.return_value = [web.SearchResult(URL, 'Python')]
        real_backend = web._backend
        with patch.dict(os.environ, {'REVIEW_TODAY_SEARCH_FALLBACKS': 'tavily'}), \
                patch.object(web, '_backend', side_effect=lambda p:
                             fallback if p == 'tavily' else real_backend(p)), self.transport({'results': []}):
            result = json.loads(web.web_search_text(query))
        self.assertEqual(result['provider'], 'tavily')
        self.assertEqual(fallback.search.call_args.args, (query,))
        self.assertEqual(self.requests, [])
        self.assertEqual(policy.provider_state('deepseek').until, 0)

    def test_long_query_with_no_fallback_fails_without_network(self):
        with self.transport({'results': []}), self.assertRaises(WebToolError) as caught:
            web.web_search_text('公开' * 65)
        self.assertEqual(caught.exception.diagnostic, 'RT.WEB.UNSUPPORTED')
        self.assertEqual(self.requests, [])

    def test_missing_web_key_never_borrows_model_key_or_contacts_api(self):
        with patch.dict(os.environ, {'DEEPSEEK_WEB_API_KEY': ''}), self.transport({'results': []}):
            self.assertEqual(web.web_search_capability()['reason'], 'RT.WEB.NO_KEY')
            self.assertEqual(web.web_read_capability()['status'], 'unavailable')
            with self.assertRaisesRegex(WebToolError, 'CHAIN_FAILED'):
                web.web_search_text('Python lists')
        self.assertEqual(self.requests, [])

    def test_missing_web_key_does_not_block_configured_existing_fallback(self):
        fallback = Mock()
        fallback.search.return_value = [web.SearchResult(URL, 'Python')]
        real_backend = web._backend
        with patch.dict(os.environ, {'DEEPSEEK_WEB_API_KEY': '', 'REVIEW_TODAY_SEARCH_FALLBACKS': 'tavily'}), \
                patch.object(web, '_backend', side_effect=lambda p:
                             fallback if p == 'tavily' else real_backend(p)), self.transport({'results': []}):
            self.assertEqual(json.loads(web.web_search_text('Python'))['provider'], 'tavily')
        self.assertEqual(self.requests, [])

    def test_fetch_returns_bounded_markdown_with_observed_provenance(self):
        with self.transport(dict(title='Python lists', content=BODY)):
            result = web.read_public_url(URL, limit=30)
        self.assertIsInstance(result, PageRead)
        self.assertEqual(result, ('Python lists', BODY[:30]))
        self.assertEqual(result.details, dict(provider='deepseek', requested_url=URL,
                                             content_kind='page_text', truncated=True))
        req = self.requests[0]
        self.assertEqual(str(req.url), deepseek.BASE_URL + 'fetch')
        self.assertEqual(json.loads(req.content), {'url': URL})
        self.assertNotIn('final_url', result.details)

    def test_fetch_without_title_still_reads_body(self):
        with self.transport(dict(title='', content=BODY)):
            self.assertEqual(web.read_public_url(URL), (URL, BODY))

    def test_escaped_technical_prose_is_readable_and_original_content_is_preserved(self):
        body = (r'\# JavaScript examples' + '\n\n' +
                'This article explains how browser events update an accessible user interface.\n' +
                r'var a\=window\.x\; document\.title\=\"Example\"\; function\(\)\{window\.y\=2\;\}')
        with self.transport(dict(title='Examples', content=body)):
            self.assertEqual(web.read_public_url(URL), ('Examples', body))

    def test_missing_body_or_access_shell_is_never_read_evidence(self):
        for payload in [dict(title='Python'), dict(title='Python', content=''),
                        dict(title='Python', content=[]), dict(title='Python', content='Python'),
                        dict(title='Login', content='Sign in to continue'),
                        dict(title='Shell', content='var a=window.x; document.cookie="a"; function(){window.y=2;};'),
                        dict(title='Shell', content=r'var a\=window\.x\; document\.cookie\=\"a\"\; function\(\)\{window\.y\=2\;\}\;')]:
            self.fresh()
            with self.subTest(payload=payload), self.transport(payload):
                search = json.dumps(dict(protocol=web.PROTOCOL, results=[dict(url=URL, snippet='claim')]))
                self.assertEqual(web.read_search_evidence(search), [])

    def test_malformed_search_success_is_not_a_result(self):
        for payload in [{'results': None}, {'results': 'model answer'}, {'error': 'SECRET'}, []]:
            self.fresh()
            with self.subTest(payload=payload), self.transport(payload), self.assertRaises(WebToolError) as caught:
                web.web_search_text('Python')
            self.assertEqual(caught.exception.diagnostic, 'RT.WEB.PROTOCOL')
            self.assertNotIn('SECRET', str(caught.exception))

    def test_transport_size_redirect_and_timeout_fail_once_without_leaking_body(self):
        for status, payload, cause in [(302, {}, 'PROVIDER'), (408, {}, 'TIMEOUT'),
                                       (500, {'error': 'PRIVATE'}, 'PROVIDER'),
                                       (200, {'results': [], 'padding': 'x' * 1_000_001}, 'PROTOCOL')]:
            self.fresh()
            before = len(self.requests)
            with self.subTest(status=status, cause=cause), self.transport(payload, status=status), \
                    self.assertRaises(WebToolError) as caught:
                web.web_search_text('Python')
            self.assertEqual(len(self.requests), before + 1)
            self.assertEqual(caught.exception.diagnostic, 'RT.WEB.' + cause)
            self.assertNotIn('PRIVATE', str(caught.exception))

    def test_boundary_checks_run_before_network_and_fallback(self):
        with self.transport({'results': []}), patch.object(web, '_backend', wraps=web._backend) as factory:
            for query in ['secret=private_value', '内部文档：未公开项目方案']:
                with self.subTest(query=query), self.assertRaises(WebToolError):
                    web.web_search_text(query)
            for url in ['http://localhost/secret', 'https://example.com/?token=private',
                        'http://127.0.0.1/', 'file:///tmp/private', 'https://u:p@example.com/']:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    web.read_public_url(url)
            factory.assert_not_called()
        self.assertEqual(self.requests, [])

    def test_page_403_and_404_fall_back_without_cooling_other_pages_or_search(self):
        for status in [403, 404]:
            self.fresh()
            fallback = Mock()
            fallback.read.return_value = ('Backup', BODY)
            real_backend = web._backend
            def handle(request):
                if request.url.path.endswith('/fetch') and json.loads(request.content)['url'] == URL:
                    return httpx.Response(status, json={'error': {'message': 'PRIVATE'}})
                if request.url.path.endswith('/search'):
                    return httpx.Response(200, json={'results': [dict(url=URL, title='Python')]})
                return httpx.Response(200, json=dict(title='Other', content=BODY))
            with self.subTest(status=status), patch.dict(os.environ, {'REVIEW_TODAY_READ_FALLBACKS': 'tavily'}), \
                    patch.object(web, '_backend', side_effect=lambda p:
                                 fallback if p == 'tavily' else real_backend(p)), self.transport(handler=handle):
                self.assertEqual(web.read_public_url(URL), ('Backup', BODY))
                self.assertEqual(policy.provider_state('deepseek').until, 0)
                self.assertEqual(web.read_public_url('https://docs.python.org/3/'), ('Other', BODY))
                self.assertEqual(json.loads(web.web_search_text('Python'))['provider'], 'deepseek')
                fallback.read.assert_called_once()

    def test_auth_and_balance_errors_cool_search_and_read_without_retry(self):
        for status, code in [(401, 'AUTH_REQUIRED'), (402, 'BALANCE_REQUIRED')]:
            self.fresh()
            with self.subTest(status=status), self.transport({'error': {'message': 'PRIVATE'}}, status=status):
                with self.assertRaises(WebToolError) as caught:
                    web.web_search_text('Python')
                self.assertEqual(caught.exception.diagnostic, 'RT.WEB.' + code)
                self.assertGreater(policy.provider_state('deepseek').until, time.monotonic() + 3500)
                before = len(self.requests)
                with self.assertRaises(WebToolError): web.read_public_url(URL)
                self.assertEqual(len(self.requests), before)
                self.assertNotIn('PRIVATE', str(caught.exception))
        error = WebToolError('BALANCE_REQUIRED', 'HTTP 402')
        self.assertEqual(diagnose(error)['category'], 'balance_required')
        self.assertFalse(diagnose(error)['retryable'])

    def test_rate_limit_retry_after_is_shared_by_operations(self):
        with self.transport({'error': 'PRIVATE'}, status=429, headers={'Retry-After': '7200'}):
            with self.assertRaises(WebToolError): web.web_search_text('Python')
            with self.assertRaises(WebToolError): web.read_public_url(URL)
        self.assertEqual(len(self.requests), 1)
        self.assertGreater(policy.provider_state('deepseek').until, time.monotonic() + 7198)

    def test_web_key_rotation_resets_cooldown_but_model_key_does_not(self):
        state = policy.provider_state('deepseek')
        state.until = time.monotonic() + 3600
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'OTHER_MODEL_KEY'}):
            self.assertIs(policy.provider_state('deepseek'), state)
        with patch.dict(os.environ, {'DEEPSEEK_WEB_API_KEY': 'OTHER_WEB_KEY'}):
            self.assertIsNot(policy.provider_state('deepseek'), state)

    def test_single_provider_consumes_shared_round_budget_and_emits_events(self):
        events = []
        with self.transport({'results': []}), policy.web_round_scope(on_event=events.append) as state, \
                patch.object(policy, 'ROUND_CALLS', 1):
            web.web_search_text('Python')
            with self.assertRaisesRegex(WebToolError, 'BUDGET_EXHAUSTED'): web.read_public_url(URL)
            self.assertEqual(state.calls, 1)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual([(e['operation'], e['status']) for e in events], [('search', 'started'), ('search', 'empty')])

    def test_single_provider_paces_search_and_read_together(self):
        starts = []
        def handle(request):
            starts.append(time.monotonic())
            return httpx.Response(200, json={'results': []} if request.url.path.endswith('/search') else
                                  dict(title='Python', content=BODY))
        with self.transport(handler=handle):
            web.web_search_text('Python')
            web.read_public_url(URL)
        self.assertGreaterEqual(starts[1] - starts[0], .23)

    def test_cancel_waiting_for_single_provider_does_not_send_request(self):
        state = policy.provider_state('deepseek')
        state.slot.acquire()
        handles, errors = [], []
        ready = threading.Event()
        def run():
            try:
                web.web_search_text('Python', on_cancel_handle=lambda h: (handles.append(h), ready.set()))
            except WebToolError as exc:
                errors.append(exc.code)
        with self.transport({'results': []}):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(ready.wait(1))
                handles[0]()
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, ['RT.WEB.CANCELLED'])
                self.assertEqual(self.requests, [])
            finally:
                state.slot.release()
                thread.join(1)

    def test_http_cancel_closes_client_without_accepting_late_success(self):
        clients = []
        def factory():
            client = httpx.Client(transport=httpx.MockTransport(lambda req:
                                httpx.Response(200, json={'results': []})))
            clients.append(client)
            return client
        with patch.object(deepseek, '_client', side_effect=factory), self.assertRaisesRegex(WebToolError, 'CANCELLED'):
            web.web_search_text('Python', on_cancel_handle=lambda close: close())
        # Immediate route cancellation occurs before even constructing an HTTP client.
        self.assertEqual(clients, [])
        with patch.object(deepseek, '_client', side_effect=factory), self.assertRaisesRegex(WebToolError, 'CANCELLED'):
            deepseek.DeepSeekWebBackend('WEB_TEST_KEY').search('Python', on_cancel_handle=lambda close: close())
        self.assertTrue(clients[-1].is_closed)

    def test_deepseek_read_can_use_browser_as_last_explicit_fallback(self):
        browser = Mock()
        browser.read.return_value = PageRead('Rendered', BODY, details={'final_url': URL})
        real_backend = web._backend
        with patch.dict(os.environ, {'REVIEW_TODAY_BROWSER_FALLBACK': '1'}), \
                patch.object(web, '_backend', side_effect=lambda p:
                             browser if p == 'browser' else real_backend(p)), self.transport({}, status=404):
            self.assertEqual(web.provider_chain('read'), ['deepseek', 'browser'])
            self.assertEqual(web.provider_chain('search'), ['deepseek'])
            result = web.read_public_url(URL)
        self.assertEqual(result[1], BODY)
        self.assertEqual(result.details['final_url'], URL)
        self.assertEqual(browser.read.call_args.args, (URL,))

    def test_unused_deepseek_key_never_changes_existing_service_order(self):
        with patch.dict(os.environ, {'REVIEW_TODAY_SEARCH_PROVIDER': 'exa',
                                    'REVIEW_TODAY_READ_PROVIDER': 'exa',
                                    'REVIEW_TODAY_SEARCH_FALLBACKS': 'tavily',
                                    'REVIEW_TODAY_READ_FALLBACKS': 'tavily'}):
            self.assertEqual(web.provider_chain('search'), ['exa', 'tavily'])
            self.assertEqual(web.provider_chain('read'), ['exa', 'tavily'])


if __name__ == '__main__':
    unittest.main()
