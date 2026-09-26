"""Disposable browser worker. Only fixed page-loading/extraction code runs here.

Input and output are bounded JSON over inherited pipes; no model/provider
configuration, browser profile, .env, conversation or credentials are loaded.
"""
import asyncio
import json
import re
import signal
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from agent_service.browser_proxy import PublicProxy
from agent_service.web_privacy import public_service_url

CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

EXTRACT = r"""limit => {
  const body = document.body;
  if (!body) return {text:'', title:document.title, url:location.href, ready:false};
  const all = body.innerText || '';
  const main = document.querySelector('main, article, [role="main"]');
  const focused = main ? (main.innerText || '') : '';
  const text = (focused.length >= 160 && focused.length >= all.length * .35 ? focused : all)
    .replace(/\u00a0/g, ' ').replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  return {text:text.slice(0, limit), truncated:text.length > limit,
    title:document.title.slice(0,300), url:location.href,
    ready:document.readyState !== 'loading'};
}"""


def access_page(text):
    return len(text) < 1400 and bool(re.search(
        r'请(?:先)?登录|登录后(?:查看|继续)|扫码登录|访问过于频繁|滑动.{0,8}验证|'
        r'请输入验证码|完成验证后(?:继续|即可)|请完成以下验证|点击按钮进行验证|'
        r'verify you are human|checking your browser|access denied|sign in to (?:continue|view)', text, re.I))


def navigation_url(url):
    """Page-generated parameters stay in the disposable browser, never logs.

    User input still passes the stricter privacy check before launch. A public
    page can add its own short-lived anti-bot nonce during normal navigation.
    """
    if not isinstance(url, str) or len(url)>8192 or any(ord(c)<32 for c in url):
        raise ValueError('RT.WEB.INVALID_URL')
    parts = urlsplit(url)
    public_service_url(f'{parts.scheme}://{parts.netloc}/')
    return parts


def source_location(url):
    parts = navigation_url(url)
    try:
        public_service_url(url)
        return url, False
    except ValueError as error:
        if str(error) != 'RT.WEB.PRIVATE_URL':
            raise
        # Do not export a site's transient credentials/nonce. The stable path
        # and the separately retained original user URL identify this source.
        public = urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
        public_service_url(public)
        return public, True


async def render(url, limit, seconds):
    from playwright.async_api import async_playwright, Error, TimeoutError as BrowserTimeout
    public_service_url(url)
    started = time.monotonic()
    browser = None
    with PublicProxy(seconds) as proxy:
        async with async_playwright() as runtime:
            try:
                options = dict(headless=True, chromium_sandbox=True, proxy=proxy.configuration,
                               timeout=min(10000, int(seconds * 1000)),
                               args=['--disable-quic', '--proxy-bypass-list=<-loopback>',
                                     '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
                                     '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
                if CHROME.is_file():
                    options['channel'] = 'chrome'
                else:
                    options['channel'] = 'chromium'
                browser = await runtime.chromium.launch(**options)
                context = await browser.new_context(accept_downloads=False, service_workers='block',
                    permissions=[], locale='zh-CN', viewport={'width':1280,'height':900})
                await context.route_web_socket('**/*', lambda ws: ws.close())
                page = await context.new_page()
                page.on('dialog', lambda dialog: dialog.dismiss())
                page.on('download', lambda download: download.cancel())
                context.on('page', lambda extra: extra.close())
                pending = set()
                request_count = 0
                navigation_count = 0
                last_status = 0

                async def route_request(route):
                    nonlocal request_count, navigation_count
                    request = route.request
                    request_count += 1
                    try:
                        parts = urlsplit(request.url)
                        public_service_url(f'{parts.scheme}://{parts.netloc}/')
                        if request_count > 180 or request.resource_type in {'image', 'media', 'font'}:
                            raise ValueError()
                        if request.is_navigation_request():
                            navigation_url(request.url)
                            if request.frame.page != page or request.frame.parent_frame is not None:
                                raise ValueError()
                            navigation_count += 1
                            if navigation_count > 8:
                                raise ValueError()
                        if request.resource_type in {'document','script','xhr','fetch'}:
                            pending.add(request)
                        await route.continue_()
                    except (ValueError, Error):
                        await route.abort()

                await context.route('**/*', route_request)
                page.on('requestfinished', lambda request: pending.discard(request))
                page.on('requestfailed', lambda request: pending.discard(request))

                def response_status(response):
                    nonlocal last_status
                    if response.request.is_navigation_request() and response.frame == page.main_frame:
                        last_status = response.status
                page.on('response', response_status)
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=min(12000, int(seconds*1000)))
                except BrowserTimeout:
                    pass  # DOM may already be useful despite a slow ancillary load.
                except Error:
                    return dict(error='BROWSER_READ_FAILED')
                snapshot = {}
                signature = None
                stable_since = time.monotonic()
                while time.monotonic() - started < seconds - 1:
                    try:
                        snapshot = await page.evaluate(EXTRACT, limit)
                        # Normal navigation can briefly clear the document. A
                        # browser error page is a load failure, not a private URL.
                        if snapshot.get('url') == 'about:blank':
                            await asyncio.sleep(.2)
                            continue
                        if snapshot.get('url', '').startswith('chrome-error:'):
                            return dict(error='BROWSER_READ_FAILED')
                        navigation_url(snapshot.get('url', ''))
                    except ValueError:
                        return dict(error='BROWSER_ADDRESS_BLOCKED')
                    except Error:
                        await asyncio.sleep(.2)
                        continue
                    text = snapshot.get('text', '').strip()
                    current = (snapshot.get('url'), text)
                    if current != signature:
                        signature, stable_since = current, time.monotonic()
                    # A visible access gate is conclusive even if its telemetry
                    # or challenge requests are still running. Do not interact.
                    if (snapshot.get('ready') and time.monotonic()-stable_since >= 1.2
                            and (access_page(text) or last_status in {401,403,429})):
                        return dict(error='BROWSER_ACCESS_REQUIRED')
                    if (snapshot.get('ready') and not pending and time.monotonic()-stable_since >= 1.2
                            and time.monotonic()-started >= 2):
                        if last_status >= 400:
                            return dict(error='BROWSER_READ_FAILED')
                        if len(text) >= 80:
                            final_url, redacted = source_location(snapshot['url'])
                            return dict(title=snapshot['title'], body=text, final_url=final_url, final_url_redacted=redacted,
                                truncated=bool(snapshot.get('truncated')), request_count=request_count,
                                connections=proxy.connections, network_bytes=proxy.bytes, blocked_connections=proxy.blocked)
                    await asyncio.sleep(.2)
                return dict(error='BROWSER_ACCESS_REQUIRED' if access_page(snapshot.get('text','')) else 'BROWSER_TIMEOUT')
            finally:
                if browser is not None:
                    try:
                        await asyncio.wait_for(browser.close(), timeout=1.5)
                    except (Error, asyncio.TimeoutError):
                        pass


async def run(request):
    seconds = max(.1, min(24, float(request['seconds'])))
    task = asyncio.create_task(render(request['url'], max(100, min(20000, int(request['limit']))), seconds))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        return await asyncio.wait_for(task, timeout=seconds)
    except asyncio.CancelledError:
        return dict(error='CANCELLED')
    except asyncio.TimeoutError:
        return dict(error='BROWSER_TIMEOUT')


def main():
    try:
        raw = sys.stdin.buffer.readline(16384)
        request = json.loads(raw)
        result = asyncio.run(run(request))
    except (ModuleNotFoundError, ImportError):
        result = dict(error='BROWSER_UNAVAILABLE')
    except Exception:
        result = dict(error='BROWSER_READ_FAILED')
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == '__main__':
    main()
