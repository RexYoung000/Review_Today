import json

from openai import OpenAI, APITimeoutError, APIConnectionError, APIStatusError
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
) -> BaseModel:
    try:
        return _parse_model(system, user, text_format, model=model, timeout=timeout)
    except ModelCallError:
        raise
    except APITimeoutError as exc:
        raise ModelCallError("TIMEOUT", type(exc).__name__) from None
    except APIConnectionError as exc:
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


def _parse_model(system, user, text_format, *, model, timeout):
    client = _client(timeout=timeout)
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
