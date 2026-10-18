"""Optional standalone DeepSeek Search/Fetch. No model credentials or calls."""
import re
import string

import httpx

from agent_service.call_errors import WebToolError
from agent_service.certs import ssl_context
from agent_service.source_content import PageRead, readable_page

BASE_URL = 'https://api.deepseek.com/v1/tools/'
MARKDOWN_ESCAPE = re.compile(r'\\([' + re.escape(string.punctuation) + r'])')


def _client():
    return httpx.Client(verify=ssl_context(), follow_redirects=False)


class DeepSeekWebBackend:
    name = 'deepseek'

    def __init__(self, key):
        if not key:
            raise WebToolError('NO_KEY')
        self.key = key

    def _post(self, operation, body, on_cancel_handle):
        from agent_service.web_http import request_json
        try:
            return request_json(_client, 'POST', BASE_URL + operation,
                                headers={'Authorization': 'Bearer ' + self.key},
                                body=body, on_cancel_handle=on_cancel_handle)
        except WebToolError as error:
            # Fetch 403 is a page policy refusal, not an invalid account key.
            if operation == 'fetch' and error.diagnostic in {'HTTP 403', 'HTTP 404'}:
                raise WebToolError('READ_FAILED', error.diagnostic) from None
            if error.diagnostic == 'HTTP 401':
                raise WebToolError('AUTH_REQUIRED', error.diagnostic) from None
            if error.diagnostic == 'HTTP 402':
                raise WebToolError('BALANCE_REQUIRED', error.diagnostic) from None
            if error.diagnostic == 'HTTP 408':
                raise WebToolError('TIMEOUT', error.diagnostic) from None
            raise

    def search(self, query, *, on_cancel_handle=None):
        from agent_service.web_tools import SearchResult, require_public_query, public_service_url
        query = require_public_query(query)
        if len(query) > 128:
            # Preserve site/date/negative filters and meaning for the next provider.
            raise WebToolError('UNSUPPORTED', 'query exceeds 128 characters')
        payload = self._post('search', dict(query=query, count=5, need_content=False), on_cancel_handle)
        if not isinstance(payload.get('results'), list):
            raise WebToolError('PROTOCOL')
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
            title = item.get('title')
            summary = item.get('summary')
            if not isinstance(summary, str) or not summary.strip():
                summary = item.get('snippet')
            results.append(SearchResult(url, title[:300] if isinstance(title, str) and title.strip() else url,
                                        summary[:1500] if isinstance(summary, str) else ''))
        return results

    def read(self, url, *, limit, on_cancel_handle=None):
        from agent_service.web_tools import public_service_url
        public_service_url(url)
        payload = self._post('fetch', dict(url=url), on_cancel_handle)
        body, title = payload.get('content'), payload.get('title')
        if not isinstance(body, str) or not body.strip():
            raise WebToolError('READ_FAILED')
        if title is not None and not isinstance(title, str):
            raise WebToolError('PROTOCOL')
        # Gate the readable form as well: escaped script/HTML is still a shell.
        # Keep the original content for provenance and exact source quotations.
        readable_page((MARKDOWN_ESCAPE.sub(r'\1', title or url),
                       MARKDOWN_ESCAPE.sub(r'\1', body[:limit])))
        # The API does not expose a final URL. Do not invent redirect provenance.
        return PageRead(title or url, body[:limit], details=dict(
            provider=self.name, requested_url=url, content_kind='page_text',
            truncated=len(body) > limit))
