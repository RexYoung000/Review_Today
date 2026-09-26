"""Rendering fallback: provenance, public networking, budgets and cancellation."""
import json
import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

import httpx
from agent_service import browser_proxy as network, browser_reader as reader, web_tools as web, web_resilience as policy
from agent_service.browser_render import navigation_url, source_location, access_page
from agent_service.call_errors import WebToolError
from agent_service.source_content import PageRead

URL = 'https://example.com/article'
FINAL = 'https://docs.example.com/article'
BODY = '这里是实际公开正文。' * 20


def response(**changes):
    return dict(title='公开资料', body=BODY, final_url=FINAL, truncated=False,
                final_url_redacted=False, request_count=4, connections=2, network_bytes=1800,
                blocked_connections=0, **changes)


class FallbackTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'REVIEW_TODAY_READ_PROVIDER':'exa','REVIEW_TODAY_READ_FALLBACKS':'tavily',
            'REVIEW_TODAY_SEARCH_PROVIDER':'exa','REVIEW_TODAY_SEARCH_FALLBACKS':'tavily',
            'REVIEW_TODAY_BROWSER_FALLBACK':'1'})
        env.start(); self.addCleanup(env.stop)
        state = patch.object(policy, '_states', {})
        state.start(); self.addCleanup(state.stop)
        self.backends = {key:Mock() for key in ('exa','tavily','browser')}
        for backend in self.backends.values():
            backend.read.return_value = ('文档', BODY)
        factory = patch.object(web, '_backend', side_effect=self.backends.get)
        factory.start(); self.addCleanup(factory.stop)

    def test_only_failed_read_uses_browser_and_preserves_provenance(self):
        self.assertEqual(web.read_public_url(URL)[1], BODY)
        self.backends['browser'].read.assert_not_called()
        self.backends['exa'].read.return_value = ('外壳', 'var a=window.x; document.cookie="a"; function(){window.y=2;};')
        self.backends['tavily'].read.side_effect = WebToolError('READ_FAILED')
        self.backends['browser'].read.return_value = PageRead('正文', BODY, details={'reader':'browser','final_url':FINAL})
        events=[]
        with policy.web_round_scope(on_event=events.append) as budget:
            result = web.read_public_url(URL)
        self.assertEqual(result.details['final_url'], FINAL)
        self.assertEqual(budget.calls, 3)
        self.assertEqual(events[-1]['provider'], 'browser')
        self.assertEqual(events[-1]['status'], 'succeeded')
        for backend in self.backends.values():
            backend.search.assert_not_called()

    def test_flag_off_or_local_read_cannot_silently_launch_browser(self):
        with patch.dict(os.environ, {'REVIEW_TODAY_BROWSER_FALLBACK':'0'}):
            self.assertEqual(web.provider_chain('read'), ['exa','tavily'])
        with patch.dict(os.environ, {'REVIEW_TODAY_READ_PROVIDER':'local','REVIEW_TODAY_READ_FALLBACKS':'browser'}):
            self.assertEqual(web.provider_chain('read'), ['local'])
        self.assertEqual(web.provider_chain('search'), ['exa','tavily'])

    def test_cancel_after_remote_failure_never_starts_browser(self):
        handles=[]
        def cancel_then_fail(*args, **kwargs):
            handles[0]()
            raise WebToolError('READ_FAILED')
        self.backends['exa'].read.side_effect = cancel_then_fail
        with self.assertRaisesRegex(WebToolError,'CANCELLED'):
            web.read_public_url(URL, on_cancel_handle=handles.append)
        self.backends['tavily'].read.assert_not_called()
        self.backends['browser'].read.assert_not_called()

    def test_browser_too_late_is_not_admitted_or_counted(self):
        self.backends['exa'].read.side_effect = WebToolError('READ_FAILED')
        self.backends['tavily'].read.side_effect = WebToolError('READ_FAILED')
        with policy.web_round_scope(seconds=1) as budget:
            with self.assertRaisesRegex(WebToolError,'BUDGET_EXHAUSTED'):
                web.read_public_url(URL)
        self.assertEqual(budget.calls,2)
        self.backends['browser'].read.assert_not_called()

    def test_late_or_cancelled_browser_result_never_succeeds(self):
        self.backends['exa'].read.side_effect = WebToolError('READ_FAILED')
        self.backends['tavily'].read.side_effect = WebToolError('READ_FAILED')
        handles=[]; events=[]
        def stale(*args, **kwargs):
            handles[0]()
            return ('迟到正文', BODY)
        self.backends['browser'].read.side_effect=stale
        with policy.web_round_scope(on_event=events.append):
            with self.assertRaisesRegex(WebToolError,'CANCELLED'):
                web.read_public_url(URL,on_cancel_handle=handles.append)
        self.assertFalse(any(v['status']=='succeeded' for v in events))

    def test_remaining_run_deadline_caps_browser_even_with_full_web_budget(self):
        self.backends['exa'].read.side_effect = WebToolError('READ_FAILED')
        self.backends['tavily'].read.side_effect = WebToolError('READ_FAILED')
        with policy.web_round_scope(seconds=60,deadline=time.monotonic()+1) as budget:
            with self.assertRaisesRegex(WebToolError,'BUDGET_EXHAUSTED'):
                web.read_public_url(URL)
        self.assertEqual(budget.calls,2)
        self.backends['browser'].read.assert_not_called()

    def test_expired_run_never_starts_a_provider(self):
        with policy.web_round_scope(deadline=time.monotonic()-1) as budget:
            with self.assertRaisesRegex(WebToolError,'BUDGET_EXHAUSTED'):
                web.read_public_url(URL)
        self.assertEqual(budget.calls,0)
        self.backends['exa'].read.assert_not_called()


class NetworkTests(unittest.TestCase):
    def test_private_mixed_reserved_and_empty_dns_never_connect(self):
        for addresses in ([],['127.0.0.1'],['10.1.2.3'],['169.254.169.254'],['::1'],
                          ['93.184.215.14','192.168.1.1'],['198.18.0.1'],['::ffff:127.0.0.1']):
            with self.subTest(addresses=addresses), self.assertRaises(ValueError):
                network.public_addresses(addresses)

    def test_private_dns_cannot_use_doh_to_escape_block(self):
        address = [(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.1',443))]
        with patch.object(network.socket,'getaddrinfo',return_value=address), patch.object(network.httpx,'Client') as http:
            with self.assertRaises(ValueError):
                network.resolve_public('docs.example.com',time.monotonic()+5)
            http.assert_not_called()

    def test_fake_ip_uses_doh_domain_only_and_rejects_private_response(self):
        address = [(socket.AF_INET,socket.SOCK_STREAM,6,'',('198.18.0.15',443))]
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(200,json={'Status':0,'Answer':[{'type':1,'data':'127.0.0.1'}]})
        actual_client=httpx.Client
        with patch.object(network.socket,'getaddrinfo',return_value=address), patch.object(network.httpx,'Client',
                side_effect=lambda **kwargs:actual_client(transport=httpx.MockTransport(handler))):
            with self.assertRaises(ValueError):
                network.resolve_public('docs.example.com',time.monotonic()+5)
        self.assertEqual(dict(calls[0].url.params),{'name':'docs.example.com','type':'A'})
        self.assertNotIn('authorization',calls[0].headers)

    def test_proxy_pins_ip_and_checks_connected_peer_again(self):
        resolver=Mock(return_value=['93.184.215.14'])
        with network.PublicProxy(5,resolver=resolver) as proxy:
            for peer, succeeds in [('93.184.215.14',True),('127.0.0.1',False)]:
                connection=Mock(); connection.getpeername.return_value=(peer,443)
                with patch.object(network.socket,'socket',return_value=connection):
                    if succeeds:
                        proxy.connect('docs.example.com',443)
                    else:
                        with self.assertRaises(ValueError):proxy.connect('docs.example.com',443)
                connection.connect.assert_called_once_with(('93.184.215.14',443))
        resolver.assert_called_once()

    def test_proxy_authentication_and_real_private_connect_are_rejected(self):
        with network.PublicProxy(5) as proxy:
            for auth, status in [('',b'407'),(proxy.authorization,b'403')]:
                with socket.create_connection(('127.0.0.1',proxy.server.server_port),timeout=2) as sock:
                    sock.sendall(('CONNECT 127.0.0.1:80 HTTP/1.1\r\nHost: 127.0.0.1:80\r\n'
                                  + ('Proxy-Authorization: '+auth+'\r\n' if auth else '')+'\r\n').encode())
                    self.assertIn(status,sock.recv(2048).split(b'\r\n')[0])

    def test_generated_nonce_is_loaded_but_not_exported(self):
        url = URL+'?_security_check=1_1790397093871'
        navigation_url(url)
        with self.assertRaisesRegex(ValueError,'PRIVATE_URL'):web.public_service_url(url)
        self.assertEqual(source_location(url),(URL,True))
        for url in ('file:///etc/passwd','http://localhost/','http://127.0.0.1/','https://u:p@example.com/'):
            with self.subTest(url=url),self.assertRaises(ValueError):navigation_url(url)
        self.assertFalse(access_page('本文讲解验证码的工作原理，以及登录状态如何保存在 Cookie 中。'))
        self.assertTrue(access_page('请先登录，登录后查看完整内容。'))
        self.assertTrue(access_page('安全验证\n当前 IP 地址可能存在异常访问行为，完成验证后即可正常使用。\n为了您的账户安全，请完成以下验证'))


class WorkerTests(unittest.TestCase):
    def test_result_schema_origin_and_readability_all_required(self):
        good=response()
        result=reader.validate_result(good,requested_url=URL,limit=20000)
        self.assertEqual(result.details['requested_url'],URL)
        for change in ({'body':''},{'body':'var a=window.x; document.cookie="a"; function(){window.y=2;};'},
                       {'final_url':'http://127.0.0.1/secret'},{'network_bytes':True},{'truncated':'false'},
                       {'error':[]},{'error':'SECRET_PROVIDER_TEXT'}):
            with self.subTest(change=change),self.assertRaises(WebToolError) as error:
                reader.validate_result(dict(good,**change),requested_url=URL,limit=20000)
            self.assertNotIn('SECRET',str(error.exception))

    def test_clean_environment_does_not_export_keys_or_browser_profiles(self):
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'model-secret','EXA_API_KEY':'web-secret',
            'TYPESAFE_API_KEY':'jev-secret','HTTP_PROXY':'https://u:p@proxy.invalid','PYTHONPATH':'private'}):
            env=reader.worker_environment('/tmp/isolated-browser-test')
        self.assertNotIn('secret',json.dumps(env))
        self.assertNotIn('HTTP_PROXY',env)
        self.assertNotIn('PYTHONPATH',env)
        self.assertEqual(env['TMPDIR'],'/tmp/isolated-browser-test')

    def test_cancel_stops_real_worker_process_and_cleans_directory(self):
        actual_popen=subprocess.Popen; started=threading.Event(); handles=[]; processes=[]; errors=[]; directories=[]
        def spawn(args,**kwargs):
            directories.append(kwargs['env']['TMPDIR'])
            child=actual_popen([sys.executable,'-c','import time; time.sleep(30)'],**kwargs)
            processes.append(child); started.set(); return child
        def read():
            try: reader.BrowserBackend().read(URL,limit=20000,on_cancel_handle=handles.append)
            except WebToolError as error:errors.append(error.code)
        with patch.object(reader.subprocess,'Popen',side_effect=spawn), patch.object(reader.BrowserBackend,'__init__',return_value=None):
            thread=threading.Thread(target=read);thread.start()
            self.assertTrue(started.wait(2));handles[0]();thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors,['RT.WEB.CANCELLED'])
        self.assertIsNotNone(processes[0].poll())
        self.assertFalse(Path(directories[0]).exists())

    def test_pre_cancel_and_invalid_url_do_not_spawn(self):
        with patch.object(reader.subprocess,'Popen') as process, patch.object(reader.BrowserBackend,'__init__',return_value=None):
            with self.assertRaisesRegex(WebToolError,'CANCELLED'):
                reader.BrowserBackend().read(URL,limit=20000,on_cancel_handle=lambda cancel:cancel())
            with self.assertRaises(ValueError):reader.BrowserBackend().read('http://127.0.0.1/',limit=20000)
            process.assert_not_called()


@unittest.skipUnless(os.getenv('REVIEW_TODAY_TEST_BROWSER') == '1', 'opt-in installed Chrome; no external page requests')
class ActualBrowserTests(unittest.TestCase):
    """Run the actual DOM/script engine with fixture HTML and all sockets blocked.

    No production test bypass is introduced: test fulfillment substitutes the
    transport only after the normal page origin/operation checks have run.
    """
    def render(self, pages, *, seconds=8):
        from playwright.async_api import Route
        from agent_service import browser_render
        attempts=[]
        async def fixture(route, **kwargs):
            attempts.append(route.request.url)
            value=pages.get(route.request.url)
            if isinstance(value, str):
                await route.fulfill(content_type='text/html; charset=utf-8', body=value)
            elif value:
                await route.fulfill(**value)
            else:
                await route.abort()
        def proxy(seconds):
            return network.PublicProxy(seconds, resolver=Mock(side_effect=ValueError('blocked in fixture')))
        with patch.object(Route,'continue_',fixture), patch.object(browser_render,'PublicProxy',side_effect=proxy):
            result=asyncio.run(browser_render.run(dict(url=URL,limit=20000,seconds=seconds)))
        return result,attempts

    def test_delayed_dom_after_redirect_retains_actual_title_body_and_final_url(self):
        html='<title>动态岗位</title><body><main id="main">加载中</main><script>setTimeout(()=>document.getElementById("main").textContent='+json.dumps(BODY)+',500)</script></body>'
        result,attempts=self.render({URL:'<script>location.replace('+json.dumps(FINAL)+')</script>',FINAL:html})
        self.assertEqual(result.get('body'),BODY)
        self.assertEqual(result['title'],'动态岗位')
        self.assertEqual(result['final_url'],FINAL)
        self.assertIn(FINAL,attempts)

    def test_visible_verification_gate_is_not_a_successful_body(self):
        result,_=self.render({URL:'<title>安全验证</title><body>当前 IP 地址可能存在异常访问行为，完成验证后即可正常使用。为了您的账户安全，请完成以下验证。</body>'})
        self.assertEqual(result,{'error':'BROWSER_ACCESS_REQUIRED'})

    def test_private_frame_and_local_navigation_never_reach_transport(self):
        result,attempts=self.render({URL:'<body><iframe src="http://127.0.0.1/secret"></iframe><script>setTimeout(()=>location.href="http://localhost/secret",100)</script></body>'})
        self.assertIn(result.get('error'),{'BROWSER_READ_FAILED','BROWSER_ADDRESS_BLOCKED'})
        self.assertEqual(attempts,[URL])

    def test_permanently_empty_shell_times_out_without_success(self):
        result,_=self.render({URL:'<title>未就绪</title><body><div id="root"></div></body>'},seconds=4)
        self.assertEqual(result,{'error':'BROWSER_TIMEOUT'})


if __name__=='__main__':unittest.main()
