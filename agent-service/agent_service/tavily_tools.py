"""Optional direct HTTP backend. Disabled until explicitly configured."""
import httpx
from agent_service.call_errors import WebToolError
from agent_service.certs import ssl_context


def _client():
    return httpx.Client(verify=ssl_context(), follow_redirects=False)


class TavilyBackend:
    name = 'tavily'

    def __init__(self, key, *, keyless=False):
        if not key and not keyless:
            raise WebToolError('NO_KEY')
        self.key = key

    def _post(self, endpoint, body, on_cancel_handle):
        from agent_service.web_http import request_json
        import uuid
        headers = ({'Authorization': 'Bearer ' + self.key} if self.key else
                   {'X-Tavily-Access-Mode': 'keyless', 'X-Client-Source': 'review-today',
                    'X-Session-Id': str(uuid.uuid4())})
        payload = request_json(_client, 'POST', 'https://api.tavily.com/' + endpoint,
                               headers=headers, body=body, on_cancel_handle=on_cancel_handle)
        if not isinstance(payload.get('results'), list):
            # Keyless cap envelopes may be successful HTTP responses, never evidence.
            error = payload.get('error')
            if isinstance(error, dict) and isinstance(error.get('code'), str):
                code = error['code'].lower()
                kind = 'RATE_LIMIT' if any(word in code for word in ('limit', 'quota', 'cap', 'credit')) else 'AUTH_REQUIRED' if any(word in code for word in ('auth', 'key')) else 'TOOL_FAILED'
                failure = WebToolError(kind)
                retry = error.get('retry_after_seconds')
                if isinstance(retry, (int, float)) and 0 < retry < float('inf'):
                    failure.retry_after = retry
                raise failure
            if payload.get('status') in {'rate_limited', 'limit_reached'}:
                raise WebToolError('RATE_LIMIT')
            raise WebToolError('PROTOCOL')
        return payload

    def search(self, query, *, on_cancel_handle=None):
        from agent_service.web_tools import SearchResult, public_service_url
        import re
        domains = list(dict.fromkeys(re.findall(r'\bsite:([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', query)))[:4]
        payload = self._post('search', dict(query=query, search_depth='basic', max_results=5,
                            topic='general', auto_parameters=False, include_answer=False,
                            include_raw_content=False, include_images=False,
                            **({'include_domains': domains} if domains else {})), on_cancel_handle)
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
