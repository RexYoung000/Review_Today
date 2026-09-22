import json
import re
from collections.abc import Callable

import jiter
import httpx

from openai import OpenAI, APITimeoutError, APIConnectionError, APIStatusError
from openai.lib._parsing._responses import type_to_text_format_param
from pydantic import BaseModel, ValidationError

from agent_service.config import BASE_URL, MODEL, PROVIDER, MODEL_PROBE_TIMEOUT_SECONDS, MODEL_TIMEOUT_SECONDS, openai_key
from agent_service.execution_policy import budget_scope, current_budget
from agent_service.structured_output import schema_diagnostic
from agent_service.call_errors import ModelCallError


def _client(*, timeout: float = MODEL_TIMEOUT_SECONDS) -> OpenAI:
    key = openai_key()
    if not key:
        raise RuntimeError("RT.CAPTURE.NO_KEY")
    client = OpenAI(api_key=key, timeout=timeout, max_retries=0, **({"base_url": BASE_URL} if BASE_URL else {}))
    if current_budget.get(): current_budget.get().register(client.close)
    return client


def _input(system, user):
    # DeepSeek treats developer messages as user input. Preserve trusted rules.
    if PROVIDER == "deepseek":
        system += ("\n输出必须是一个严格符合本次 text.format JSON Schema 的 JSON 对象。"
                   "不要使用 Markdown 代码围栏，不要在 JSON 之外输出任何文字。"
                   "对用户的回答、解释和 Markdown 排版只能放在结构定义的正文字符串字段内。")
    return [{"role": "system" if PROVIDER == "deepseek" else "developer", "content": system},
            {"role": "user", "content": user}]


def _reasoning(effort):
    # DeepSeek defaults to high; smart must explicitly disable it, not silently
    # inherit a slow provider default. User-selected deep always stays high.
    if PROVIDER == "deepseek":
        return {"reasoning": {"effort": effort or "none"}}
    return {"reasoning": {"effort": effort}} if effort else {}


def _text_format(schema):
    fmt = type_to_text_format_param(schema)
    if PROVIDER != "deepseek":
        return fmt
    root = fmt["schema"]

    def expand(node, stack=frozenset()):
        if isinstance(node, list):
            return [expand(value, stack) for value in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            ref = node["$ref"]
            if not ref.startswith("#/") or ref in stack:
                raise ModelCallError("UNSUPPORTED", "recursive or external schema reference")
            target = root
            try:
                for part in ref[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError):
                raise ModelCallError("UNSUPPORTED", "unresolved schema reference") from None
            # SDK-generated refs contain annotations as siblings, not alternate
            # assertions. Preserve all constraints instead of weakening JSON mode.
            return expand({**target, **{key: value for key, value in node.items() if key != "$ref"}}, stack | {ref})
        return {key: expand(value, stack) for key, value in node.items() if key != "$defs"}

    return {**fmt, "schema": expand(root)}


def parse_model(
    system: str,
    user: str,
    text_format: type[BaseModel],
    *,
    model: str | None = None,
    timeout: float = MODEL_TIMEOUT_SECONDS,
    reasoning_effort: str | None = None,
    max_output_tokens: int | None = None,
    on_partial: Callable[[dict], None] | None = None,
    on_transport: Callable[[str], None] | None = None,
    on_cancel_handle: Callable[[Callable[[], None]], None] | None = None,
    on_usage: Callable[[dict], None] | None = None,
    on_request: Callable[[], None] | None = None,
) -> BaseModel:
    try:
        with budget_scope(timeout) as budget:
            if on_partial is not None:
                result = _stream_model(system, user, text_format, model=model, timeout=timeout,
                                     on_partial=on_partial, on_transport=on_transport, on_cancel_handle=on_cancel_handle,
                                     on_usage=on_usage, on_request=on_request,
                                     reasoning_effort=reasoning_effort, max_output_tokens=max_output_tokens)
            else:
                result = _parse_model(system, user, text_format, model=model, timeout=timeout, on_cancel_handle=on_cancel_handle,
                                on_usage=on_usage, on_request=on_request,
                                reasoning_effort=reasoning_effort, max_output_tokens=max_output_tokens)
            budget.remaining()
            return result
    except ModelCallError:
        raise
    except APITimeoutError as exc:
        raise ModelCallError("TIMEOUT", type(exc).__name__) from None
    except APIConnectionError as exc:
        raise ModelCallError("CONNECTION", type(exc).__name__) from None
    except httpx.TimeoutException as exc:
        raise ModelCallError("TIMEOUT", type(exc).__name__) from None
    except httpx.TransportError as exc:
        raise ModelCallError("CONNECTION", type(exc).__name__) from None
    except APIStatusError as exc:
        raise ModelCallError("PROVIDER", f"HTTP {exc.status_code}", request_id=getattr(exc, "request_id", None)) from None
    except ValidationError as exc:
        raise ModelCallError("SCHEMA", schema_diagnostic(exc)) from None
    except json.JSONDecodeError:
        raise ModelCallError("SCHEMA", "JSONDecodeError") from None



def _validate_output(schema, raw, response):
    try:
        return schema.model_validate_json(raw)
    except ValidationError as exc:
        raise ModelCallError("SCHEMA", schema_diagnostic(exc, raw),
                             request_id=getattr(response, "_request_id", None)) from None


def _report_usage(response, callback):
    if callback is None:
        return
    usage = getattr(response, 'usage', None)
    if usage is None:
        return
    def get(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    def number(value):
        return value if type(value) is int and value >= 0 else None
    def choose(*values):
        return next((n for v in values if (n := number(v)) is not None), None)
    inputs = choose(get(usage, 'input_tokens'), get(usage, 'prompt_tokens'))
    outputs = choose(get(usage, 'output_tokens'), get(usage, 'completion_tokens'))
    if inputs is None and outputs is None:
        return
    value = dict(response_id=getattr(response, 'id', None),
        input_tokens=inputs, output_tokens=outputs, total_tokens=number(get(usage, 'total_tokens')),
        cached_input_tokens=choose(get(get(usage, 'input_tokens_details'), 'cached_tokens'),
                                  get(get(usage, 'prompt_tokens_details'), 'cached_tokens'),
                                  get(usage, 'prompt_cache_hit_tokens')),
        reasoning_output_tokens=choose(get(get(usage, 'output_tokens_details'), 'reasoning_tokens'),
                                       get(get(usage, 'completion_tokens_details'), 'reasoning_tokens')))
    reported_model = getattr(response, 'model', None)
    if isinstance(reported_model, str): value['reported_model'] = reported_model
    callback(value)


def _stream_model(system, user, text_format, *, model, timeout, on_partial, on_transport, on_cancel_handle=None, reasoning_effort=None, max_output_tokens=None, on_usage=None, on_request=None):
    """Only output_text reaches the projection callback; reasoning is never read.

    A projection is a preview, not a validated model result. Once any preview has
    escaped, no endpoint fallback/re-generation is allowed inside this request.
    """
    client = _client(timeout=timeout)
    if on_cancel_handle:
        on_cancel_handle(client.close)
    selected = model or MODEL
    snapshot = ""
    published = False
    response = None
    response_id = None
    try:
        # Use raw SDK events: some compatible providers emit whitespace keepalives
        # before response.created, which the SDK's snapshot aggregator rejects.
        request_timeout = current_budget.get().take()
        if on_request: on_request()
        with client.responses.create(model=selected, input=_input(system, user),
           text={"format": _text_format(text_format)}, stream=True,
           timeout=request_timeout, **({"max_output_tokens": max_output_tokens} if max_output_tokens else {}), **_reasoning(reasoning_effort)) as stream:
            for event in stream:
                current_budget.get().remaining()
                if event.type == "response.refusal.delta":
                    raise ModelCallError("REFUSAL")
                if event.type in {"response.failed", "response.incomplete", "error"}:
                    _report_usage(getattr(event, 'response', None), on_usage)
                    raise ModelCallError("INCOMPLETE", event.type)
                if event.type == "response.created":
                    incoming = getattr(event.response, "id", None)
                    if response_id != incoming:
                        if published:
                            raise ModelCallError("PROTOCOL", "response changed after public output")
                        snapshot = ""
                    response_id = incoming
                if event.type == "response.completed":
                    response = event.response
                    _report_usage(response, on_usage)
                if event.type != "response.output_text.delta":
                    continue
                snapshot += event.delta
                try:
                    partial = jiter.from_json(snapshot.encode(), partial_mode="trailing-strings")
                except ValueError:
                    continue  # e.g. a split JSON escape / surrogate pair
                if isinstance(partial, dict):
                    published = published or bool(partial)
                    on_partial(partial)
        if response is None:
            raise ModelCallError("INCOMPLETE", "stream ended without response.completed")
        if getattr(response, "status", None) in {"failed", "cancelled", "incomplete"}:
            raise ModelCallError("INCOMPLETE", response.status)
        for output in getattr(response, "output", []) or []:
            if any(getattr(part, "type", "") == "refusal" for part in getattr(output, "content", []) or []):
                raise ModelCallError("REFUSAL")
        final_text = "".join(getattr(part, "text", "") for output in getattr(response, "output", []) or []
                             for part in getattr(output, "content", []) or [] if getattr(part, "type", "") == "output_text")
        if final_text or snapshot.strip():
            if on_transport:
                on_transport("streaming" if snapshot else "buffered")
            return _validate_output(text_format, final_text or snapshot, response)
        if published:
            raise ModelCallError("EMPTY")
    except APIStatusError as exc:
        # Compatibility providers may explicitly reject streaming. Other provider
        # errors (auth, rate limit, schema) must remain diagnosable, not retried.
        if published or exc.status_code not in {400, 404, 405, 422, 501} or "stream" not in str(exc).lower():
            raise
    if on_transport:
        on_transport("buffered")
    return _parse_model(system, user, text_format, model=model, timeout=current_budget.get().remaining(),
                        on_cancel_handle=on_cancel_handle, reasoning_effort=reasoning_effort, max_output_tokens=max_output_tokens, on_usage=on_usage, on_request=on_request)


def model_stream_capability(model: str, *, reasoning_effort: str | None = None) -> dict:
    class Probe(BaseModel):
        message: str
        ready: bool
    chunks = []
    transports = []
    result = parse_model("Return ready=true and message counting from one to twenty. Use the required schema.",
                         "Check structured streaming.", Probe, model=model, timeout=MODEL_PROBE_TIMEOUT_SECONDS,
                         reasoning_effort=reasoning_effort,
                         on_partial=lambda value: chunks.append(value.get("message", "")),
                         on_transport=transports.append)
    distinct = {text for text in chunks if text and text != result.message}
    return {"ready": result.ready, "streaming": "ready" if distinct and "buffered" not in transports else "buffered"}


def _parse_model(system, user, text_format, *, model, timeout, on_cancel_handle=None, reasoning_effort=None, max_output_tokens=None, on_usage=None, on_request=None):
    client = _client(timeout=timeout)
    if on_cancel_handle:
        on_cancel_handle(client.close)
    selected_model = model or MODEL
    params = dict(model=selected_model, input=_input(system, user),
                  timeout=current_budget.get().take(), **({"max_output_tokens": max_output_tokens} if max_output_tokens else {}), **_reasoning(reasoning_effort))
    if on_request: on_request()
    if PROVIDER == "deepseek":
        response = client.responses.create(**params, text={"format": _text_format(text_format)})
    else:
        response = client.responses.parse(**params, text_format=text_format)
    _report_usage(response, on_usage)
    if getattr(response, "status", None) in {"incomplete", "failed", "cancelled"}:
        raise ModelCallError("INCOMPLETE", str(response.status))
    for output in getattr(response, "output", []) or []:
        if any(getattr(part, "type", "") == "refusal" for part in getattr(output, "content", []) or []):
            raise ModelCallError("REFUSAL")
    if PROVIDER == "deepseek":
        text = "".join(getattr(part, "text", "") for output in getattr(response, "output", []) or []
                       for part in getattr(output, "content", []) or [] if getattr(part, "type", "") == "output_text")
        if text.strip():
            return _validate_output(text_format, text, response)
        raise ModelCallError("EMPTY")
    if response.output_parsed is not None:
        return response.output_parsed

    # Some OpenAI-compatible providers complete Responses requests without output.
    # Fall back only for that empty-success case; transport and API errors still raise.
    request_timeout = current_budget.get().take()
    if on_request: on_request()
    completion = client.chat.completions.parse(
        model=selected_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=text_format,
        timeout=request_timeout,
        **({"reasoning_effort": reasoning_effort} if reasoning_effort else {}),
        **({"max_completion_tokens": max_output_tokens} if max_output_tokens else {}),
    )
    _report_usage(completion, on_usage)
    if not completion.choices:
        raise ModelCallError("EMPTY")
    if getattr(completion.choices[0].message, "refusal", None):
        raise ModelCallError("REFUSAL")
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ModelCallError("EMPTY")
    return parsed


def available_model_ids() -> set[str]:
    """Return model IDs visible to the configured provider without exposing credentials."""
    return {item.id for item in _client(timeout=MODEL_PROBE_TIMEOUT_SECONDS).models.list().data if getattr(item, "id", "")}


def model_is_callable(model: str, *, reasoning_effort: str | None = None) -> bool:
    """A transport ID alone does not prove structured output is usable."""
    class Probe(BaseModel):
        ready: bool
    result = parse_model("Return ready=true in the required schema.", "Check structured output.",
                         Probe, model=model, timeout=MODEL_PROBE_TIMEOUT_SECONDS, reasoning_effort=reasoning_effort)
    return result.ready is True


def transcribe_audio(data: bytes, filename: str) -> str:
    if PROVIDER == "deepseek":
        raise ModelCallError("UNSUPPORTED", "audio transcription not configured")
    client = _client()
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=(filename, data),
    )
    text = getattr(transcript, "text", "") or ""
    if not text.strip():
        raise RuntimeError("RT.CAPTURE.TRANSCRIBE_FAILED")
    return text.strip()


def dump(model: BaseModel) -> str:
    return json.dumps(model.model_dump(), ensure_ascii=False, indent=2)
