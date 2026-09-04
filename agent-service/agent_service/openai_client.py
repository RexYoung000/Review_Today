import json
from collections.abc import Callable

import jiter
import httpx

from openai import OpenAI, APITimeoutError, APIConnectionError, APIStatusError
from openai.lib._parsing._responses import type_to_text_format_param
from pydantic import BaseModel, ValidationError

from agent_service.config import BASE_URL, MODEL, MODEL_PROBE_TIMEOUT_SECONDS, MODEL_TIMEOUT_SECONDS, openai_key


def _client(*, timeout: float = MODEL_TIMEOUT_SECONDS) -> OpenAI:
    key = openai_key()
    if not key:
        raise RuntimeError("RT.CAPTURE.NO_KEY")
    if BASE_URL:
        return OpenAI(api_key=key, base_url=BASE_URL, timeout=timeout, max_retries=0)
    return OpenAI(api_key=key, timeout=timeout, max_retries=0)


def parse_model(
    system: str,
    user: str,
    text_format: type[BaseModel],
    *,
    model: str | None = None,
    timeout: float = MODEL_TIMEOUT_SECONDS,
    on_partial: Callable[[dict], None] | None = None,
    on_transport: Callable[[str], None] | None = None,
    on_cancel_handle: Callable[[Callable[[], None]], None] | None = None,
) -> BaseModel:
    try:
        if on_partial is not None:
            return _stream_model(system, user, text_format, model=model, timeout=timeout,
                                 on_partial=on_partial, on_transport=on_transport, on_cancel_handle=on_cancel_handle)
        return _parse_model(system, user, text_format, model=model, timeout=timeout, on_cancel_handle=on_cancel_handle)
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
        raise ModelCallError("PROVIDER", f"HTTP {exc.status_code}") from None
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ModelCallError("SCHEMA", type(exc).__name__) from None


class ModelCallError(RuntimeError):
    def __init__(self, kind: str, diagnostic: str = ""):
        self.code = f"RT.MODEL.{kind}"
        self.diagnostic = diagnostic  # class/status only, never provider body or credentials
        super().__init__(self.code)


def _stream_model(system, user, text_format, *, model, timeout, on_partial, on_transport, on_cancel_handle=None):
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
        with client.responses.create(model=selected, input=[
            {"role": "developer", "content": system}, {"role": "user", "content": user},
        ], text={"format": type_to_text_format_param(text_format)}, stream=True) as stream:
            for event in stream:
                if event.type == "response.refusal.delta":
                    raise ModelCallError("REFUSAL")
                if event.type in {"response.failed", "response.incomplete", "error"}:
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
            return text_format.model_validate_json(final_text or snapshot)
        if published:
            raise ModelCallError("EMPTY")
    except APIStatusError as exc:
        # Compatibility providers may explicitly reject streaming. Other provider
        # errors (auth, rate limit, schema) must remain diagnosable, not retried.
        if published or exc.status_code not in {400, 404, 405, 422, 501} or "stream" not in str(exc).lower():
            raise
    if on_transport:
        on_transport("buffered")
    return _parse_model(system, user, text_format, model=model, timeout=timeout, on_cancel_handle=on_cancel_handle)


def model_stream_capability(model: str) -> dict:
    class Probe(BaseModel):
        message: str
        ready: bool
    chunks = []
    transports = []
    result = parse_model("Return ready=true and message counting from one to twenty. Use the required schema.",
                         "Check structured streaming.", Probe, model=model, timeout=MODEL_PROBE_TIMEOUT_SECONDS,
                         on_partial=lambda value: chunks.append(value.get("message", "")),
                         on_transport=transports.append)
    distinct = {text for text in chunks if text and text != result.message}
    return {"ready": result.ready, "streaming": "ready" if distinct and "buffered" not in transports else "buffered"}


def _parse_model(system, user, text_format, *, model, timeout, on_cancel_handle=None):
    client = _client(timeout=timeout)
    if on_cancel_handle:
        on_cancel_handle(client.close)
    selected_model = model or MODEL
    response = client.responses.parse(
        model=selected_model,
        input=[
            {"role": "developer", "content": system},
            {"role": "user", "content": user},
        ],
        text_format=text_format,
    )
    if getattr(response, "status", None) in {"incomplete", "failed", "cancelled"}:
        raise ModelCallError("INCOMPLETE", str(response.status))
    for output in getattr(response, "output", []) or []:
        if any(getattr(part, "type", "") == "refusal" for part in getattr(output, "content", []) or []):
            raise ModelCallError("REFUSAL")
    if response.output_parsed is not None:
        return response.output_parsed

    # Some OpenAI-compatible providers complete Responses requests without output.
    # Fall back only for that empty-success case; transport and API errors still raise.
    completion = client.chat.completions.parse(
        model=selected_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=text_format,
    )
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


def model_is_callable(model: str) -> bool:
    """A transport ID alone does not prove structured output is usable."""
    class Probe(BaseModel):
        ready: bool
    result = parse_model("Return ready=true in the required schema.", "Check structured output.",
                         Probe, model=model, timeout=MODEL_PROBE_TIMEOUT_SECONDS)
    return result.ready is True


def web_search_text(query: str, *, model: str | None = None) -> str:
    client = _client()
    selected_model = model or MODEL
    for tool in ({"type": "web_search_preview"}, {"type": "web_search"}):
        try:
            response = client.responses.create(model=selected_model, tools=[tool], input=query)
            text = getattr(response, "output_text", "") or ""
            if text.strip():
                return text.strip()[:8000]
        except Exception:  # noqa: BLE001
            continue
    return ""


def transcribe_audio(data: bytes, filename: str) -> str:
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
