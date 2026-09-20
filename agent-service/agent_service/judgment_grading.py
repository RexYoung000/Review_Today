"""Freeze a rubric before an answer; program logic, not a model score, passes it."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, create_model

from agent_service.judgment_types import JudgmentRequest, digest, question
from agent_service.learning_progress import current_step
from agent_service.schemas import (ScoringSpec, ConversationOutput, QuestionAnalysis,
                                  ProblemCoachBundle, MasteryEvaluation)


class ScoredConversationOutput(ConversationOutput):
    check_scoring_spec: ScoringSpec | None = None


class ScoredQuestionAnalysis(QuestionAnalysis):
    check_scoring_spec: ScoringSpec | None = None


class ScoredProblemCoachBundle(ProblemCoachBundle):
    analysis: ScoredQuestionAnalysis


class ScoredMasteryEvaluation(MasteryEvaluation):
    followup_scoring_spec: ScoringSpec | None = None


class JudgmentFeedback(BaseModel):
    correctness: str
    completeness: str
    expression: str
    transfer: str
    feedback: str
    followup_question: str = ""
    followup_scoring_spec: ScoringSpec | None = None


RUBRIC_RULE = """
出知识检查题时同时生成 check_scoring_spec：learning_goal、must_cover 必需要点、
acceptable_paraphrases 同义表达、common_misconceptions 核心误解、evidence 逐字摘录本轮讲解或已有参考材料。
标准仅包含本题必需内容，不把未问内容作为必需要点；order_rules 仅在顺序影响正确性时填写。
开放式用途/偏好澄清或没有检查题时标准为 null。标准在看到用户答案前固定。
"""

FOLLOWUP_RULE = """
生成 followup_question 时同时给 followup_scoring_spec，包含该题的必需要点、允许同义表达和核心误解；
evidence 逐字取本次给出的教学参考材料。没有足够材料制定标准时返回 null，不猜测。
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
    feedback = h._call(sid, rid, rev, "evaluate",
        "依据程序提供的逐项结论和 effective_passed 生成解释反馈，不重新判定通过，不升级掌握状态。"
        "未知项明确说明尚不能验证。使用提示时不称独立通过。" + FOLLOWUP_RULE,
        json.dumps(dict(question=text, answer=answer, scoring_spec=spec.model_dump(),
                        judgments=labels, effective_passed=effective, hint_used=task["context"].get("hint_used", False),
                        reference=task["context"].get("reference_answer") or task["context"].get("last_lesson", "")),
                   ensure_ascii=False), JudgmentFeedback)
    with h.store.transaction(sid, rid, rev) as data:
        data["runs"][rid]["point_evaluation"] = dict(labels=labels, passed=passed, effective_passed=effective,
            standard_fingerprint=task["context"]["check_standard"]["fingerprint"], llm_fallback_items=list(pending))
    return ScoredMasteryEvaluation(passed=passed, **feedback.model_dump())
