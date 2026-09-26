"""Bounded, cancellable last-resort public page rendering in a clean process."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

from agent_service.call_errors import WebToolError
from agent_service.execution_policy import budget_scope
from agent_service.source_content import PageRead, readable_page
from agent_service.web_privacy import public_service_url

MAX_SECONDS = 25
ERRORS = {'BROWSER_UNAVAILABLE', 'BROWSER_READ_FAILED', 'BROWSER_ACCESS_REQUIRED',
          'BROWSER_ADDRESS_BLOCKED', 'BROWSER_TIMEOUT', 'CANCELLED'}


def worker_environment(directory):
    env = {key: os.environ[key] for key in ('HOME','PATH','LANG','USER','LOGNAME','SSL_CERT_FILE') if key in os.environ}
    env.update(PYTHONUNBUFFERED='1', TMPDIR=directory)
    return env


def validate_result(payload, *, requested_url, limit):
    if not isinstance(payload, dict):
        raise WebToolError('BROWSER_READ_FAILED')
    if 'error' in payload:
        code = payload['error']
        raise WebToolError(code if isinstance(code, str) and code in ERRORS else 'BROWSER_READ_FAILED')
    title, body, final_url = (payload.get(key) for key in ('title','body','final_url'))
    if not all(isinstance(v, str) for v in (title,body,final_url)):
        raise WebToolError('BROWSER_READ_FAILED')
    if not all(isinstance(payload.get(key), bool) for key in ('truncated','final_url_redacted')):
        raise WebToolError('BROWSER_READ_FAILED')
    try:
        public_service_url(final_url)
    except ValueError:
        raise WebToolError('BROWSER_ADDRESS_BLOCKED') from None
    details = dict(reader='browser', requested_url=requested_url, final_url=final_url,
                   final_url_redacted=bool(payload.get('final_url_redacted')),
                   truncated=bool(payload.get('truncated')) or len(body)>limit)
    for key in ('request_count','connections','network_bytes','blocked_connections'):
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 50_000_000:
            raise WebToolError('BROWSER_READ_FAILED')
        details[key] = value
    return readable_page(PageRead(title[:300], body[:limit], details=details))


class BrowserBackend:
    name = 'browser'

    def __init__(self):
        if importlib.util.find_spec('playwright') is None:
            raise WebToolError('BROWSER_UNAVAILABLE')
        chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        caches = [Path.home()/'Library/Caches/ms-playwright', Path.home()/'.cache/ms-playwright']
        if not chrome.is_file() and not any(list(cache.glob('chromium-*')) for cache in caches):
            raise WebToolError('BROWSER_UNAVAILABLE')

    def read(self, url, *, limit, on_cancel_handle=None):
        public_service_url(url)
        cancelled = threading.Event()
        process = None

        def cancel():
            cancelled.set()
            if process and process.poll() is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass

        if on_cancel_handle:
            on_cancel_handle(cancel)
        with budget_scope(seconds=MAX_SECONDS) as budget, tempfile.TemporaryDirectory(prefix='review-page-') as directory:
            if cancelled.is_set():
                raise WebToolError('CANCELLED')
            seconds = min(MAX_SECONDS, budget.take())
            if seconds < 2:
                raise WebToolError('BUDGET_EXHAUSTED')
            deadline = time.monotonic() + seconds
            with tempfile.TemporaryFile() as output:
                try:
                    process = subprocess.Popen([sys.executable, '-m', 'agent_service.browser_render'],
                        cwd=Path(__file__).resolve().parent.parent, env=worker_environment(directory),
                        stdin=subprocess.PIPE, stdout=output, stderr=subprocess.DEVNULL, start_new_session=True)
                except OSError:
                    raise WebToolError('BROWSER_UNAVAILABLE') from None
                try:
                    if cancelled.is_set():
                        cancel()
                        raise WebToolError('CANCELLED')
                    process.stdin.write((json.dumps(dict(url=url, limit=limit, seconds=seconds-1))+'\n').encode())
                    process.stdin.close()
                    while process.poll() is None:
                        if cancelled.wait(.05):
                            raise WebToolError('CANCELLED')
                        if time.monotonic() >= deadline:
                            raise WebToolError('BROWSER_TIMEOUT')
                        if os.fstat(output.fileno()).st_size > 500_000:
                            raise WebToolError('BROWSER_READ_FAILED')
                    if cancelled.is_set():
                        raise WebToolError('CANCELLED')
                    if time.monotonic() >= deadline:
                        raise WebToolError('BROWSER_TIMEOUT')
                    output.seek(0)
                    raw = output.read(500_001)
                    if process.returncode or len(raw)>500_000:
                        raise WebToolError('BROWSER_READ_FAILED')
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise WebToolError('BROWSER_READ_FAILED') from None
                    return validate_result(payload, requested_url=url, limit=limit)
                except OSError:
                    raise WebToolError('CANCELLED' if cancelled.is_set() else 'BROWSER_READ_FAILED') from None
                finally:
                    if process.poll() is None:
                        cancel()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            process.wait(timeout=1)
