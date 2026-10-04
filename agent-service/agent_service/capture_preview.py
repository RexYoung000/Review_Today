"""Optional, source-backed invitation prose; never a generated knowledge card."""
from copy import deepcopy

from pydantic import BaseModel, Field, ValidationError, field_validator


class CapturePreviewText(BaseModel):
    text: str = Field(min_length=1, max_length=160,
        description="忠于所附引文的简短自然概括，不写评分、保存或掌握状态，不补写来源以外的知识。")
    evidence_quotes: list[str] = Field(min_length=1, max_length=4,
        description="支撑这项概括的当前有效知识选段中的连续逐字引文，保留格式和必要限定。")

    @field_validator('text')
    @classmethod
    def nonblank_text(cls, value):
        if not value.strip():
            raise ValueError('preview text must be nonblank')
        return value.strip()

    @field_validator('evidence_quotes')
    @classmethod
    def nonblank_quotes(cls, values):
        if any(not value.strip() for value in values):
            raise ValueError('preview evidence must be nonblank')
        return [value.strip() for value in values]


class CapturePreview(BaseModel):
    points: list[CapturePreviewText] = Field(min_length=1, max_length=4,
        description="少量实际知识要点，按内容选择，不凑条数，不截断句子或生成完整卡片。")
    summary: CapturePreviewText = Field(description="一句概括当前拟整理内容的总结，同样附当前有效来源引文。")


def optional_preview(value):
    """Malformed optional presentation must not fail an answer/schema repair."""
    try:
        if isinstance(value, CapturePreview):
            value = value.model_dump()
        return CapturePreview.model_validate(value) if value is not None else None
    except (ValidationError, TypeError, ValueError):
        return None


def grounded_fields(value, fragments):
    preview = optional_preview(value)
    if preview is None:
        return {}
    if (not isinstance(fragments, (list, tuple))
            or any(not isinstance(fragment, dict) or not isinstance(fragment.get('text'), str) for fragment in fragments)):
        return {}
    texts = [fragment['text'] for fragment in fragments]
    items = [*preview.points, preview.summary]
    # Each continuous witness belongs to a selected fragment, not to the full
    # lesson, a discarded correction, a user's answer, or a different offer.
    if any(not any(quote in text for text in texts) for item in items for quote in item.evidence_quotes):
        return {}
    points = [item.text for item in preview.points]
    if len(set(points)) != len(points):
        return {}
    return dict(preview_points=points, preview_summary=preview.summary.text)


def clear(offer):
    for key in ('preview', 'preview_version', 'preview_points', 'preview_summary'):
        offer.pop(key, None)


def replace(offer, value):
    """Replace the complete preview alongside the new scope/version, or fall back."""
    clear(offer)
    fields = grounded_fields(value, offer['fragments'])
    if fields:
        offer.update(fields, preview=optional_preview(value).model_dump(), preview_version=offer['version'])


def public(offer):
    if offer.get('preview_version') != offer.get('version'):
        return {}
    fields = grounded_fields(offer.get('preview'), offer.get('fragments', []))
    # Persisted presentation cannot drift from its evidence-bearing snapshot.
    return deepcopy(fields) if all(offer.get(key) == value for key, value in fields.items()) else {}
