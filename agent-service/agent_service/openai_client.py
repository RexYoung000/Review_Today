import json

from openai import OpenAI
from pydantic import BaseModel

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
) -> BaseModel:
    client = _client()
    selected_model = model or MODEL
    response = client.responses.parse(
        model=selected_model,
        input=[
            {"role": "developer", "content": system},
            {"role": "user", "content": user},
        ],
        text_format=text_format,
    )
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
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError("RT.CAPTURE.MODEL_FAILED")
    return parsed


def available_model_ids() -> set[str]:
    """Return model IDs visible to the configured provider without exposing credentials."""
    return {item.id for item in _client(timeout=MODEL_PROBE_TIMEOUT_SECONDS).models.list().data if getattr(item, "id", "")}


def model_is_callable(model: str) -> bool:
    """Probe a real generation so advertised-but-unreachable models are not reported ready."""
    response = _client(timeout=MODEL_PROBE_TIMEOUT_SECONDS).responses.create(
        model=model,
        input="Reply OK.",
        max_output_tokens=8,
    )
    return bool(getattr(response, "id", "")) and getattr(response, "status", None) != "failed"


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
