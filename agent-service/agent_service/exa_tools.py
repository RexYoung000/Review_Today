"""Bounded client for Exa's two public MCP tools, independent of model APIs.

Only the fixed hosted Streamable HTTP transport is supported. This is not a
plugin runner: server requests, prompts, resources and research are never run.
"""
import json
import re
import threading

import httpx

from agent_service.call_errors import WebToolError
from agent_service.certs import ssl_context
from agent_service.execution_policy import budget_scope

ENDPOINT = 'https://mcp.exa.ai/mcp'
VERSION = '2025-03-26'
MAX_BYTES = 1_000_000


def _client():
    return httpx.Client(verify=ssl_context(), follow_redirects=False)


def _decode(message, request_id):
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
        raise WebToolError('PROTOCOL')
    if message.get('id') != request_id:
        return None  # Never execute notifications or requests from a server.
    if 'error' in message:
        raise WebToolError('PROTOCOL')
    result = message.get('result')
    if not isinstance(result, dict):
        raise WebToolError('PROTOCOL')
    return result


def _tool_text(result):
    blocks = result.get('content')
    if not isinstance(blocks, list):
        raise WebToolError('PROTOCOL')
    text = '\n'.join(b['text'] for b in blocks if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str))
    if result.get('isError'):
        # Classify only. Provider text may contain prompts/URLs; never log it.
        if re.search(r'rate.?limit|too many requests|\b429\b|quota', text, re.I):
            raise WebToolError('RATE_LIMIT')
        if re.search(r'authenticat|unauthorized|\b401\b|\b403\b', text, re.I):
            raise WebToolError('AUTH_REQUIRED')
        raise WebToolError('TOOL_FAILED')
    if not text.strip():
        raise WebToolError('EMPTY')
    return text


class ExaBackend:
    name = 'exa'

    def _call(self, name, arguments, on_cancel_handle):
        if name not in {'web_search_exa', 'web_fetch_exa'}:
            raise WebToolError('UNSUPPORTED')
        cancelled = threading.Event()
        with budget_scope(seconds=30) as budget, _client() as client:
            budget.take()  # One logical tool attempt, including its handshake.
            budget.register(client.close)
            def cancel():
                cancelled.set()
                client.close()
            if on_cancel_handle:
                on_cancel_handle(cancel)
            headers = {'Accept': 'application/json, text/event-stream'}

            def check():
                if cancelled.is_set():
                    raise WebToolError('CANCELLED')
                return min(30, budget.remaining())

            def post(method, params=None, request_id=None):
                body = dict(jsonrpc='2.0', method=method)
                if params is not None: body['params'] = params
                if request_id is not None: body['id'] = request_id
                with client.stream('POST', ENDPOINT, headers=headers, json=body, timeout=check()) as response:
                    if response.status_code == 429:
                        raise WebToolError('RATE_LIMIT', 'HTTP 429')
                    if response.status_code not in (200, 202):
                        raise WebToolError('PROVIDER', f'HTTP {response.status_code}')
                    session = response.headers.get('mcp-session-id')
                    if session:
                        if not re.fullmatch(r'[!-~]{1,512}', session):
                            raise WebToolError('PROTOCOL')
                        headers['Mcp-Session-Id'] = session
                    if request_id is None:
                        if response.status_code != 202: raise WebToolError('PROTOCOL')
                        return None
                    content_type = response.headers.get('content-type', '').split(';')[0].strip()
                    size, chunks, pending, event = 0, [], b'', []
                    for chunk in response.iter_bytes():
                        check()
                        size += len(chunk)
                        if size > MAX_BYTES: raise WebToolError('PROTOCOL', 'response too large')
                        if content_type == 'application/json':
                            chunks.append(chunk)
                        elif content_type == 'text/event-stream':
                            pending += chunk
                            while b'\n' in pending:
                                line, pending = pending.split(b'\n', 1)
                                line = line.rstrip(b'\r')
                                if line.startswith(b'data:'):
                                    event.append(line[5:].lstrip(b' '))
                                elif not line and event:
                                    result = _decode(json.loads(b'\n'.join(event)), request_id)
                                    event = []
                                    if result is not None: return result
                        else:
                            raise WebToolError('PROTOCOL')
                    if content_type == 'application/json':
                        result = _decode(json.loads(b''.join(chunks)), request_id)
                        if result is not None: return result
                    raise WebToolError('INCOMPLETE')
            try:
                hello = post('initialize', dict(protocolVersion=VERSION, capabilities={},
                             clientInfo=dict(name='ReviewToday', version='0.1')), 1)
                if hello.get('protocolVersion') != VERSION or not isinstance(hello.get('capabilities'), dict) or 'tools' not in hello['capabilities']:
                    raise WebToolError('PROTOCOL')
                headers['MCP-Protocol-Version'] = VERSION
                post('notifications/initialized')
                result = post('tools/call', dict(name=name, arguments=arguments), 2)
                check()
                return _tool_text(result)
            except (ValueError, UnicodeError):
                raise WebToolError('PROTOCOL') from None
            except httpx.TimeoutException:
                raise WebToolError('CANCELLED' if cancelled.is_set() else 'TIMEOUT') from None
            except (httpx.TransportError, RuntimeError) as error:
                if cancelled.is_set(): raise WebToolError('CANCELLED') from None
                if isinstance(error, RuntimeError): raise
                raise WebToolError('CONNECTION') from None
            finally:
                # Exa currently runs without session IDs. End a future stateful
                # session when possible, without retrying a completed tool call.
                if 'Mcp-Session-Id' in headers and not client.is_closed:
                    try: client.delete(ENDPOINT, headers=headers, timeout=1)
                    except httpx.HTTPError: pass

    def search(self, query, *, on_cancel_handle=None):
        from agent_service.web_tools import SearchResult, public_service_url
        text = self._call('web_search_exa', dict(query=query, numResults=5), on_cancel_handle)
        if re.fullmatch(r'\s*No (?:search )?results(?: found)?[.!]?\s*', text, re.I):
            return []
        records = re.split(r'\n---\s*\n(?=Title: )', text)
        results, seen = [], set()
        for record in records:
            match = re.match(r'\s*Title: ([^\n]+)\nURL: (https?://[^\s]+)\n(?:Published: [^\n]*\n)?(?:Author: [^\n]*\n)?(?:Highlights|Text|Content):\n([\s\S]*)', record)
            if not match: raise WebToolError('PROTOCOL', 'unexpected search format')
            title, url, snippet = match.groups()
            try: public_service_url(url)
            except ValueError: continue
            if url not in seen:
                results.append(SearchResult(url, title[:300], snippet[:1500]))
                seen.add(url)
        return results[:5]

    def read(self, url, *, limit, on_cancel_handle=None):
        from agent_service.web_tools import public_service_url
        public_service_url(url)
        text = self._call('web_fetch_exa', dict(urls=[url], maxCharacters=min(limit, 20000)), on_cancel_handle)
        match = re.match(r'\A# ([^\n]+)\nURL: ([^\n]+)\n\n([\s\S]+)\Z', text)
        if not match: raise WebToolError('READ_FAILED')
        title, actual, body = match.groups()
        if actual != url or not body.strip(): raise WebToolError('READ_FAILED')
        return title[:300], body[:limit]
