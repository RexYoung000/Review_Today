"""Brave search and query-based extracted chunks; never a URL fetch adapter."""
import httpx
from agent_service.call_errors import WebToolError
from agent_service.certs import ssl_context
from agent_service.web_http import request_json


def _client():
    return httpx.Client(verify=ssl_context(), follow_redirects=False)


class BraveBackend:
    name = 'brave'

    def __init__(self, key):
        if not key: raise WebToolError('NO_KEY')
        self.key = key

    def _get(self, path, body, on_cancel_handle):
        return request_json(_client, 'GET', 'https://api.search.brave.com/res/v1/' + path,
                            headers={'X-Subscription-Token': self.key, 'Accept': 'application/json'},
                            body=body, on_cancel_handle=on_cancel_handle)

    def search(self, query, *, on_cancel_handle=None):
        from agent_service.web_tools import SearchResult, public_service_url
        payload = self._get('web/search', dict(q=query, count=5), on_cancel_handle)
        if 'web' not in payload and payload.get('type') != 'search':
            raise WebToolError('PROTOCOL')
        web = payload.get('web', {})
        items = web.get('results', []) if isinstance(web, dict) else None
        if not isinstance(items, list): raise WebToolError('PROTOCOL')
        results, seen = [], set()
        for item in items[:5]:
            if not isinstance(item, dict): continue
            url = item.get('url')
            try: public_service_url(url)
            except ValueError: continue
            if url in seen: continue
            seen.add(url)
            results.append(SearchResult(url, str(item.get('title') or url)[:300],
                                        str(item.get('description') or '')[:1500]))
        return results

    def context(self, query, *, on_cancel_handle=None):
        from agent_service.web_tools import public_service_url
        payload = self._get('llm/context', dict(q=query, count=5, maximum_number_of_urls=3,
            maximum_number_of_tokens=4096, maximum_number_of_tokens_per_url=2048,
            maximum_number_of_snippets=12, context_threshold_mode='strict'), on_cancel_handle)
        grounding = payload.get('grounding')
        if not isinstance(grounding, dict) or not isinstance(grounding.get('generic'), list):
            raise WebToolError('PROTOCOL')
        pages, seen = [], set()
        for item in grounding['generic']:
            if not isinstance(item, dict): continue
            url, chunks = item.get('url'), item.get('snippets')
            try: public_service_url(url)
            except ValueError: continue
            if url in seen or not isinstance(chunks, list): continue
            body = '\n\n'.join(s for s in chunks if isinstance(s, str) and s.strip())[:10000]
            if not body: continue
            seen.add(url)
            pages.append(dict(url=url, title=str(item.get('title') or url)[:300], content=body,
                              provider='brave', content_kind='extracted_chunks'))
            if len(pages) == 3: break
        return pages
