"""Explicit, versioned whole-step checks; ordinary questions prove concepts only."""
from copy import deepcopy
import re

from agent_service.learning_progress import bound_check, bind_check, current_step, step_target, comprehensive_bound


def explicit_request(decision, last):
    request = decision.comprehensive_check
    if (not request or not set(decision.intents) <= {"question", "followup", "goal"}
            or decision.conversation_kind != "ordinary" or decision.relation == "new_topic"
            or decision.proposed_actions or decision.requested_mode or last.get("operation")
            or decision.conversation_repair or decision.reply_feedback == "response_only"
            or decision.knowledge_card_status or decision.topic_closure or decision.clarification
            or decision.programming_boundary != "none" or decision.resource_boundary != "none"
            or decision.is_jd or decision.material_focus == "product"
            or decision.needs_verification or decision.refresh_sources or decision.cross_check_sources):
        return False
    evidence, text = request.evidence, last["content"]
    start = text.find(evidence)
    clause = (re.split(r"[。！？!?;；\n]", text[:start])[-1] + evidence
              + re.split(r"[。！？!?;；\n]", text[start + len(evidence):])[0]) if start >= 0 else ""
    if start < 0 or re.search(r"不要|先别|不做|不需要|不用|别检查|don't|not |unless|如果|除非", clause, re.I):
        return False
    quoted = re.findall(r'https?://\S+|```[\s\S]*?```|“[^”]*”|‘[^’]*’|「[^」]*」|"[^"]*"|^>.*$', text, re.M)
    return not any(evidence in span for span in quoted)


def prepare(data, run, request):
    task = data["tasks"].get(run.get("task_id"))
    if not task or task["task_id"] != data.get("active_task_id"):
        return None
    ctx = task["context"]
    step = current_step(task)
    target = step_target(task) or {}
    base = bound_check(task)
    if not base and not ctx.get("check_question") and ctx.get("practice"):
        # Feedback-only recovery does not erase the question actually evaluated.
        # Reuse it solely as source basis after all current version checks pass;
        # the new user's request grants fresh comprehensive permission.
        prior = ctx["practice"][-1].get("binding")
        if prior:
            projected = deepcopy(task)
            projected["context"].update(check_binding=prior, check_question=prior.get("question", ""))
            base = bound_check(projected)
    condition = target.get("completion_condition", "")
    from agent_service.learning_progress import completion_requirements
    if (ctx.get("requires_mastery") or ctx.get("memory_invalidated")
            or not step or step["id"] != request["step_id"]
            or step.get("state") not in {"explained", "verified"}
            or not condition.strip() or len(completion_requirements(condition)) > 32 or not base):
        return None
    return dict(task_id=task["task_id"], step_id=step["id"],
        plan_version=ctx["learning_plan"]["version"], reference_stamp=base["reference_stamp"],
        condition=condition, question="请用自己的话逐项完成本节的要求：\n\n" + condition,
        proposal=dict(step_title=step["title"], concepts=base["concepts"],
                      evidence_quotes=base["evidence_quotes"], scope="step"),
        request=deepcopy(request), request_message_id=run["input_ids"][-1], request_run_id=run["run_id"])


def activate(data, run, prepared):
    """Called inside the same transaction that publishes the question."""
    current = prepare(data, run, prepared["request"])
    if current != {k: v for k, v in prepared.items() if k != "scoring_spec"}:
        raise RuntimeError("RT.CHECK.STALE_CONTEXT")
    task = data["tasks"][prepared["task_id"]]
    ctx = task["context"]
    ctx["check_question"] = prepared["question"]
    binding = bind_check(task, prepared["question"], prepared["proposal"], comprehensive=True)
    if binding is None:
        raise RuntimeError("RT.CHECK.STALE_CONTEXT")
    binding.update(request_message_id=prepared["request_message_id"],
                   request_run_id=prepared["request_run_id"], request_evidence=prepared["request"]["evidence"])
    if not comprehensive_bound(binding):
        raise RuntimeError("RT.CHECK.STALE_CONTEXT")
    ctx["hint_used"] = False
    from agent_service.judgment_grading import bind_standard
    from agent_service.schemas import ScoringSpec
    spec = prepared.get("scoring_spec")
    bind_standard(task, prepared["question"], ScoringSpec.model_validate(spec) if spec else None)
    run["comprehensive_check"] = deepcopy(prepared)
    return prepared["question"]


def handle(h, sid, rid, rev, decision, last):
    if not explicit_request(decision, last):
        return False
    data, run = h._snapshot(sid, rid, rev)
    task = h._task(data, run)
    if task and task["context"].get("requires_mastery"):
        h._publish(sid, rid, rev, "这个问题沿用独立作答和迁移追问的检查方式。请先完成当前题目；本次请求不会直接标记为已攻克。")
        return True
    prepared = prepare(data, run, decision.comprehensive_check.model_dump())
    if prepared is None:
        h._publish(sid, rid, rev, "当前这一节还缺少对应的完整讲解、有效完成要求或检查依据。可以先补讲这一节，再做综合检查；原题和学习进度保留。")
        return True
    if h.judgments is not None:
        # Preserve the opt-in experiment's pre-publication question/rubric gate.
        from agent_service.judgment_quality import checked_question
        from agent_service.learning_progress import check_reference
        from agent_service.schemas import ScoringSpec
        spec = ScoringSpec(learning_goal=current_step(task)["title"],
                           must_cover=[prepared["condition"]], evidence=check_reference(task))
        question, spec = checked_question(h, sid, rid, rev, prepared["question"], spec,
                                         check_reference(task), owner=task["task_id"])
        if question != prepared["question"] or spec is None:
            raise RuntimeError("RT.QUESTION.QUALITY_UNRESOLVED")
        prepared["scoring_spec"] = spec.model_dump()
    h._publish(sid, rid, rev, "", comprehensive=prepared)
    return True
