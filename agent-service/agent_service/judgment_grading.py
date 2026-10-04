"""Freeze a rubric before an answer; program logic, not a model score, passes it."""
from __future__ import annotations

import json
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, create_model, field_validator

from agent_service.judgment_types import JudgmentRequest, digest, question
from agent_service.learning_progress import current_step, check_reference
from agent_service.schemas import (ScoringSpec, ConversationOutput, QuestionAnalysis,
                                  ProblemCoachBundle, MasteryEvaluation, CheckBinding,
                                  validate_capture_quote_fields)


class ScoredConversationOutput(ConversationOutput):
    defer_public_preview: ClassVar[bool] = True
    check_scoring_spec: ScoringSpec | None = None


class ScoredQuestionAnalysis(QuestionAnalysis):
    check_scoring_spec: ScoringSpec | None = None


class ScoredProblemCoachBundle(ProblemCoachBundle):
    defer_public_preview: ClassVar[bool] = True
    analysis: ScoredQuestionAnalysis


class ScoredMasteryEvaluation(MasteryEvaluation):
    defer_public_preview: ClassVar[bool] = True
    followup_scoring_spec: ScoringSpec | None = None


class JudgmentFeedback(BaseModel):
    defer_public_preview: ClassVar[bool] = True
    correctness: str
    completeness: str
    expression: str
    transfer: str
    feedback: str
    followup_question: str = ""
    followup_scoring_spec: ScoringSpec | None = None
    question_validity: Literal["valid", "ambiguous", "out_of_scope"] = "valid"
    step_completion_demonstrated: bool = False
    followup_binding: CheckBinding | None = None
    capture_quotes: list[str] = Field(default_factory=list, max_length=6,
        description="本题实际检查知识点所需的 reference 连续逐字选段；只作邀请来源，无可靠选段时为空。")
    capture_feedback_quotes: list[str] = Field(default_factory=list, max_length=6,
        description="本次 feedback 内对应知识点的解释或纠正的连续逐字选段；排除评分、鼓励和新题，没有时为空。")
    capture_scope_summary: str = Field(default="", max_length=160,
        description="用一句具体知识说明所选来源的保存范围，不写流程、评分或保存承诺。")

    @field_validator("capture_quotes", "capture_feedback_quotes")
    @classmethod
    def nonblank_capture_quotes(cls, values):
        if any(not value.strip() for value in values):
            raise ValueError("capture quotes must be nonblank")
        return values

    def validate_request(self, payload):
        validate_capture_quote_fields(self, payload)


CAPTURE_QUOTE_RULE = """
若提供 capture_concepts，只为其中尚未邀请的知识点选择保存片段；不要重复已经邀请的概念。空数组表示无需再选保存片段。
capture_quotes 只从本次 reference 连续逐字摘录本题实际检查概念所需的知识解释，保留原格式、限定、数字和标点。
不要因为同属一节就摘整节材料，不取用户答案、评分描述或新题；没有可靠的对应选段就返回空数组。
capture_feedback_quotes 只从你本次输出的 feedback 连续逐字摘录这些概念的知识解释或纠正；
排除通过/评分描述、鼓励、建议、下一题及其他新知识，没有对应知识内容就返回空数组。
这两个字段只是新增知识邀请的来源范围，不生成知识卡，不改变原始判题标准、通过判定或理解状态。
capture_scope_summary 用一句简短的具体知识概括所选来源，例如“RAG 检索资料辅助回答；微调通过训练调整模型参数。”
不重复标题，不说“对应讲解、有效纠正、保存范围、通过检查”，保留必要条件，不添加选段以外的知识。
本题答对时 feedback 用一两句点明答对之处或必要纠正；无需复述整节讲义、列出已通过知识点、声明其他章节未验证或反复邀请继续追问。
"""


RUBRIC_RULE = """
出知识检查题时同时生成 check_scoring_spec：learning_goal、must_cover 必需要点、
acceptable_paraphrases 同义表达、common_misconceptions 核心误解、evidence 逐字摘录本轮讲解或已有参考材料。
标准仅包含本题必需内容，不把未问内容作为必需要点；order_rules 仅在顺序影响正确性时填写。
检查题只写在专用题目字段，不在 message、direct_answer 或 feedback 正文重复题目。
开放式用途/偏好澄清或没有检查题时标准为 null。标准在看到用户答案前固定。
"""

FOLLOWUP_RULE = """
生成 followup_question 时同时给 followup_scoring_spec，包含该题的必需要点、允许同义表达和核心误解；
evidence 逐字取本次给出的教学参考材料。没有足够材料制定标准时返回 null，不猜测。
追问题目只写在 followup_question，不在 feedback 中重复题目。
"""


def reference_stamp(ctx, step_id):
    return digest(dict(reference=ctx.get("reference_answer", ""), lesson=ctx.get("last_lesson", ""),
                       step=step_id, sources=[{k: s.get(k) for k in ("source_id", "url", "version")}
                                             for s in ctx.get("sources", [])]))


def bind_standard(task, text, spec):
    ctx = task["context"]
    old = ctx.get("check_standard") or {}
    if not text or spec is None:
        ctx.pop("check_standard", None)
        return
    reference = "\n".join(dict.fromkeys(part for part in
        [ctx.get("reference_answer", ""), ctx.get("last_lesson", ""),
         *[s.get("content", "") for s in ctx.get("sources", [])]] if part.strip()))
    if not reference:
        ctx.pop("check_standard", None)
        return
    if len(spec.must_cover) + 1 + bool(spec.order_rules.strip()) > 128:
        ctx.pop("check_standard", None)
        return
    step_id = (current_step(task) or {}).get("id")
    # Use the actual pre-answer material, including Markdown and source text.
    # Model quotations may elide or reformat it; they are not source locators.
    spec = spec.model_copy(update={"evidence": reference})
    value = dict(question=text, scoring_spec=spec.model_dump(), step_id=step_id,
                 reference_stamp=reference_stamp(ctx, step_id))
    fingerprint = digest(value)
    ctx["check_standard"] = dict(value, fingerprint=fingerprint,
                                version=old.get("version", 0) + (old.get("fingerprint") != fingerprint))


def standard_for(task, text):
    ctx = task["context"]
    value = ctx.get("check_standard")
    if not value or value.get("question") != text:
        return None
    fields = {k: value.get(k) for k in ("question", "scoring_spec", "step_id", "reference_stamp")}
    if (value.get("fingerprint") != digest(fields) or value.get("step_id") != (current_step(task) or {}).get("id") or
            value.get("reference_stamp") != reference_stamp(ctx, value.get("step_id"))):
        return None
    try:
        spec = ScoringSpec.model_validate(value["scoring_spec"])
        return spec if len(spec.must_cover) + 1 + bool(spec.order_rules.strip()) <= 128 else None
    except ValueError:
        return None


def grading_request(task, text, answer, spec):
    questions = {f"point_{i}": question(
        "依据固定 scoring_spec 和题目评价原始 answer 是否满足必需要点：" + point +
        " 允许同义表达；不替用户补全；正确与相反主张并存仍为 contradicted。",
        {"covered": "正确表达该要点。", "missing": "未表达或只有自述懂了。", "contradicted": "存在与要点相反的主张。"})
        for i, point in enumerate(spec.must_cover)}
    questions["misconception"] = question(
        "依据 scoring_spec 的核心原理和 common_misconceptions，原始答案是否包含核心误解；"
        "正确内容与错误混杂仍为 present，列表非穷尽。引用一个误解并明确反驳不算持有它。",
        {"present": "有核心误解。", "absent": "没有表达核心误解，但这不表示完整。"})
    if spec.order_rules.strip():
        questions["order"] = question("原始回答是否符合 scoring_spec.order_rules 的必要逻辑顺序。",
                                      {"satisfied": "满足。", "violated": "违反。"})
    standard = task["context"]["check_standard"]
    return JudgmentRequest(node="answer_points",
        state=dict(question=text, scoring_spec=spec.model_dump(), answer=answer),
        questions=questions, sources=[{"question_fingerprint": standard["fingerprint"],
                                     "question_version": standard["version"], "step_id": standard["step_id"]}])


def evaluate(h, sid, rid, rev, task, answer, system):
    text = task["context"].get("check_question") or task["context"].get("calibration_question") or task["content"]
    spec = standard_for(task, text)
    if spec is None:
        return None  # Never construct a rubric from an answer already received.
    request = grading_request(task, text, answer, spec)
    result = h.judgments.judge(h, sid, rid, rev, request)
    labels = dict(result.labels) if result.status in {"ok", "uncertain"} else {}
    pending = {k: q for k, q in request.questions.items() if labels.get(k, "unsure") == "unsure"}
    if pending:
        schema = create_model("PointJudgmentFallback",
            **{k: (Literal[tuple(q.criteria)], ...) for k, q in pending.items()})
        fixed = h._call(sid, rid, rev, "evaluate_points",
            "按固定题目标准逐项评价原始答案，只回答指定项。保留不确定性，不改变标准，不补写用户答案。",
            json.dumps(dict(state=request.state, questions={k: q.model_dump() for k, q in pending.items()}),
                       ensure_ascii=False), schema)
        labels.update(fixed.model_dump())
    h.judgments.disposition(h, sid, rid, rev, result, applied=result.status == "ok" or bool(set(result.labels) - set(pending)),
                            reason="llm_point_fallback" if pending else "")
    passed = (all(labels.get(f"point_{i}") == "covered" for i in range(len(spec.must_cover))) and
              labels.get("misconception") == "absent" and
              (not spec.order_rules.strip() or labels.get("order") == "satisfied"))
    effective = passed and not task["context"].get("hint_used", False)
    from agent_service.knowledge_invitation import unoffered_concepts
    from agent_service.learning_progress import bound_check
    data, _ = h._snapshot(sid, rid, rev)
    capture_concepts = unoffered_concepts(data, task['task_id'], bound_check(task))
    feedback = h._call(sid, rid, rev, "evaluate",
        "依据程序提供的逐项结论和 effective_passed 生成解释反馈，不重新判定通过，不升级掌握状态。"
        "未知项明确说明尚不能验证。使用提示时不称独立通过。若题面条件不足或超出已教范围，"
        "即使逐项看似覆盖也将 question_validity 标为 ambiguous/out_of_scope，不判用户错误。" + system + FOLLOWUP_RULE + CAPTURE_QUOTE_RULE,
        json.dumps(dict(question=text, answer=answer, scoring_spec=spec.model_dump(),
                        judgments=labels, effective_passed=effective, hint_used=task["context"].get("hint_used", False),
                        checked_concepts=spec.must_cover, capture_concepts=capture_concepts, reference=check_reference(task)),
                   ensure_ascii=False), JudgmentFeedback)
    with h.store.transaction(sid, rid, rev) as data:
        data["runs"][rid]["point_evaluation"] = dict(labels=labels, passed=passed, effective_passed=effective,
            standard_fingerprint=task["context"]["check_standard"]["fingerprint"], llm_fallback_items=list(pending))
    return ScoredMasteryEvaluation(passed=passed and feedback.question_validity == "valid", **feedback.model_dump())
