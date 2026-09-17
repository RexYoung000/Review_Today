"""Bounded direct JSON transport shared by independent web providers."""
import json
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from agent_service.call_errors import WebToolError
from agent_service.execution_policy import budget_scope


def response_error(response):
    error = WebToolError('RATE_LIMIT' if response.status_code == 429 else 'PROVIDER', f'HTTP {response.status_code}')
    raw = response.headers.get('Retry-After', '')
    try:
        seconds = float(raw)
    except ValueError:
        try: seconds = (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError): seconds = 0
    if seconds > 0 and seconds < float('inf'):
        error.retry_after = seconds
    return error


def request_json(client_factory, method, url, *, headers, body, on_cancel_handle=None):
    cancelled = threading.Event()
    with budget_scope(seconds=30) as budget, client_factory() as client:
        def cancel():
            cancelled.set()
            client.close()
        budget.register(client.close)
        if on_cancel_handle: on_cancel_handle(cancel)
        def check():
            if cancelled.is_set(): raise WebToolError('CANCELLED')
            return budget.remaining()
        try:
            check()
            timeout = min(30, budget.take())
            options = {'params': body} if method == 'GET' else {'json': body}
            with client.stream(method, url, headers=headers, timeout=timeout, **options) as response:
                if response.status_code != 200: raise response_error(response)
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    check()
                    size += len(chunk)
                    if size > 1_000_000: raise WebToolError('PROTOCOL', 'response too large')
                    chunks.append(chunk)
                check()
                try: payload = json.loads(b''.join(chunks))
                except (ValueError, UnicodeError): raise WebToolError('PROTOCOL') from None
                if not isinstance(payload, dict): raise WebToolError('PROTOCOL')
                return payload
        except httpx.TimeoutException:
            raise WebToolError('CANCELLED' if cancelled.is_set() else 'TIMEOUT') from None
        except (httpx.TransportError, RuntimeError) as error:
            if cancelled.is_set(): raise WebToolError('CANCELLED') from None
            if isinstance(error, RuntimeError): raise
            raise WebToolError('CONNECTION') from None
