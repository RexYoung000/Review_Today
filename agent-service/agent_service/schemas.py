from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

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
    learning_goal: str
    must_cover: list[str] = Field(min_length=1)
    acceptable_paraphrases: list[str] = Field(default_factory=list)
    common_misconceptions: list[str] = Field(default_factory=list)
    evidence: str = ""
    order_rules: str = ""


class QuestionDraft(BaseModel):
    variant_index: int = Field(ge=0, le=2)
    prompt_text: str


class KnowledgeDraft(BaseModel):
    id: str
    learning_goal: str
    knowledge_type: KnowledgeType
    theme: str
    content_language: str
    question_language: str
    answer_language: str
    evidence_excerpt: str
    evidence_locator: str
    title: str = Field(min_length=1, description="卡片关键词：这条知识是什么，名词性短标题，不要写成说明/描述/概括。")
    explanation: str = Field(min_length=1, description="卡片详解：用户主语言、Markdown 式分点（1. 2. 3. 或 -），3–6 条，必须能对回 evidence_excerpt。")
    scoring_spec: ScoringSpec
    questions: list[QuestionDraft] = Field(min_length=1, max_length=3)

    @field_validator("questions")
    @classmethod
    def require_main_question(cls, value: list[QuestionDraft]) -> list[QuestionDraft]:
        if not any(item.variant_index == 0 for item in value):
            raise ValueError("main question variant_index 0 is required")
        return value


class ExtractPayload(BaseModel):
    understood_as: str
    theme: str
    attribution: Attribution
    risk_flagged: bool = False
    risk_reason: str = ""
    knowledge: list[KnowledgeDraft] = Field(min_length=1, max_length=8)


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


class GradeResult(BaseModel):
    attempt_id: str = ""
    agent_grade: Literal["again", "hard", "good"]
    brief_feedback: str
    hint_used: bool = False


class GradeAckRequest(BaseModel):
    attempt_id: str

