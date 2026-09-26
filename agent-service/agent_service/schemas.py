import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from agent_service.image_inputs import ImageAttachment

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


# Harness V2 ---------------------------------------------------------------

SessionMode = Literal[
    "auto",
    "memory_organization",
    "source_learning",
    "topic_exploration",
    "problem_solving",
]
ResolvedMode = Literal[
    "memory_organization",
    "source_learning",
    "topic_exploration",
    "problem_solving",
]
LearningTaskStatus = Literal[
    "accepted",
    "queued",
    "running",
    "awaiting_user",
    "committing",
    "completed",
    "retryable_failed",
    "needs_attention",
    "cancelled",
    "terminal_failed",
]
TopicRelation = Literal["continuation", "related_subtopic", "new_topic", "uncertain"]
EvidenceState = Literal["unverified", "supported", "conflicting", "insufficient", "outdated", "scoped"]


class ContextMessage(BaseModel):
    role: Literal["user", "coach", "system_summary"]
    content: str = Field(min_length=1, max_length=512_000)


class TurnContext(BaseModel):
    continuation_candidates: list[dict[str, Any]] | None = None
    summary: str = Field(default="", max_length=12_000)
    recent_messages: list[ContextMessage] = Field(default_factory=list, max_length=20)
    knowledge_summaries: list[str] = Field(default_factory=list, max_length=5)
    handoff: dict | None = None
    memory_lookup_available: bool = False
    memory_candidates: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    invalid_memory_run_ids: list[str] = Field(default_factory=list, max_length=1000)


class SessionTurnRequest(BaseModel):
    client_message_id: str
    content: str = Field(min_length=1, max_length=512_000)
    content_type: Literal["text", "url"] = "text"
    mode_preset: SessionMode = "auto"
    primary_language: str = "zh"
    context: TurnContext = Field(default_factory=TurnContext)

    @field_validator("client_message_id")
    @classmethod
    def require_message_uuid(cls, value: str) -> str:
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("client_message_id must be a valid UUID") from exc

    @field_validator("content", "primary_language")
    @classmethod
    def require_turn_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("turn text fields cannot be blank")
        return value


class TaskRequiredAction(BaseModel):
    type: Literal[
        "respond",
        "choose_sources",
        "confirm_understanding",
        "choose_question",
        "submit_answer",
        "confirm_memory",
        "resolve_conflict",
        "confirm_mode_switch",
        "confirm_new_session",
    ]
    prompt: str = Field(min_length=1)
    options: list[str] = Field(default_factory=list)


class HarnessMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["coach", "system_summary"] = "coach"
    content: str = Field(min_length=1)
    created_at: str = ""


class TaskEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    task_id: str
    seq: int = Field(ge=1)
    occurred_at: str
    stage: str
    state: str
    node: str
    user_summary: str = Field(min_length=1)
    detail_summary: str = ""
    attempt: int = Field(default=1, ge=1)
    duration_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    recovery_action: str | None = None
    required_action: TaskRequiredAction | None = None
    message: HarnessMessage | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionTurnAccepted(BaseModel):
    message_id: str
    task_id: str
    status: Literal["accepted", "queued"]
    next_event_seq: int = 1


class LearningTaskView(BaseModel):
    goal_ownership_json: str | None = None
    lifecycle_revision: int = 0
    learning_plan_json: str | None = None
    learning_outcome_json: str | None = None
    sources_json: str | None = None
    memory_references_json: str | None = None
    draft_target_id: str | None = None
    run_id: str | None = None
    understanding: Literal["unknown", "self_reported", "verified"] = "unknown"
    task_id: str
    session_id: str
    client_message_id: str
    mode: SessionMode
    status: LearningTaskStatus
    stage: str
    user_summary: str
    retry_count: int = 0
    error_code: str | None = None
    required_action: TaskRequiredAction | None = None
    result_summary: str = ""
    last_event_seq: int = 0
    last_acked_seq: int = 0
    memory_package: ExtractPayload | None = None
    memory_source_text: str = ""


class TaskEventPage(BaseModel):
    task_id: str
    events: list[TaskEvent] = Field(default_factory=list)
    last_seq: int = 0


class TaskActionRequest(BaseModel):
    action_id: str
    action_type: Literal[
        "respond",
        "select_sources",
        "confirm_understanding",
        "select_question",
        "submit_answer",
        "form_memory",
        "skip_memory",
        "retry",
        "cancel",
        "switch_mode",
        "continue_session",
        "create_handoff",
    ]
    content: str = ""
    selection: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("action_id")
    @classmethod
    def require_action_uuid(cls, value: str) -> str:
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("action_id must be a valid UUID") from exc


class TaskAckRequest(BaseModel):
    last_event_seq: int = Field(ge=0)
    knowledge_ids: list[str] = Field(default_factory=list)


class ModeDecision(BaseModel):
    mode: ResolvedMode
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)
    suggest_switch: bool = False
    relation: TopicRelation = "continuation"


class SourcePackItem(BaseModel):
    title: str
    purpose: str
    url: str
    date_or_version: str = ""
    scope: str = ""
    snippet: str = ""
    evidence_state: EvidenceState = "unverified"


class SourcePack(BaseModel):
    topic: str
    sources: list[SourcePackItem] = Field(min_length=2, max_length=4)


class EvidenceAssessment(BaseModel):
    state: EvidenceState
    reason: str
    sources: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"


class LearningPlan(BaseModel):
    goal: str
    steps: list[str] = Field(min_length=1, max_length=8)
    success_check: str
    # Existing IDs only. Empty entries create new steps; title edits retain ID.
    step_ids: list[str] = Field(default_factory=list, max_length=8, description="Only IDs of existing steps from context, aligned with steps. For a new plan return an empty list. Never invent existing IDs.")


class LessonStep(BaseModel):
    title: str
    explanation: str
    source_name: str = ""
    source_locator: str = ""
    check_question: str = ""


class UnderstandingCheck(BaseModel):
    question: str
    expected_points: list[str] = Field(default_factory=list)
    passed: bool | None = None
    feedback: str = ""


class QuestionAnalysis(BaseModel):
    question: str
    question_type: str
    assumptions: list[str] = Field(default_factory=list)
    calibration_question: str


class JDAnalysis(BaseModel):
    role_goal: str
    competency_map: list[str] = Field(min_length=1, max_length=12)
    risk_points: list[str] = Field(default_factory=list, max_length=8)
    prioritized_questions: list[str] = Field(min_length=1, max_length=12)


class ProblemAnswer(BaseModel):
    direct_answer: str
    spoken_answer: str = ""
    assumptions: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]
    evidence_state: EvidenceState = "unverified"
    evidence_notes: list[str] = Field(default_factory=list)


class KnowledgeGapMap(BaseModel):
    related_knowledge: list[str] = Field(min_length=1, max_length=12)
    likely_gaps: list[str] = Field(default_factory=list, max_length=8)
    learning_order: list[str] = Field(min_length=1, max_length=8)


class ProblemCoachBundle(BaseModel):
    analysis: QuestionAnalysis
    answer: ProblemAnswer
    gap_map: KnowledgeGapMap
    learning_plan: LearningPlan


class MasteryEvaluation(BaseModel):
    passed: bool
    correctness: str
    completeness: str
    expression: str
    transfer: str
    feedback: str
    followup_question: str = ""


class MemoryPackage(BaseModel):
    source_summary: str
    learning_goal: str
    proposed_card_count: int = Field(ge=1, le=8)
    evidence_state: EvidenceState


class CoachTurnOutput(BaseModel):
    message: str = Field(min_length=1)
    stage: str
    required_action: TaskRequiredAction | None = None
    result_summary: str = ""
    evidence_state: EvidenceState = "unverified"


# Message intent is deliberately not a five-way content classifier. Workflow is
# optional: a greeting, correction or stop is useful without a learning goal.
class IntentOperation(BaseModel):
    kind: Literal["save", "new_session", "change_goal", "set_mode", "continue_session", "select_sources", "select_question"]
    disposition: Literal["confirm", "reject", "conditional", "request"]
    target_id: str = ""
    version: int = 0
    evidence: str = ""
    selection: list[str] = Field(default_factory=list)


class MemorySelection(BaseModel):
    id: str
    relation: Literal["prerequisite", "analogy", "contrast", "transfer"]


class TopicClosure(BaseModel):
    evidence: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=100)
    message_ids: list[str] = Field(min_length=1, max_length=30)
    next_request: str = Field(default="", max_length=1000)


class IntentDecision(BaseModel):
    conversation_kind: Literal["ordinary", "social", "companionship", "learning_support", "background"] = Field(
        default="ordinary", description="Semantic dialogue scope. Social/companionship only for pure social input; mixed knowledge or action requests stay ordinary.")
    clarification_kind: Literal["none", "content", "resume_target", "operation"] = "none"
    conversation_repair: bool = False
    reply_feedback: Literal["none", "response_only", "with_request"] = Field(
        default="none", description="Feedback on repetitive, curt or otherwise unhelpful replies. response_only has no independent knowledge or action request; with_request must retain that request. Not a keyword match or a learning outcome.")
    reply_purpose: Literal['none', 'product_information', 'boundary_confirmation'] = Field(default='none',
        description='Pure conversation only: product_information asks about this assistant identity, capabilities, memory or configured model; boundary_confirmation only confirms the immediately preceding product limit. Any independent knowledge question or operation must use none.')
    repair_target_message_id: str = ""
    continuation_evidence: str = ""
    continuation_topic: str = ""
    programming_boundary: Literal["none", "capability_question", "development_delivery", "mixed_learning"] = Field(
        default="none", description="Semantic product boundary: programming capability enquiry, development delivery request, or ordinary learning. Not a keyword filter.")
    programming_learning_request: str = Field(default="", max_length=2000, description="For mixed_learning only: quote a smaller, independent learning excerpt verbatim, never the full input or the development request. Example: '解释闭包，再部署项目' -> '解释闭包'.")
    resource_boundary: Literal["none", "capability_question", "resource_delivery", "mixed_learning"] = Field(
        default="none", description="Product scope for resource acquisition and external errands, not a download keyword filter. Knowledge/source study stays none.")
    resource_learning_request: str = Field(default="", max_length=2000, description="For mixed_learning quote only the independent knowledge request from current inputs; search flags/query must refer only to that request.")
    learning_reply_sentence_limit: int | None = Field(default=None, ge=1, le=10,
        description="Only for mixed_learning: an explicit user sentence limit for the knowledge explanation, e.g. 一句话 -> 1. Never invent a limit. Keep this separate from the exact learning excerpt.")
    intents: list[Literal[
        "greeting", "thanks", "capabilities", "social", "question", "goal", "material",
        "followup", "hint", "example", "answer", "correction", "confirm", "reject",
        "defer", "continue", "skip_check", "self_report", "stop", "pause", "cancel", "queue",
    ]] = Field(min_length=1)
    target_task_id: str = ""
    target_description: str = ""
    relation: Literal["continuation", "related_subtopic", "new_topic", "uncertain"]
    workflow: ResolvedMode | None = None
    scope: Literal["conversation", "organize", "learning", "continue_goal"]
    proposed_actions: list[IntentOperation] = Field(default_factory=list)
    clarification: str = Field(default="", description="只问一个必要的缺失项；不重问已知用途，不一次索取多项背景")
    rationale: str = Field(min_length=1)
    understanding: Literal["unknown", "self_reported"] = "unknown"
    answer_evidence: str = Field(default="", description="For answer intent, copy the exact text of the current user answer; never copy options or a prior message.")
    topic_closure: TopicClosure | None = None
    learning_goal_ready: bool = False
    direct_teaching: bool = False
    answer_only: bool = False
    is_jd: bool = False
    jd_request: Literal['none', 'analyze', 'method'] = Field(default='none',
        description='analyze: work on a concrete supplied job description for interview preparation; method: learn how to dissect a JD; none: mention/background or ordinary concepts.')
    needs_verification: bool = False
    cross_check_sources: bool = False
    requested_mode: SessionMode | None = None
    refresh_sources: bool = False
    public_search_query: str = Field(default="", max_length=180)
    light_reply: str = Field(default="", max_length=600)
    session_tags: list[str] = Field(default_factory=list, max_length=5)
    handoff_source_ids: list[str] = Field(default_factory=list, max_length=8)
    handoff_step_ids: list[str] = Field(default_factory=list, max_length=10)
    memory_selections: list[MemorySelection] = Field(default_factory=list, max_length=2)


class BoundOperation(BaseModel):
    """An explicit UI action bound to the displayed object, never inferred by Swift."""
    kind: Literal["save", "reject_save", "continue_session", "new_session", "select_sources", "select_question", "capture_save", "capture_later", "capture_skip"]
    target_id: str
    version: int = Field(ge=1)
    selection: list[str] = Field(default_factory=list)


class SessionMessageRequest(SessionTurnRequest):
    content_type: Literal["text", "url", "image"] = "text"
    image: ImageAttachment | None = None
    images: list[ImageAttachment] = Field(default_factory=list, max_length=8)
    delivery: Literal["steer", "queue"] = "steer"
    task_id: str | None = None
    operation: BoundOperation | None = None
    expected_event_seq: int | None = Field(default=None, ge=0)
    lifecycle_revision: int | None = Field(default=None, ge=0)
    thinking_strength: Literal["smart", "deep"] | None = None

    @model_validator(mode="after")
    def image_contract(self):
        supplied = self.image is not None or bool(self.images)
        if supplied != (self.content_type == "image") or (supplied and self.operation) or (self.image and self.images):
            raise ValueError("RT.IMAGE.INVALID_MESSAGE")
        return self


class MessageAccepted(BaseModel):
    message_id: str
    run_id: str
    task_id: str | None = None
    status: str
    revision: int


class RunActionRequest(BaseModel):
    action_id: str
    action: Literal["stop", "resume", "retry", "cancel_task", "set_mode", "set_thinking"]
    mode: SessionMode | None = None
    thinking_strength: Literal["smart", "deep"] | None = None

    @field_validator("action_id")
    @classmethod
    def valid_action_id(cls, value: str) -> str:
        return str(uuid.UUID(value))


class SessionAckRequest(BaseModel):
    last_event_seq: int = Field(ge=0)


class ConversationOutput(BaseModel):
    message: str = Field(min_length=1)
    check_question: str = ""
    evidence_state: EvidenceState = "unverified"
    learning_plan: LearningPlan | None = None
    learning_concepts: list[str] = Field(default_factory=list, max_length=6)


class EvidenceAssessmentV2(BaseModel):
    state: EvidenceState
    summary: str
    sources: list[str] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    goal: str
    confirmed_decisions: list[str]
    open_questions: list[str]
    summary: str


class TeachingPreparation(BaseModel):
    official_sources_required: bool = False
    source_domains: list[str] = Field(default_factory=list, max_length=4)
    concepts: list[str] = Field(default_factory=list, max_length=6)
    public_query: str = Field(default="", max_length=180)
    new_knowledge: bool = True


class MemoryChoice(BaseModel):
    selections: list[MemorySelection] = Field(default_factory=list, max_length=2)


class MemoryResultsRequest(BaseModel):
    request_id: uuid.UUID
    revision: int = Field(ge=1)
    lifecycle_revision: int = Field(ge=0)
    candidates: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
