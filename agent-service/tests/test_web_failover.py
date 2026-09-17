import json
import os
import threading
import time
import unittest
from unittest.mock import patch, Mock

import httpx
from agent_service import web_tools as web, web_resilience as policy, brave_tools, tavily_tools
from agent_service.call_errors import WebToolError
from agent_service.web_http import response_error

URL = 'https://docs.python.org/3/tutorial/datastructures.html'


class FailoverTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, dict(REVIEW_TODAY_SEARCH_PROVIDER='exa',
            REVIEW_TODAY_SEARCH_FALLBACKS='tavily,brave', REVIEW_TODAY_READ_PROVIDER='exa',
            REVIEW_TODAY_READ_FALLBACKS='tavily', REVIEW_TODAY_CONTEXT_PROVIDER='brave',
            REVIEW_TODAY_TAVILY_KEYLESS='1', TAVILY_API_KEY='', BRAVE_API_KEY='TEST_ONLY'))
        self.env.start(); self.addCleanup(self.env.stop)
        self.states = patch.object(policy, '_states', {})
        self.states.start(); self.addCleanup(self.states.stop)
        self.backends = {name: Mock(name=name) for name in ['exa', 'tavily', 'brave']}
        for b in self.backends.values():
            b.search.return_value = [web.SearchResult(URL, 'Docs', 'summary')]
            b.read.return_value = ('Docs', 'actual body')
        self.factory = patch.object(web, '_backend', side_effect=lambda provider: self.backends[provider])
        self.factory.start(); self.addCleanup(self.factory.stop)

    def test_429_search_switches_and_cooldown_is_shared_with_reads(self):
        self.backends['exa'].search.side_effect = WebToolError('RATE_LIMIT')
        events = []
        with policy.web_round_scope(on_event=events.append):
            found = json.loads(web.web_search_text('Python list'))
            self.assertEqual(found['provider'], 'tavily')
            self.assertEqual(web.read_public_url(URL), ('Docs', 'actual body'))
            web.web_search_text('another topic')
        self.backends['exa'].search.assert_called_once()
        self.backends['exa'].read.assert_not_called()
        self.assertTrue(any(e['status']=='skipped' and e['provider']=='exa' for e in events))
        self.assertTrue(any(e['status']=='succeeded' and e['provider']=='tavily' for e in events))

    def test_two_failures_reach_brave_without_model_call(self):
        self.backends['exa'].search.side_effect = WebToolError('TIMEOUT')
        self.backends['tavily'].search.side_effect = WebToolError('PROVIDER', 'HTTP 503')
        with patch('agent_service.openai_client._client') as model:
            self.assertEqual(json.loads(web.web_search_text('topic'))['provider'], 'brave')
            model.assert_not_called()

    def test_exa_auth_failure_uses_tavily_and_disabled_brave_stays_off(self):
        self.backends['exa'].search.side_effect = WebToolError('PROVIDER', 'HTTP 401')
        with patch.dict(os.environ, {'REVIEW_TODAY_SEARCH_FALLBACKS': 'tavily',
                                    'REVIEW_TODAY_CONTEXT_PROVIDER': 'none'}):
            self.assertEqual(json.loads(web.web_search_text('topic'))['provider'], 'tavily')
            self.assertGreater(policy.provider_state('exa').until, time.monotonic() + 3500)
            web.read_public_url(URL)
            self.backends['exa'].read.assert_not_called()
            self.backends['tavily'].search.side_effect = WebToolError('RATE_LIMIT')
            with self.assertRaisesRegex(WebToolError, 'CHAIN_FAILED'):
                web.web_search_text('another topic')
            self.assertEqual(web.web_context_capability()['status'], 'unavailable')
            self.backends['brave'].search.assert_not_called()

    def test_exa_key_change_has_fresh_cooldown_state(self):
        with patch.dict(os.environ, {'EXA_API_KEY': 'OLD_TEST_KEY'}):
            old = policy.provider_state('exa')
            old.until = time.monotonic() + 3600
        with patch.dict(os.environ, {'EXA_API_KEY': 'NEW_TEST_KEY'}):
            self.assertIsNot(policy.provider_state('exa'), old)
            self.assertEqual(policy.provider_state('exa').until, 0)

    def test_read_failure_switches_same_url_without_search_or_global_cooldown(self):
        self.backends['exa'].read.side_effect = WebToolError('READ_FAILED')
        web.read_public_url(URL)
        self.backends['tavily'].read.assert_called_once()
        self.assertEqual(self.backends['tavily'].read.call_args.args, (URL,))
        for b in self.backends.values(): b.search.assert_not_called()
        self.assertEqual(policy.provider_state('exa').until, 0)

    def test_empty_results_only_one_supplemental_search(self):
        for b in self.backends.values(): b.search.return_value=[]
        self.assertEqual(json.loads(web.web_search_text('topic'))['results'], [])
        self.backends['brave'].search.assert_not_called()

    def test_all_failures_are_finite_nonretryable(self):
        for b in self.backends.values(): b.search.side_effect=WebToolError('CONNECTION')
        with self.assertRaisesRegex(WebToolError, 'CHAIN_FAILED') as error: web.web_search_text('topic')
        from agent_service.service_diagnostics import diagnose
        self.assertFalse(diagnose(error.exception)['retryable'])
        for b in self.backends.values(): b.search.assert_called_once()

    def test_missing_key_skips_without_contact(self):
        self.backends['exa'].search.side_effect=WebToolError('RATE_LIMIT')
        self.backends['tavily'].search.side_effect=WebToolError('RATE_LIMIT')
        def factory(provider):
            if provider=='brave': raise WebToolError('NO_KEY')
            return self.backends[provider]
        with patch.object(web, '_backend', side_effect=factory):
            with self.assertRaisesRegex(WebToolError, 'CHAIN_FAILED'): web.web_search_text('topic')
        self.backends['brave'].search.assert_not_called()

    def test_cancel_between_providers_does_not_contact_fallback(self):
        handle=[]
        def failed(*a, **kw):
            handle[0]()
            raise WebToolError('CONNECTION')
        self.backends['exa'].search.side_effect=failed
        with self.assertRaisesRegex(WebToolError,'CANCELLED'):
            web.web_search_text('topic',on_cancel_handle=handle.append)
        self.backends['tavily'].search.assert_not_called()

    def test_waiting_for_busy_provider_is_cancellable(self):
        shared=policy.provider_state('exa'); shared.slot.acquire()
        ready=threading.Event(); handles=[]; errors=[]
        def run():
            try:
                web.web_search_text('topic',on_cancel_handle=lambda h:(handles.append(h),ready.set()))
            except WebToolError as e: errors.append(e.code)
        thread=threading.Thread(target=run);thread.start()
        try:
            self.assertTrue(ready.wait(1)); handles[0]();thread.join(1)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,['RT.WEB.CANCELLED'])
            for b in self.backends.values(): b.search.assert_not_called()
        finally: shared.slot.release()

    def test_busy_provider_does_not_consume_whole_fallback_deadline(self):
        shared=policy.provider_state('exa'); shared.slot.acquire()
        try:
            with patch.object(policy,'QUEUE_SECONDS',.01):
                result=json.loads(web.web_search_text('topic'))
            self.assertEqual(result['provider'],'tavily')
            self.backends['exa'].search.assert_not_called()
        finally: shared.slot.release()

    def test_concurrent_sessions_do_not_duplicate_cold_probe(self):
        started=threading.Event(); release=threading.Event(); errors=[]; results=[]
        def failing(*a, **kw):
            started.set();release.wait(1);raise WebToolError('RATE_LIMIT')
        self.backends['exa'].search.side_effect=failing
        def run():
            try: results.append(json.loads(web.web_search_text('topic'))['provider'])
            except Exception as e: errors.append(e)
        a=threading.Thread(target=run);b=threading.Thread(target=run)
        a.start();self.assertTrue(started.wait(1));b.start();release.set();a.join(2);b.join(2)
        self.assertEqual(errors,[]);self.assertEqual(results,['tavily','tavily'])
        self.backends['exa'].search.assert_called_once()

    def test_retry_after_is_respected_and_expiry_allows_recovery(self):
        err=response_error(httpx.Response(429,headers={'Retry-After':'7200'}))
        self.backends['exa'].search.side_effect=err
        web.web_search_text('topic')
        shared=policy.provider_state('exa')
        self.assertGreater(shared.until-time.monotonic(),7198)
        shared.until=0; shared.next_start=0
        self.backends['exa'].search.side_effect=None
        self.assertEqual(json.loads(web.web_search_text('topic'))['provider'],'exa')

    def test_round_call_budget_covers_search_and_read(self):
        with policy.web_round_scope() as state, patch.object(policy,'ROUND_CALLS',2):
            web.web_search_text('topic');web.read_public_url(URL)
            self.assertEqual(state.calls,2)
            with self.assertRaisesRegex(WebToolError,'BUDGET_EXHAUSTED'):web.read_public_url(URL)

    def test_deadline_does_not_start_another_provider(self):
        with patch.object(policy,'CHAIN_SECONDS',0):
            with self.assertRaisesRegex(WebToolError,'BUDGET_EXHAUSTED'):web.web_search_text('topic')
        for b in self.backends.values(): b.search.assert_not_called()

    def test_ssrf_does_not_trigger_any_provider(self):
        with self.assertRaises(ValueError):web.read_public_url('http://127.0.0.1/secret')
        for b in self.backends.values():b.read.assert_not_called()

    def test_context_preserves_kind_and_filters_official_domains(self):
        self.backends['brave'].context.return_value=[
            dict(url=URL,title='Docs',content='extracted text',content_kind='extracted_chunks'),
            dict(url='https://python.org.evil.com/',content='untrusted')]
        pages=web.web_context_pages('Python',allowed_domains=['python.org'])
        self.assertEqual(len(pages),1);self.assertEqual(pages[0]['content_kind'],'extracted_chunks')


class ProviderTransportTests(unittest.TestCase):
    def test_keyless_tavily_uses_explicit_mode_not_model_credentials(self):
        requests=[]
        def handler(request):
            requests.append(request)
            return httpx.Response(200,json={'results':[{'url':URL,'title':'Docs','content':'text'}]})
        with patch.object(tavily_tools,'_client',side_effect=lambda:httpx.Client(transport=httpx.MockTransport(handler))):
            tavily_tools.TavilyBackend('',keyless=True).search('Python')
        self.assertNotIn('authorization',requests[0].headers)
        self.assertEqual(requests[0].headers['x-tavily-access-mode'],'keyless')

    def test_brave_context_uses_only_extracted_text_no_generated_answer(self):
        requests=[]
        def handler(request):
            requests.append(request)
            return httpx.Response(200,json={'answer':'GENERATED','grounding':{'generic':[
                {'url':URL,'title':'Docs','snippets':['actual chunk']},
                {'url':'http://127.0.0.1','snippets':['PRIVATE']}]}})
        with patch.object(brave_tools,'_client',side_effect=lambda:httpx.Client(transport=httpx.MockTransport(handler))):
            pages=brave_tools.BraveBackend('TEST_ONLY').context('Python')
        self.assertEqual(pages[0]['content'],'actual chunk');self.assertEqual(len(pages),1)
        self.assertEqual(pages[0]['content_kind'],'extracted_chunks')
        self.assertEqual(requests[0].url.path,'/res/v1/llm/context')
        self.assertEqual(requests[0].headers['x-subscription-token'],'TEST_ONLY')
        self.assertNotIn('GENERATED',str(pages))

    def test_brave_search_and_context_require_independent_key(self):
        with self.assertRaisesRegex(WebToolError,'NO_KEY'):brave_tools.BraveBackend('')

    def test_retry_after_http_date(self):
        from datetime import datetime,timedelta,timezone
        from email.utils import format_datetime
        response=httpx.Response(429,headers={'Retry-After':format_datetime(datetime.now(timezone.utc)+timedelta(minutes=10))})
        self.assertGreater(response_error(response).retry_after,598)

    def test_tavily_official_query_uses_api_domain_filter(self):
        with patch.object(tavily_tools.TavilyBackend,'_post',return_value={'results':[]}) as post:
            tavily_tools.TavilyBackend('',keyless=True).search('Python list site:docs.python.org')
        self.assertEqual(post.call_args.args[1]['include_domains'],['docs.python.org'])

    def test_keyless_cap_envelope_never_becomes_results(self):
        payload={'error':{'code':'keyless_rate_limit_exceeded','retry_after_seconds':900,'message':'SECRET','next_actions':[{'type':'agentic_payment','url':'https://example.com'}]}}
        with patch('agent_service.web_http.request_json',return_value=payload):
            with self.assertRaisesRegex(WebToolError,'RATE_LIMIT') as error:
                tavily_tools.TavilyBackend('',keyless=True).search('topic')
        self.assertEqual(error.exception.retry_after,900)
        self.assertNotIn('SECRET',str(error.exception))
