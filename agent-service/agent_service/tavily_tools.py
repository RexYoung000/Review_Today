"""Optional direct HTTP backend. Disabled until explicitly configured."""
import httpx
from agent_service.call_errors import WebToolError
from agent_service.certs import ssl_context
from agent_service.execution_policy import budget_scope


def _client():
    return httpx.Client(verify=ssl_context(), follow_redirects=False)


class TavilyBackend:
    name = 'tavily'

    def __init__(self, key):
        if not key:
            raise WebToolError('NO_KEY')
        self.key = key

    def _post(self, endpoint, body, on_cancel_handle):
        with budget_scope(seconds=30) as budget, _client() as client:
            budget.register(client.close)
            if on_cancel_handle:
                on_cancel_handle(client.close)
            try:
                with client.stream('POST', 'https://api.tavily.com/' + endpoint,
                                   headers={'Authorization': 'Bearer ' + self.key},
                                   json=body, timeout=min(30, budget.take())) as response:
                    if response.status_code != 200:
                        raise WebToolError('PROVIDER', f'HTTP {response.status_code}')
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        budget.remaining()
                        size += len(chunk)
                        if size > 1_000_000:
                            raise WebToolError('PROTOCOL', 'response too large')
                        chunks.append(chunk)
                    import json
                    try:
                        payload = json.loads(b''.join(chunks))
                    except (ValueError, UnicodeError):
                        raise WebToolError('PROTOCOL') from None
                    if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
                        raise WebToolError('PROTOCOL')
                    return payload
            except httpx.TimeoutException:
                raise WebToolError('TIMEOUT') from None
            except httpx.TransportError:
                raise WebToolError('CONNECTION') from None

    def search(self, query, *, on_cancel_handle=None):
        from agent_service.web_tools import SearchResult, public_service_url
        payload = self._post('search', dict(query=query, search_depth='basic', max_results=5,
                            topic='general', auto_parameters=False, include_answer=False,
                            include_raw_content=False, include_images=False), on_cancel_handle)
        results, seen = [], set()
        for item in payload['results'][:5]:
            if not isinstance(item, dict):
                continue
            url = item.get('url')
            try:
                public_service_url(url)
            except ValueError:
                continue
            if url in seen:
                continue
            seen.add(url)
            title, snippet = item.get('title'), item.get('content')
            results.append(SearchResult(url, title[:300] if isinstance(title, str) else url,
                                        snippet[:1500] if isinstance(snippet, str) else ''))
        return results

    def read(self, url, *, limit, on_cancel_handle=None):
        from agent_service.web_tools import public_service_url
        public_service_url(url)
        payload = self._post('extract', dict(urls=[url], extract_depth='basic', format='text',
                            include_images=False, timeout=20), on_cancel_handle)
        for item in payload['results']:
            if not isinstance(item, dict) or item.get('url') != url:
                continue
            body = item.get('raw_content')
            if isinstance(body, str) and body.strip():
                return url, body[:limit]
        # HTTP 200 can contain only failed_results. Never promote a snippet.
        raise WebToolError('READ_FAILED')
