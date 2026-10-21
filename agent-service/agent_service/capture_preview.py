"""Optional, source-backed invitation prose; never a generated knowledge card."""
from copy import deepcopy
import json

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
    """Keep legacy parsing optional; new eligible invitations validate separately."""
    try:
        if isinstance(value, CapturePreview):
            value = value.model_dump()
        return CapturePreview.model_validate(value) if value is not None else None
    except (ValidationError, TypeError, ValueError):
        return None


def ungrounded_quote_paths(preview, fragments):
    texts = [fragment['text'] for fragment in fragments]
    items = [(['points', index], item) for index, item in enumerate(preview.points)]
    items.append((['summary'], preview.summary))
    return [path + ['evidence_quotes', index] for path, item in items
            for index, quote in enumerate(item.evidence_quotes)
            if not any(quote in text for text in texts)]


def grounded_fields(value, fragments):
    preview = optional_preview(value)
    if preview is None:
        return {}
    if (not isinstance(fragments, (list, tuple))
            or any(not isinstance(fragment, dict) or not isinstance(fragment.get('text'), str) for fragment in fragments)):
        return {}
    # Each continuous witness belongs to a selected fragment, not to the full
    # lesson, a discarded correction, a user's answer, or a different offer.
    if ungrounded_quote_paths(preview, fragments):
        return {}
    points = [item.text for item in preview.points]
    if len(set(points)) != len(points):
        return {}
    return dict(preview_points=points, preview_summary=preview.summary.text)


def validate_initial_preview(output, payload, *, passed):
    """Repair a missing new invitation preview, preserving optional legacy reads."""
    binding = payload.get('check_binding')
    concepts = payload.get('capture_concepts')
    quotes = output.capture_quotes
    reference = payload.get('reference')
    if (passed is not True or output.question_validity != 'valid' or payload.get('hint_used')
            or not isinstance(binding, dict) or not binding.get('step_id')
            or not isinstance(concepts, list) or not concepts):
        return
    from agent_service.call_errors import ModelCallError
    if not quotes or not isinstance(reference, str) or any(quote not in reference for quote in quotes):
        if payload.get('_repair_missing_capture_preview') is True:
            raise ModelCallError('SCHEMA', json.dumps([
                dict(field=['capture_quotes'], type='initial_capture_preview_source_missing')]))
        return
    if output.capture_preview is None:
        error = ModelCallError('SCHEMA', json.dumps([
            dict(field=['capture_preview'], type='initial_capture_preview_missing')]))
        error.repair_missing_capture_preview = True
        raise error
    # Only the repair of this missing field tightens provenance here. Existing
    # valid-shaped initial previews retain their original fallback behavior.
    if payload.get('_repair_missing_capture_preview') is not True:
        return
    preview = output.capture_preview
    fragments = [dict(text=quote) for quote in quotes + output.capture_feedback_quotes]
    issues = [dict(field=['capture_preview'] + path, type='initial_capture_preview_grounding')
              for path in ungrounded_quote_paths(preview, fragments)]
    if len({item.text for item in preview.points}) != len(preview.points):
        issues.append(dict(field=['capture_preview', 'points'], type='initial_capture_preview_duplicate'))
    if issues:
        raise ModelCallError('SCHEMA', json.dumps(issues))


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
