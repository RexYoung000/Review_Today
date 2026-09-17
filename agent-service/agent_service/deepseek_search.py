"""DeepSeek-hosted search via Anthropic Messages; no provider prose as evidence."""
import json
import ssl
from urllib.parse import urlsplit

import httpx

from agent_service.config import CA_BUNDLE, openai_key
from agent_service.execution_policy import budget_scope

ENDPOINT = "https://api.deepseek.com/anthropic/v1/messages"
MAX_USES = 2


def _client():
    return httpx.Client(verify=ssl.create_default_context(cafile=CA_BUNDLE), follow_redirects=False)


def _result_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def search_results(payload):
    """Allowlist tool results, dropping thinking, encrypted content and text URLs."""
    from agent_service.openai_client import ModelCallError
    blocks = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(blocks, list):
        raise ModelCallError("PROTOCOL", "missing search content")
    calls = {b["id"] for b in blocks if isinstance(b, dict) and b.get("type") == "server_tool_use"
             and b.get("name") == "web_search" and isinstance(b.get("id"), str) and b["id"]}
    if not calls:
        raise ModelCallError("UNSUPPORTED", "provider did not execute web search")
    results, seen, paired, errors = [], set(), set(), set()
    completed_lists = 0
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
            continue
        call_id = block.get("tool_use_id")
        if not isinstance(call_id, str) or call_id not in calls or call_id in paired:
            continue
        paired.add(call_id)
        content = block.get("content")
        if isinstance(content, dict) and content.get("type") == "web_search_tool_result_error":
            code = content.get("error_code")
            errors.add(code if isinstance(code, str) and code in {"max_uses_exceeded", "too_many_requests", "query_too_long", "invalid_input", "unavailable"} else "tool_error")
        elif isinstance(content, list):
            completed_lists += 1
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "web_search_result":
                    continue
                url = _result_url(item.get("url"))
                if url and url not in seen:
                    seen.add(url)
                    title = item.get("title")
                    results.append({"url": url, "title": title[:300] if isinstance(title, str) else url})
            if content and not any(isinstance(i, dict) and i.get("type") == "web_search_result" and _result_url(i.get("url")) for i in content):
                errors.add("invalid_results")
        else:
            errors.add("invalid_results")
    if not results:
        if errors:
            code = "SEARCH_LIMIT" if errors == {"max_uses_exceeded"} else "SEARCH_FAILED"
            raise ModelCallError(code, "web search tool returned an error")
        if not completed_lists or calls != paired:
            raise ModelCallError("INCOMPLETE", "search result missing")
    # A tool-use stop or a capped extra search does not invalidate completed
    # results. We need URLs for our own fetch/assessment, not a provider summary.
    return json.dumps({"protocol": "anthropic_messages", "results": results[:12],
                       "partial": bool(errors or calls != paired), "errors": sorted(errors)}, ensure_ascii=False)


def web_search_text(query, *, model, reasoning_effort=None, on_cancel_handle=None):
    from agent_service.openai_client import ModelCallError
    key = openai_key()
    if not key:
        raise RuntimeError("RT.CAPTURE.NO_KEY")
    with budget_scope() as budget:
        with _client() as client:
            budget.register(client.close)
            if on_cancel_handle:
                on_cancel_handle(client.close)
            body = dict(model=model, max_tokens=4096,
                        system="Execute web_search for this public query. Use at most two searches. Do not invent URLs or answer from memory. Search results will be read and assessed separately; no lengthy answer is needed.",
                        messages=[{"role": "user", "content": query}],
                        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_USES}],
                        thinking={"type": "enabled" if reasoning_effort == "high" else "disabled"})
            if reasoning_effort == "high":
                body["output_config"] = {"effort": "high"}
            try:
                response = client.post(ENDPOINT, headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                                       json=body, timeout=budget.take())
                budget.remaining()
                if response.status_code != 200:
                    raise ModelCallError("PROVIDER", f"HTTP {response.status_code}")
                try:
                    payload = response.json()
                except ValueError:
                    raise ModelCallError("PROTOCOL", "invalid search response") from None
                result = search_results(payload)
                budget.remaining()
                return result
            except httpx.TimeoutException:
                raise ModelCallError("TIMEOUT") from None
            except httpx.TransportError:
                raise ModelCallError("CONNECTION") from None
