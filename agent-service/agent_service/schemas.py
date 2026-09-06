import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

KnowledgeType = Literal["fact", "concept", "procedure"]
Attribution = Literal["claim", "source_view", "personal"]
InputType = Literal["text", "url", "voice"]
TaskStatus = Literal[
    "queued",
    "uploading",
    "processing",
    "committing",
    "completed",
    "retryable_failed",
    "needs_attention",
    "cancelled",
]


class ScoringSpec(BaseModel):
    learning_goal: str = Field(min_length=1)
    must_cover: list[str] = Field(min_length=1)
    acceptable_paraphrases: list[str] = Field(default_factory=list)
    common_misconceptions: list[str] = Field(default_factory=list)
    evidence: str = ""
    order_rules: str = ""

    @field_validator("must_cover")
    @classmethod
    def require_nonblank_coverage(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("must_cover items cannot be blank")
        return value


class QuestionDraft(BaseModel):
    variant_index: int = Field(ge=0, le=2)
    prompt_text: str = Field(min_length=1)


class KnowledgeDraft(BaseModel):
    id: str
    learning_goal: str
    knowledge_type: KnowledgeType
    theme: str
    content_language: str
    question_language: str
    answer_language: str
    evidence_excerpt: str = Field(min_length=1)
    evidence_locator: str
    title: str = Field(min_length=1, description="卡片关键词：这条知识是什么，名词性短标题，不要写成说明/描述/概括。")
    explanation: str = Field(min_length=1, description="卡片详解：用户主语言、Markdown 式分点（1. 2. 3. 或 -），3–6 条，必须能对回 evidence_excerpt。")
    scoring_spec: ScoringSpec
    questions: list[QuestionDraft] = Field(min_length=1, max_length=3)

    @field_validator("id")
    @classmethod
    def require_uuid(cls, value: str) -> str:
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("knowledge id must be a valid UUID") from exc

    @field_validator("questions")
    @classmethod
    def require_one_main_question(cls, value: list[QuestionDraft]) -> list[QuestionDraft]:
        indices = [item.variant_index for item in value]
        if indices.count(0) != 1:
            raise ValueError("exactly one main question with variant_index 0 is required")
        if len(indices) != len(set(indices)):
            raise ValueError("question variant_index values must be unique")
        return value

    @model_validator(mode="after")
    def require_scoring_evidence(self) -> "KnowledgeDraft":
        if not self.scoring_spec.evidence.strip():
            raise ValueError("scoring_spec.evidence is required for capture knowledge")
        return self


class ExtractPayload(BaseModel):
    understood_as: str
    theme: str
    attribution: Attribution
    risk_flagged: bool = False
    risk_reason: str = ""
    knowledge: list[KnowledgeDraft] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def require_unique_knowledge_ids(self) -> "ExtractPayload":
        ids = [item.id for item in self.knowledge]
        if len(ids) != len(set(ids)):
            raise ValueError("knowledge ids must be unique")
        return self


class SemanticVerdict(BaseModel):
    ok: bool
    issues: list[str] = Field(default_factory=list)


class IntentClass(BaseModel):
    intent: Literal["remember_content", "learn_topic", "too_broad"]
    topic: str = ""
    reason: str = ""


class RiskVerdict(BaseModel):
    risk: bool
    reason: str = ""


class VerifyVerdict(BaseModel):
    verdict: Literal["confirmed", "conflict", "insufficient"]
    reason: str = ""
    sources: list[str] = Field(default_factory=list)


class SourceCandidate(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""


class SourceList(BaseModel):
    candidates: list[SourceCandidate] = Field(default_factory=list, max_length=3)


class CaptureSubmitRequest(BaseModel):
    task_id: str
    source_id: str
    input_type: InputType = "text"
    raw_text: str = ""
    url: str | None = None
    primary_language: str = "zh"
    audio_base64: str = ""
    audio_format: str = "m4a"


class CaptureAckRequest(BaseModel):
    knowledge_ids: list[str] = Field(default_factory=list)


class CaptureActionRequest(BaseModel):
    action: Literal[
        "reprocess",
        "paste",
        "attach_url",
        "find_sources",
        "confirm_sources",
        "adopt_limited",
        "as_source_view",
        "keep_paused",
        "delete",
        "confirm_transcript",
    ]
    raw_text: str = ""
    url: str = ""
    urls: list[str] = Field(default_factory=list)
    transcript: str = ""


class Receipt(BaseModel):
    understood_as: str
    theme: str
    knowledge_count: int
    attribution: Attribution


class CaptureTaskView(BaseModel):
    task_id: str
    status: TaskStatus
    user_status: str
    error_code: str | None = None
    receipt: Receipt | None = None
    result: ExtractPayload | None = None
    source_id: str | None = None
    intent: str | None = None
    source_candidates: list[SourceCandidate] = Field(default_factory=list)
    verify_reason: str | None = None
    events: list[dict] = Field(default_factory=list)


class GradeRequest(BaseModel):
    attempt_id: str
    prompt_text: str
    scoring_spec: ScoringSpec
    answer_text: str
    hint_used: bool = False
    primary_language: str = "zh"

    @field_validator("attempt_id")
    @classmethod
    def require_attempt_uuid(cls, value: str) -> str:
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("attempt_id must be a valid UUID") from exc

    @field_validator("prompt_text", "answer_text", "primary_language")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("grade request text fields cannot be blank")
        return value

    @model_validator(mode="after")
    def require_scoring_evidence(self) -> "GradeRequest":
        if not self.scoring_spec.evidence.strip():
            raise ValueError("scoring_spec.evidence is required for grading")
        return self


class GradeResult(BaseModel):
    attempt_id: str = ""
    agent_grade: Literal["again", "hard", "good"]
    brief_feedback: str = Field(min_length=1, max_length=240)
    hint_used: bool = False

    @field_validator("brief_feedback")
    @classmethod
    def require_nonblank_feedback(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("brief_feedback cannot be blank")
        return value


class GradeAckRequest(BaseModel):
    attempt_id: str

    @field_validator("attempt_id")
    @classmethod
    def require_attempt_uuid(cls, value: str) -> str:
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("attempt_id must be a valid UUID") from exc

