import json

from openai import OpenAI
from pydantic import BaseModel

from agent_service.config import BASE_URL, MODEL, openai_key


def _client() -> OpenAI:
    key = openai_key()
    if not key:
        raise RuntimeError("RT.CAPTURE.NO_KEY")
    if BASE_URL:
        return OpenAI(api_key=key, base_url=BASE_URL)
    return OpenAI(api_key=key)


def parse_model(system: str, user: str, text_format: type[BaseModel]) -> BaseModel:
    response = _client().responses.parse(
        model=MODEL,
        input=[
            {"role": "developer", "content": system},
            {"role": "user", "content": user},
        ],
        text_format=text_format,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("RT.CAPTURE.MODEL_FAILED")
    return parsed


def web_search_text(query: str) -> str:
    client = _client()
    for tool in ({"type": "web_search_preview"}, {"type": "web_search"}):
        try:
            response = client.responses.create(model=MODEL, tools=[tool], input=query)
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
