"""Harness-owned search/read contracts. No model client, prompt or model selector."""
import json
import os
from pathlib import Path
from typing import Protocol
from dataclasses import asdict, dataclass

from dotenv import load_dotenv
from agent_service.call_errors import WebToolError
from agent_service.execution_policy import budget_scope

load_dotenv(Path(__file__).resolve().parent.parent / 'providers' / 'web' / '.env')
PROTOCOL = 'harness_web_tools_v1'


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str = ''


class SearchBackend(Protocol):
    name: str
    def search(self, query: str, *, on_cancel_handle=None) -> list[SearchResult]: ...


class ReadBackend(Protocol):
    name: str
    def read(self, url: str, *, limit: int, on_cancel_handle=None) -> tuple[str, str]: ...


def search_provider():
    return os.getenv('REVIEW_TODAY_SEARCH_PROVIDER', 'none').strip() or 'none'


def read_provider():
    return os.getenv('REVIEW_TODAY_READ_PROVIDER', 'local').strip() or 'local'


def _backend(provider):
    if provider == 'tavily':
        from agent_service.tavily_tools import TavilyBackend
        return TavilyBackend(os.getenv('TAVILY_API_KEY', '').strip())
    raise WebToolError('NOT_CONFIGURED' if provider == 'none' else 'UNSUPPORTED')


def web_search_capability():
    provider = search_provider()
    try:
        _backend(provider)
    except WebToolError as exc:
        return dict(status='unavailable', provider=provider, protocol=PROTOCOL, reason=exc.code)
    return dict(status='unverified', provider=provider, protocol=PROTOCOL, reason='requires_search_result')


def web_read_capability():
    provider = read_provider()
    if provider == 'local':
        return dict(status='unverified', provider=provider, reason='requires_public_page_read')
    try:
        _backend(provider)
    except WebToolError as exc:
        return dict(status='unavailable', provider=provider, reason=exc.code)
    return dict(status='unverified', provider=provider, reason='requires_public_page_read')


def web_search_text(query: str, *, on_cancel_handle=None) -> str:
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise WebToolError('INVALID_QUERY')
    backend = _backend(search_provider())
    with budget_scope():
        results = backend.search(query, on_cancel_handle=on_cancel_handle)
    return json.dumps(dict(protocol=PROTOCOL, provider=backend.name,
                           results=[asdict(r) for r in results]), ensure_ascii=False)


def read_public_url(url: str, limit: int = 20000, *, on_cancel_handle=None) -> tuple[str, str]:
    provider = read_provider()
    if provider == 'local':
        # This reader retains pinned DNS, peer and redirect checks. Remote
        # reading is a separately selected service, never an automatic retry.
        from agent_service.capture.fetch import fetch_public_url
        return fetch_public_url(url, limit=limit)
    backend = _backend(provider)
    with budget_scope(seconds=30):
        return backend.read(url, limit=limit, on_cancel_handle=on_cancel_handle)


def public_service_url(url):
    """Remote service eligibility only; local fetch still performs DNS pinning."""
    import ipaddress
    import re
    from urllib.parse import urlsplit
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError('RT.WEB.INVALID_URL')
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower().rstrip('.')
        if (parsed.scheme not in {'http', 'https'} or not host or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 80, 443)
                or host.endswith(('.local', '.internal', '.localhost', '.test', '.invalid'))
                or '.' not in host or '\\' in url or '%' in host
                or not re.fullmatch(r'[a-z0-9.-]+', host) or host in {'metadata.google.internal'}):
            raise ValueError('RT.WEB.INVALID_URL')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if all(part.isdigit() or part.startswith('0x') for part in host.split('.')):
                raise ValueError('RT.WEB.INVALID_URL')
        else:
            raise ValueError('RT.WEB.INVALID_URL')
    except (ValueError, TypeError):
        raise ValueError('RT.WEB.INVALID_URL') from None
    return url


def assert_readable_url(url):
    if read_provider() == 'local':
        from agent_service.capture.fetch import assert_public_http_url
        return assert_public_http_url(url)
    return public_service_url(url)


def safe_public_query(value):
    import re
    value = value.strip() if isinstance(value, str) else ''
    if not 2 <= len(value) <= 180 or re.search(r"(?:https?://|\bsk-|\bBearer\b|[^\s]+@[^\s]+|\d{7,}|-----BEGIN|(?:密钥|密码)\s*[:：])", value, re.I):
        return ''
    return value


def read_search_evidence(search, *, reader=None):
    """Only fetched bodies qualify as evidence; plain/model prose cannot qualify."""
    reader = reader or read_public_url
    try:
        data = json.loads(search)
        if data.get('protocol') != PROTOCOL or not isinstance(data.get('results'), list):
            return []
    except (ValueError, TypeError, AttributeError):
        return []
    pages, seen = [], set()
    for item in data['results'][:3]:
        if not isinstance(item, dict) or not isinstance(item.get('url'), str):
            continue
        url = item['url']
        if url in seen:
            continue
        seen.add(url)
        try:
            title, body = reader(url)
            if body.strip():
                pages.append(dict(url=url, title=title, content=body[:6000]))
        except (ValueError, OSError, WebToolError):
            continue
    return pages
