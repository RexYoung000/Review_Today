"""Harness-owned search/read contracts. No model client, prompt or model selector."""
import json
import os
from pathlib import Path
from typing import Protocol
from dataclasses import asdict, dataclass

from dotenv import load_dotenv
from agent_service.call_errors import WebToolError
from agent_service.execution_policy import budget_scope
from agent_service.web_privacy import safe_public_query, require_public_query, require_public_url

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
    if provider == 'exa':
        from agent_service.exa_tools import ExaBackend
        return ExaBackend(os.getenv('EXA_API_KEY', '').strip())
    if provider == 'tavily':
        from agent_service.tavily_tools import TavilyBackend
        return TavilyBackend(os.getenv('TAVILY_API_KEY', '').strip(), keyless=os.getenv('REVIEW_TODAY_TAVILY_KEYLESS') == '1')
    if provider == 'brave':
        from agent_service.brave_tools import BraveBackend
        return BraveBackend(os.getenv('BRAVE_API_KEY', '').strip())
    raise WebToolError('NOT_CONFIGURED' if provider == 'none' else 'UNSUPPORTED')


def provider_chain(operation):
    primary = search_provider() if operation == 'search' else read_provider()
    fallback = os.getenv('REVIEW_TODAY_' + operation.upper() + '_FALLBACKS', '')
    providers = list(dict.fromkeys([primary] + [p.strip() for p in fallback.split(',') if p.strip()]))
    allowed = {'exa', 'tavily', 'brave'} if operation == 'search' else {'exa', 'tavily'}
    # 'none' and local-only mode cannot silently enable a remote provider.
    return providers if primary in allowed else [primary]


def _operation_backend(provider, operation):
    if operation == 'read' and provider not in {'exa', 'tavily'}:
        raise WebToolError('UNSUPPORTED')
    return _backend(provider)


def _capability(operation):
    providers = provider_chain(operation)
    configured = []
    for provider in providers:
        try:
            if provider != 'local': _operation_backend(provider, operation)
            configured.append(dict(provider=provider, status='unverified'))
        except WebToolError as exc:
            configured.append(dict(provider=provider, status='unavailable', reason=exc.code))
    available = any(p['status'] == 'unverified' for p in configured)
    result = dict(status='unverified' if available else 'unavailable', provider=providers[0],
                  reason=('requires_search_result' if operation == 'search' else 'requires_public_page_read')
                         if available else configured[0]['reason'])
    if operation == 'search': result['protocol'] = PROTOCOL
    if len(providers) > 1: result['providers'] = configured
    return result


def web_search_capability():
    return _capability('search')


def web_read_capability():
    return _capability('read')


def web_context_capability():
    provider = os.getenv('REVIEW_TODAY_CONTEXT_PROVIDER', 'none')
    try:
        if provider != 'brave': raise WebToolError('NOT_CONFIGURED')
        _backend(provider)
    except WebToolError as error:
        return dict(provider=provider, status='unavailable', reason=error.code)
    return dict(provider=provider, status='unverified', reason='requires_extracted_chunks', content_kind='extracted_chunks')


def web_search_text(query: str, *, on_cancel_handle=None) -> str:
    query = require_public_query(query)
    chain = provider_chain('search')
    if len(chain) == 1:
        backend = _backend(chain[0])
        with budget_scope():
            results = backend.search(query, on_cancel_handle=on_cancel_handle)
        provider = backend.name
    else:
        from agent_service.web_resilience import route
        def invoke(provider, backend, register):
            if backend is None: return _backend(provider)
            return backend.search(query, on_cancel_handle=register)
        provider, results = route(chain, 'search', invoke, on_cancel_handle=on_cancel_handle)
    return json.dumps(dict(protocol=PROTOCOL, provider=provider,
                           results=[asdict(r) for r in results]), ensure_ascii=False)


def read_public_url(url: str, limit: int = 20000, *, on_cancel_handle=None) -> tuple[str, str]:
    require_public_url(url)
    chain = provider_chain('read')
    if chain == ['local']:
        from agent_service.capture.fetch import fetch_public_url
        return fetch_public_url(url, limit=limit)
    public_service_url(url)
    if len(chain) == 1:
        with budget_scope(seconds=30):
            return _operation_backend(chain[0], 'read').read(url, limit=limit, on_cancel_handle=on_cancel_handle)
    from agent_service.web_resilience import route
    def invoke(provider, backend, register):
        if backend is None: return _operation_backend(provider, 'read')
        return backend.read(url, limit=limit, on_cancel_handle=register)
    _, result = route(chain, 'read', invoke, on_cancel_handle=on_cancel_handle)
    return result


def web_context_pages(query, *, on_cancel_handle=None, allowed_domains=()):
    """Query-based evidence recovery, explicitly distinct from reading a URL."""
    if os.getenv('REVIEW_TODAY_CONTEXT_PROVIDER', 'none') != 'brave': return []
    query = require_public_query(query)
    from urllib.parse import urlsplit
    from agent_service.web_resilience import route
    def invoke(provider, backend, register):
        if backend is None: return _backend(provider)
        return backend.context(query, on_cancel_handle=register)
    _, pages = route(['brave'], 'context', invoke, on_cancel_handle=on_cancel_handle)
    return [p for p in pages if not allowed_domains or any(
        (urlsplit(p['url']).hostname or '').lower() == d or
        (urlsplit(p['url']).hostname or '').lower().endswith('.' + d) for d in allowed_domains)]


def public_service_url(url):
    """Remote service eligibility only; local fetch still performs DNS pinning."""
    import ipaddress
    import re
    from urllib.parse import urlsplit
    require_public_url(url)
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
    require_public_url(url)
    if read_provider() == 'local':
        from agent_service.capture.fetch import assert_public_http_url
        return assert_public_http_url(url)
    return public_service_url(url)


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
            public_service_url(url)
            title, body = reader(url)
            if body.strip():
                pages.append(dict(url=url, title=title, content=body[:6000]))
        except (ValueError, OSError, WebToolError):
            continue
    return pages
