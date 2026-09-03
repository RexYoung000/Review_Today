from __future__ import annotations

import re
import time
import uuid
from typing import Any

from agent_service.capture import RISK_RULE, find_source_candidates, run_capture
from agent_service.capture.fetch import fetch_public_url, looks_like_url
from agent_service.config import COACH_MODEL, RISK_MODEL, ROUTER_MODEL
from agent_service.harness_store import HarnessTaskRecord, harness_store, now_iso
from agent_service.openai_client import parse_model, web_search_text
from agent_service.schemas import (
    CoachTurnOutput,
    JDAnalysis,
    MasteryEvaluation,
    ModeDecision,
    ProblemCoachBundle,
    SourcePack,
    SourcePackItem,
    TaskActionRequest,
)


MODE_LABELS = {
    "memory_organization": "知识整理",
    "source_learning": "资料学习",
    "topic_exploration": "主题探索",
    "problem_solving": "问题攻克",
}

QUESTION_HINT = re.compile(r"(\?|？|为什么|是什么|如何|怎么|请解释|面试题|请问|区别|作用|原理)", re.I)
LEARN_HINT = re.compile(r"(想学|学习|了解|入门|掌握|不懂|不了解|讲解)", re.I)
TEACH_HINT = re.compile(r"(不懂|不了解|不理解|讲解|教我|看不明白|帮我理解)", re.I)
JD_HINT = re.compile(r"(^|\s)(JD|job description)(\s|$)|岗位职责|职位要求|任职要求|岗位要求|工作职责", re.I)


ROUTER_SYSTEM = """你是 Review Today 学习教练的轻量路由器。只判断用户当前学习目标应进入哪条受控工作流。
memory_organization=用户已经理解材料，希望形成记忆；source_learning=用户有资料但不理解；
topic_exploration=用户只有主题没有资料；problem_solving=具体问题、面试题、面经或 JD。
不要回答问题。输出简短可解释理由。没有足够证据时 relation 使用 uncertain。"""

RELATION_SYSTEM = """你是 Review Today 的 Session 边界判断器。根据当前输入与同一 Session 的摘要和近期消息，
判断它是 continuation、related_subtopic、new_topic 或 uncertain。只有主题目标明显无关时才用 new_topic；
自然追问、回答教练问题、同主题延伸都不是 new_topic。不要回答用户问题。mode 仍按本轮最适合的学习模式填写，
reason 只给用户可理解的简短依据。"""

PROBLEM_SYSTEM = """你是专门的学习教练。针对用户的具体问题，先给一版立即可用但诚实标记假设的答案，
再建立相关知识、可能缺口和针对性学习顺序。不要声称用户已经掌握。calibration_question 每次只问一个最影响答案深度的问题。
若是面试问题，spoken_answer 给出自然口头表达；否则可为空。使用用户主语言。"""

JD_SYSTEM = """你是学习教练。分析用户粘贴的 JD，只输出岗位目标、能力地图、风险点和按面试价值排序的问题清单。
不要一次回答所有问题，不要编造企业内部要求。使用用户主语言。"""

SOURCE_LEARNING_SYSTEM = """你是学习教练。基于用户提供的资料做一次短而清晰的分段讲解。
指出本段学习目标、核心解释、资料边界，并在结尾给一个小型理解检查。不要自动生成长期记忆，使用用户主语言。"""

MASTERY_SYSTEM = """你是问题攻克模式的验收教练。比较用户独立回答与问题及参考内容，
分别判断正确性、完整性、表达和迁移能力。标准应严格但不苛刻。只有用户能脱离参考答案回答核心问题时 passed=true。
未通过时 followup_question 只追问一个最关键缺口；通过时留空。使用用户主语言。"""


def _context_text(record: HarnessTaskRecord) -> str:
    context = record.context or {}
    parts: list[str] = []
    if context.get("summary"):
        parts.append(f"Session 摘要：{context['summary'][:6000]}")
    recent = context.get("recent_messages") or []
    if recent:
        rendered = "\n".join(f"{item.get('role')}: {item.get('content', '')[:2000]}" for item in recent[-10:])
        parts.append(f"近期对话：\n{rendered}")
    knowledge = context.get("knowledge_summaries") or []
    if knowledge:
        parts.append("相关既有知识：\n" + "\n".join(f"- {item[:1000]}" for item in knowledge[:5]))
    return "\n\n".join(parts)


def classify_mode(record: HarnessTaskRecord) -> ModeDecision:
    text = record.content.strip()
    heuristic: ModeDecision | None = None
    if JD_HINT.search(text):
        heuristic = ModeDecision(mode="problem_solving", confidence=0.98, reason="检测到岗位职责或任职要求", relation="continuation")
    elif QUESTION_HINT.search(text):
        heuristic = ModeDecision(mode="problem_solving", confidence=0.94, reason="输入包含需要直接回答的具体问题", relation="continuation")
    elif TEACH_HINT.search(text) and (looks_like_url(text) or len(text) > 180):
        heuristic = ModeDecision(mode="source_learning", confidence=0.9, reason="用户希望理解已经提供的资料", relation="continuation")
    elif LEARN_HINT.search(text) and len(text) < 220 and not looks_like_url(text):
        heuristic = ModeDecision(mode="topic_exploration", confidence=0.92, reason="用户表达了学习主题，但尚未提供资料", relation="continuation")
    elif len(text) > 220 or looks_like_url(text):
        heuristic = ModeDecision(mode="memory_organization", confidence=0.86, reason="输入主要是一段可整理的学习材料", relation="continuation")

    declined = bool((record.context or {}).get("mode_switch_declined"))
    if record.mode_preset != "auto" and heuristic and heuristic.mode != record.mode_preset and not declined:
        heuristic.suggest_switch = True
        heuristic.reason = f"当前输入更符合{MODE_LABELS[heuristic.mode]}；Session 预设仍保持{MODE_LABELS[record.mode_preset]}，等待用户确认"
        return heuristic
    if record.mode_preset != "auto":
        return ModeDecision(
            mode=record.mode_preset,
            confidence=1,
            reason=f"本 Session 已预设为{MODE_LABELS[record.mode_preset]}",
            relation="continuation",
        )
    if heuristic:
        return heuristic

    prompt = f"用户主语言：{record.primary_language}\n输入：{text}\n\n{_context_text(record)}"
    return ModeDecision.model_validate(parse_model(ROUTER_SYSTEM, prompt, ModeDecision, model=ROUTER_MODEL).model_dump())


def assess_relation(record: HarnessTaskRecord, decision: ModeDecision) -> ModeDecision:
    """Use the router only when this turn actually has prior Session context."""
    context = record.context or {}
    if context.get("relation_declined"):
        return decision
    if not context.get("summary") and not (context.get("recent_messages") or []):
        return decision
    prompt = (
        f"用户主语言：{record.primary_language}\n当前输入：{record.content.strip()}\n"
        f"当前模式判断：{decision.mode}\n\n{_context_text(record)}"
    )
    try:
        relation = ModeDecision.model_validate(
            parse_model(RELATION_SYSTEM, prompt, ModeDecision, model=ROUTER_MODEL).model_dump()
        )
    except Exception:  # noqa: BLE001 - relation advice must never block the learning task
        return decision
    if relation.relation == "new_topic" and relation.confidence >= 0.85:
        decision.relation = "new_topic"
        decision.confidence = relation.confidence
        if relation.reason.strip():
            decision.reason = relation.reason.strip()
    else:
        decision.relation = "uncertain" if relation.relation == "new_topic" else relation.relation
    return decision


def _coach_message(record: HarnessTaskRecord, content: str) -> dict[str, Any]:
    return {
        "message_id": str(uuid.uuid4()),
        "role": "coach",
        "content": content.strip(),
        "created_at": now_iso(),
    }


def _emit(
    record: HarnessTaskRecord,
    *,
    stage: str,
    state: str,
    node: str,
    summary: str,
    detail: str = "",
    duration_ms: int | None = None,
    required_action: dict[str, Any] | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    error_code: str | None = None,
    recovery_action: str | None = None,
) -> None:
    current = harness_store.get(record.task_id)
    if current is not None and current.status == "cancelled" and state != "cancelled":
        return
    harness_store.append_event(
        record.task_id,
        stage=stage,
        state=state,
        node=node,
        user_summary=summary,
        detail_summary=detail,
        duration_ms=duration_ms,
        required_action=required_action,
        message=_coach_message(record, message) if message else None,
        payload=payload,
        error_code=error_code,
        recovery_action=recovery_action,
    )


def _update(task_id: str, **values: Any) -> HarnessTaskRecord:
    def apply(record: HarnessTaskRecord) -> None:
        for key, value in values.items():
            setattr(record, key, value)

    updated = harness_store.mutate(task_id, apply)
    if updated is None:
        raise RuntimeError("RT.TASK.UNKNOWN")
    return updated


def _topic_exploration(record: HarnessTaskRecord) -> None:
    action = {
        "type": "respond",
        "prompt": "先明确一个学习目标",
        "options": [],
    }
    message = (
        f"我先把「{record.content.strip()[:100]}」收窄成一个能学完的目标。\n\n"
        "你最希望学完后能够做什么？例如：理解基本原理、能在项目中落地，或能回答相关面试题。"
    )
    _emit(
        record,
        stage="clarify_goal",
        state="awaiting_user",
        node="topic_goal",
        summary="等你明确学习目标",
        detail="主题探索先收窄目标，再建立资料包。",
        required_action=action,
        message=message,
    )


def _load_source(content: str) -> tuple[str, str]:
    url = looks_like_url(content)
    if not url:
        return content, "用户提供的文字"
    title, body = fetch_public_url(url)
    return f"{title}\n\n{body}", url


def _source_learning(record: HarnessTaskRecord) -> None:
    started = time.monotonic()
    source, locator = _load_source(record.content)
    _emit(
        record,
        stage="teaching",
        state="running",
        node="lesson_step",
        summary="正在拆解资料并准备讲解",
        detail=f"资料定位：{locator}",
    )
    prompt = (
        f"用户主语言：{record.primary_language}\n资料定位：{locator}\n\n资料：\n{source[:16000]}\n\n"
        f"{_context_text(record)}"
    )
    output = CoachTurnOutput.model_validate(
        parse_model(SOURCE_LEARNING_SYSTEM, prompt, CoachTurnOutput, model=COACH_MODEL).model_dump()
    )
    action = {
        "type": "confirm_understanding",
        "prompt": "这一段你已经理解了吗？",
        "options": ["我理解了", "还有疑问"],
    }
    _emit(
        record,
        stage="teaching",
        state="awaiting_user",
        node="lesson_step",
        summary="已完成一段讲解，等你确认",
        detail=f"资料定位：{locator}",
        duration_ms=int((time.monotonic() - started) * 1000),
        required_action=action,
        message=output.message,
        payload={"evidence_state": output.evidence_state},
    )


def _render_problem(bundle: ProblemCoachBundle) -> str:
    answer = bundle.answer
    gaps = bundle.gap_map
    plan = bundle.learning_plan
    sections = [f"先给你一版可直接使用的答案：\n\n{answer.direct_answer}"]
    if answer.spoken_answer.strip():
        sections.append(f"面试口头表达版：\n\n{answer.spoken_answer}")
    if answer.assumptions:
        sections.append("这版答案的关键假设：\n" + "\n".join(f"- {item}" for item in answer.assumptions))
    sections.append("相关知识点：\n" + "\n".join(f"- {item}" for item in gaps.related_knowledge))
    if gaps.likely_gaps:
        sections.append("你可能需要补齐：\n" + "\n".join(f"- {item}" for item in gaps.likely_gaps))
    sections.append("针对性学习顺序：\n" + "\n".join(f"{idx}. {item}" for idx, item in enumerate(gaps.learning_order, 1)))
    sections.append(f"先校准一个问题：\n\n{bundle.analysis.calibration_question}")
    return "\n\n".join(sections)


def _problem_solving(record: HarnessTaskRecord) -> None:
    if JD_HINT.search(record.content) and not any(item.get("action_type") == "select_question" for item in record.action_history):
        started = time.monotonic()
        _emit(
            record,
            stage="jd_analysis",
            state="running",
            node="analyze_jd",
            summary="正在拆解岗位要求和优先问题",
        )
        analysis = JDAnalysis.model_validate(
            parse_model(
                JD_SYSTEM,
                f"用户主语言：{record.primary_language}\n\nJD：\n{record.content[:20000]}",
                JDAnalysis,
                model=COACH_MODEL,
            ).model_dump()
        )
        questions = analysis.prioritized_questions
        message = (
            f"岗位目标\n\n{analysis.role_goal}\n\n"
            "能力地图\n" + "\n".join(f"- {item}" for item in analysis.competency_map) + "\n\n"
            "需要优先关注\n" + ("\n".join(f"- {item}" for item in analysis.risk_points) or "- 暂未发现额外风险") + "\n\n"
            "建议逐题攻克\n" + "\n".join(f"{idx}. {item}" for idx, item in enumerate(questions, 1))
        )
        action = {"type": "choose_question", "prompt": "先选择一道要攻克的问题", "options": questions}
        _emit(
            record,
            stage="jd_analysis",
            state="awaiting_user",
            node="analyze_jd",
            summary="已拆解 JD，等你选题",
            duration_ms=int((time.monotonic() - started) * 1000),
            required_action=action,
            message=message,
            payload={"jd_analysis": analysis.model_dump()},
        )
        return

    started = time.monotonic()
    evidence_text = ""
    evidence_state = "unverified"
    if RISK_RULE.search(record.content):
        _emit(
            record,
            stage="evidence_check",
            state="running",
            node="risk_search",
            summary="正在核对高风险或时效信息",
            detail="问题命中风险规则，使用高风险模型角色和公开检索。",
        )
        evidence_text = web_search_text(f"核验并回答：{record.content[:2000]}", model=RISK_MODEL)
        evidence_state = "supported" if evidence_text else "insufficient"
    prompt = (
        f"用户主语言：{record.primary_language}\n问题：{record.content}\n"
        f"证据状态：{evidence_state}\n公开检索摘录：{evidence_text[:8000]}\n\n{_context_text(record)}"
    )
    _emit(
        record,
        stage="answering",
        state="running",
        node="problem_answer",
        summary="正在准备基础答案和针对性学习路径",
        detail=f"证据状态：{evidence_state}",
    )
    bundle = ProblemCoachBundle.model_validate(
        parse_model(PROBLEM_SYSTEM, prompt, ProblemCoachBundle, model=COACH_MODEL).model_dump()
    )
    bundle.answer.evidence_state = evidence_state
    calibrated = any(item.get("action_type") == "respond" for item in record.action_history)
    action = (
        {
            "type": "submit_answer",
            "prompt": "请先不看上面的答案，用自己的话回答一次。",
            "options": [],
        }
        if calibrated
        else {
            "type": "respond",
            "prompt": bundle.analysis.calibration_question,
            "options": [],
        }
    )
    _emit(
        record,
        stage="practice" if calibrated else "calibration",
        state="awaiting_user",
        node="problem_answer",
        summary="已给出答案和学习路径，等你独立作答" if calibrated else "已给出基础答案，等你补充一个背景",
        detail=f"证据状态：{evidence_state}",
        duration_ms=int((time.monotonic() - started) * 1000),
        required_action=action,
        message=_render_problem(bundle),
        payload={"problem_bundle": bundle.model_dump()},
    )


def _form_memory(record: HarnessTaskRecord, *, force_source_view: bool | None = None) -> None:
    coach_messages = [
        event.get("message", {}).get("content", "")
        for event in record.events
        if event.get("message") and event.get("message", {}).get("content")
    ]
    if record.mode == "memory_organization":
        source_text = record.content
        use_source_view = False if force_source_view is None else force_source_view
    else:
        source_text = "\n\n".join([record.content, *coach_messages]).strip()
        use_source_view = True if force_source_view is None else force_source_view
    _emit(
        record,
        stage="memory_generation",
        state="running",
        node="memory_builder",
        summary="正在形成记忆",
        detail="使用现有知识卡结构、语义和来源校验。",
    )
    result = run_capture(
        record.task_id,
        source_text,
        record.primary_language,
        force_source_view=use_source_view,
        model=COACH_MODEL,
        risk_model=RISK_MODEL,
    )
    payload = result.get("extracted")
    if result.get("outcome") == "needs_attention":
        required = {
            "type": "resolve_conflict",
            "prompt": "内容存在冲突或证据不足，请决定如何处理",
            "options": ["作为资料观点", "按有限范围采用", "保持暂停"],
        }
        _emit(
            record,
            stage="knowledge_conflict",
            state="needs_attention",
            node="evidence_conflict",
            summary="发现知识冲突，已暂停写入",
            detail=result.get("verify_reason") or "没有足够证据直接写入正式记忆。",
            required_action=required,
            message="这段内容与可核验信息存在冲突或证据不足，我已暂停形成记忆。请决定把它作为资料观点、按有限范围采用，或继续保持暂停。",
            error_code=result.get("error_code") or "RT.KNOWLEDGE.CONFLICT",
            recovery_action="resolve_conflict",
        )
        return
    if result.get("outcome") != "committing" or not payload:
        raise RuntimeError(result.get("error_code") or "RT.TASK.MEMORY_FAILED")
    _update(
        record.task_id,
        memory_package=payload,
        memory_source_text=source_text,
        result_summary=f"已准备 {len(payload.get('knowledge') or [])} 条记忆，等待 Mac 保存",
    )
    _emit(
        record,
        stage="committing",
        state="committing",
        node="memory_commit",
        summary="记忆已准备，等待本机保存",
        detail="Mac 保存并 ACK 后任务才完成。",
        payload={"knowledge_ids": [item.get("id") for item in payload.get("knowledge") or []]},
    )


def process_task(task_id: str) -> None:
    record = harness_store.get(task_id)
    if record is None or record.status not in {"accepted", "queued", "running", "retryable_failed"}:
        return
    try:
        _emit(
            record,
            stage="routing",
            state="running",
            node="mode_router",
            summary="正在理解你的目标",
            detail="结合 Session 预设、当前输入和受限上下文选择一条工作流。",
        )
        record = harness_store.get(task_id) or record
        decision = assess_relation(record, classify_mode(record))
        record = _update(task_id, mode=decision.mode)
        _emit(
            record,
            stage="routing",
            state="running",
            node="mode_router",
            summary=f"已进入{MODE_LABELS[decision.mode]}",
            detail=decision.reason,
            payload={"mode_decision": decision.model_dump()},
        )
        if decision.relation == "new_topic" and decision.confidence >= 0.85:
            context = {
                **record.context,
                "proposed_new_session": True,
                "proposed_mode": decision.mode,
            }
            record = _update(task_id, context=context)
            required = {
                "type": "confirm_new_session",
                "prompt": "这看起来是一个新主题，要在新的 Session 中继续吗？",
                "options": ["新建 Session", "留在当前 Session"],
            }
            _emit(
                record,
                stage="confirm_session",
                state="awaiting_user",
                node="session_boundary",
                summary="发现无关新主题，等你决定放在哪里",
                detail=decision.reason,
                required_action=required,
                message="这条输入与当前 Session 的学习目标明显不同。建议新建 Session，避免旧上下文影响回答；是否新建由你决定。",
            )
            return
        if decision.suggest_switch:
            context = {**record.context, "proposed_mode": decision.mode}
            record = _update(task_id, context=context)
            required = {
                "type": "confirm_mode_switch",
                "prompt": f"这条内容更适合{MODE_LABELS[decision.mode]}，要切换吗？",
                "options": [f"切换到{MODE_LABELS[decision.mode]}", f"保持{MODE_LABELS[record.mode_preset]}"],
            }
            _emit(
                record,
                stage="confirm_mode",
                state="awaiting_user",
                node="mode_switch_confirmation",
                summary="发现更合适的模式，等你确认",
                detail="未自动切换 Session 模式。",
                required_action=required,
                message=f"这条输入更符合{MODE_LABELS[decision.mode]}。是否只为当前任务切换？Session 原预设不会被静默改变。",
            )
            return
        record = harness_store.get(task_id) or record
        if decision.mode == "topic_exploration":
            _topic_exploration(record)
        elif decision.mode == "source_learning":
            _source_learning(record)
        elif decision.mode == "problem_solving":
            _problem_solving(record)
        else:
            _form_memory(record)
    except Exception as exc:  # noqa: BLE001
        current = harness_store.get(task_id) or record
        retry_count = current.retry_count + 1
        status = "retryable_failed" if retry_count <= 3 else "terminal_failed"
        code = str(exc) if str(exc).startswith("RT.") else "RT.TASK.MODEL_FAILED"
        _update(task_id, retry_count=retry_count)
        _emit(
            current,
            stage="failed",
            state=status,
            node=current.stage or "harness",
            summary="暂时无法继续" if status == "retryable_failed" else "当前任务无法继续",
            detail="模型、资料或结构化输出未能完成当前步骤。",
            error_code=code,
            recovery_action="retry" if status == "retryable_failed" else "review_details",
        )


def _source_path_response(record: HarnessTaskRecord, action: TaskActionRequest) -> None:
    goal = action.content.strip() or action.selection.strip()
    if record.stage == "clarify_goal":
        _update(record.task_id, result_summary=f"学习目标：{goal}")
        required = {
            "type": "respond",
            "prompt": "请选择资料来源",
            "options": ["粘贴材料", "提供链接", "Agent 查找资料"],
        }
        _emit(
            record,
            stage="choose_source",
            state="awaiting_user",
            node="source_choice",
            summary="目标已明确，等你选择资料来源",
            required_action=required,
            message="目标已经更清楚了。接下来你可以粘贴一段材料、提供公开链接，或者让我先找 2–4 个互补来源。",
        )
        return
    choice = action.selection.strip() or action.content.strip()
    if "查找" in choice:
        _emit(record, stage="source_search", state="running", node="source_search", summary="正在查找资料")
        goal = record.result_summary.removeprefix("学习目标：").strip()
        subject = re.sub(r"^(我)?(想|希望)?(了解|学习|掌握|入门)\s*", "", record.content.strip(), flags=re.I)
        query = f"主题：{subject[:160]}；学习目标：{goal[:240]}" if goal else subject[:320]
        candidates = find_source_candidates(query, model=COACH_MODEL)
        if not candidates:
            required = {
                "type": "respond",
                "prompt": "联网查找暂不可用，请粘贴材料或公开链接",
                "options": ["粘贴材料", "提供链接"],
            }
            _emit(
                record,
                stage="awaiting_material",
                state="awaiting_user",
                node="source_search_unavailable",
                summary="没有找到可核验来源，等你提供资料",
                detail="未用猜测链接填充资料包；当前任务和学习目标均已保留。",
                required_action=required,
                message="这次没有拿到可核验的公开来源，我不会用猜测链接充数。请粘贴材料或提供公开链接，我会从这里继续。",
                error_code="RT.SOURCE.SEARCH_UNAVAILABLE",
                recovery_action="provide_source",
            )
            return
        if len(candidates) < 2:
            required = {
                "type": "respond",
                "prompt": "可靠来源不足，请再提供一段材料或公开链接",
                "options": ["粘贴材料", "提供链接"],
            }
            _emit(
                record,
                stage="awaiting_material",
                state="awaiting_user",
                node="source_pack_incomplete",
                summary="可核验来源不足，等你补充资料",
                detail="主题探索需要 2–4 个互补来源；当前结果未达到资料包门槛。",
                required_action=required,
                message="目前只找到不足两个可核验来源，不能组成可靠资料包。请补充材料或公开链接，我会从已确认的学习目标继续。",
                error_code="RT.SOURCE.PACK_INCOMPLETE",
                recovery_action="provide_source",
            )
            return
        purposes = ["建立权威基础", "理解实现方法", "补充评估方法", "识别限制与争议"]
        pack = SourcePack(
            topic=goal or subject,
            sources=[
                SourcePackItem(
                    title=item.title or item.url,
                    purpose=purposes[index],
                    url=item.url,
                    date_or_version="来源未标注，学习前确认",
                    scope="公开网页；具体版本与适用范围待核对",
                    snippet=item.snippet,
                    evidence_state="unverified",
                )
                for index, item in enumerate(candidates[:4])
            ],
        )
        options = [item.url for item in pack.sources]
        required = {"type": "choose_sources", "prompt": "确认用于学习的资料", "options": options}
        message = "我先整理了一个小型资料包：\n\n" + "\n".join(
            f"- {item.title}\n  用途：{item.purpose}\n  日期/版本：{item.date_or_version}\n"
            f"  范围：{item.scope}\n  定位：{item.url}\n  状态：尚待你确认"
            for item in pack.sources
        )
        _emit(
            record,
            stage="source_confirmation",
            state="awaiting_user",
            node="source_pack",
            summary="资料包已准备，等你确认",
            required_action=required,
            message=message,
            payload={"source_pack": [item.model_dump() for item in pack.sources]},
        )
        return
    required = {"type": "respond", "prompt": "请发送材料或公开链接", "options": []}
    _emit(
        record,
        stage="awaiting_material",
        state="awaiting_user",
        node="source_input",
        summary="等你提供学习材料",
        required_action=required,
        message="请直接粘贴材料或公开链接。我会基于它分段讲解，并标出资料边界。",
    )


def _evaluate_answer(record: HarnessTaskRecord, answer: str) -> None:
    reference = next(
        (
            event.get("message", {}).get("content", "")
            for event in reversed(record.events)
            if event.get("node") == "problem_answer" and event.get("message")
        ),
        "",
    )
    prompt = (
        f"用户主语言：{record.primary_language}\n原问题：{record.content}\n\n"
        f"参考教学：{reference[:12000]}\n\n用户独立回答：{answer[:8000]}"
    )
    result = MasteryEvaluation.model_validate(
        parse_model(MASTERY_SYSTEM, prompt, MasteryEvaluation, model=COACH_MODEL).model_dump()
    )
    message = (
        f"正确性：{result.correctness}\n\n完整性：{result.completeness}\n\n"
        f"表达：{result.expression}\n\n迁移能力：{result.transfer}\n\n{result.feedback}"
    )
    if result.passed:
        required = {"type": "confirm_memory", "prompt": "这道问题已经通过。要形成长期记忆吗？", "options": ["形成记忆", "暂不形成"]}
        _emit(
            record,
            stage="mastered",
            state="awaiting_user",
            node="mastery_check",
            summary="已能独立作答，等你决定是否形成记忆",
            required_action=required,
            message=message,
            payload={"mastery": result.model_dump()},
        )
    else:
        required = {"type": "submit_answer", "prompt": result.followup_question or "请针对反馈再回答一次", "options": []}
        _emit(
            record,
            stage="practice",
            state="awaiting_user",
            node="mastery_check",
            summary="还有一个关键缺口，等你补充",
            required_action=required,
            message=f"{message}\n\n下一步只补这一点：{required['prompt']}",
            payload={"mastery": result.model_dump()},
        )


def process_action(task_id: str, action: TaskActionRequest) -> None:
    record = harness_store.get(task_id)
    if record is None:
        return
    failed = False
    try:
        if action.action_type == "cancel":
            _emit(record, stage="cancelled", state="cancelled", node="user_cancel", summary="任务已取消", message="这项任务已取消，Session 中的对话仍然保留。")
            return
        if action.action_type == "retry":
            _update(task_id, status="queued", error_code=None, required_action=None)
            process_task(task_id)
            return
        if record.required_action and record.required_action.get("type") == "resolve_conflict":
            choice = action.selection.strip() or action.content.strip()
            if "保持" in choice:
                _emit(
                    record,
                    stage="knowledge_conflict",
                    state="needs_attention",
                    node="conflict_paused",
                    summary="冲突内容保持暂停",
                    detail="未写入长期记忆，原始输入仍保留在 Session。",
                    message="已保持暂停，不会写入正式知识库。你之后仍可回到这条任务重新处理。",
                )
                return
            if "观点" in choice or "有限" in choice:
                _form_memory(record, force_source_view=True)
                return
        if record.required_action and record.required_action.get("type") == "confirm_mode_switch":
            proposed = (record.context or {}).get("proposed_mode")
            if action.action_type == "switch_mode" and proposed in MODE_LABELS:
                context = {key: value for key, value in record.context.items() if key not in {"proposed_mode", "mode_switch_declined"}}
                _update(task_id, mode_preset=proposed, status="queued", required_action=None, context=context)
                process_task(task_id)
                return
        if record.required_action and record.required_action.get("type") == "confirm_new_session":
            if action.action_type == "create_handoff":
                destination = action.content.strip() or action.selection.strip()
                _update(task_id, result_summary=f"已交接到新 Session：{destination}" if destination else "已交接到新 Session")
                _emit(
                    record,
                    stage="completed",
                    state="completed",
                    node="session_handoff",
                    summary="已交接到新 Session",
                    detail="原 Session 保留这条输入和交接记录；未复制完整聊天。",
                    message="已在新的 Session 中继续处理；这里保留交接记录，原上下文不会被带过去。",
                    payload={"destination_session_id": destination},
                )
                return
            if action.action_type == "continue_session":
                context = {**record.context, "relation_declined": True}
                context.pop("proposed_new_session", None)
                _update(task_id, status="queued", required_action=None, context=context)
                process_task(task_id)
                return
            if action.action_type == "continue_session":
                context = {**record.context, "mode_switch_declined": True}
                context.pop("proposed_mode", None)
                _update(task_id, status="queued", required_action=None, context=context)
                process_task(task_id)
                return
        if record.mode == "topic_exploration":
            if record.stage in {"clarify_goal", "choose_source"}:
                _source_path_response(record, action)
                return
            if record.stage == "awaiting_material":
                material = action.content.strip() or action.selection.strip()
                _update(task_id, content=material, mode="source_learning")
                _source_learning(harness_store.get(task_id) or record)
                return
            if record.stage == "source_confirmation" and action.action_type == "select_sources":
                selected = action.selection.strip() or action.content.strip()
                _update(task_id, content=selected, mode="source_learning")
                _source_learning(harness_store.get(task_id) or record)
                return
        if record.mode == "source_learning":
            if "疑问" in (action.selection + action.content):
                _update(task_id, context={**record.context, "learner_question": action.content or action.selection})
                _source_learning(harness_store.get(task_id) or record)
                return
            if action.action_type == "confirm_understanding" or "理解" in (action.selection + action.content):
                required = {"type": "confirm_memory", "prompt": "要把已经理解的内容形成长期记忆吗？", "options": ["形成记忆", "暂不形成"]}
                _emit(record, stage="understood", state="awaiting_user", node="understanding_check", summary="已确认理解，等你决定是否形成记忆", required_action=required, message="这部分已经完成理解检查。是否把它整理成长期复习卡片？")
                return
            if action.action_type == "respond":
                _update(task_id, context={**record.context, "learner_question": action.content})
                _source_learning(harness_store.get(task_id) or record)
                return
        if record.mode == "problem_solving":
            if action.action_type == "select_question":
                question = action.selection.strip() or action.content.strip()
                _update(task_id, content=question)
                _problem_solving(harness_store.get(task_id) or record)
                return
            if action.action_type == "respond" and record.stage == "calibration":
                _update(task_id, context={**record.context, "calibration_answer": action.content or action.selection})
                _problem_solving(harness_store.get(task_id) or record)
                return
            if action.action_type == "submit_answer" or record.stage == "practice":
                _evaluate_answer(record, action.content.strip() or action.selection.strip())
                return
        if action.action_type == "form_memory" or "形成记忆" in (action.selection + action.content):
            _form_memory(record)
            return
        if action.action_type == "skip_memory" or "暂不" in (action.selection + action.content):
            _update(task_id, result_summary="学习任务已完成，未写入长期记忆")
            _emit(record, stage="completed", state="completed", node="complete_without_memory", summary="学习任务已完成", message="好的，这次先不形成长期记忆。你可以继续在当前 Session 追问。")
            return
        if action.action_type == "respond":
            required = record.required_action or {"type": "respond", "prompt": "请继续", "options": []}
            _emit(record, stage=record.stage, state="awaiting_user", node="user_response", summary="已收到，等你继续", required_action=required, message="我已收到这条补充。请按当前问题继续。")
            return
        raise RuntimeError("RT.TASK.UNSUPPORTED_ACTION")
    except Exception as exc:  # noqa: BLE001
        failed = True
        current = harness_store.get(task_id) or record
        code = str(exc) if str(exc).startswith("RT.") else "RT.TASK.ACTION_FAILED"
        _emit(current, stage="failed", state="retryable_failed", node="task_action", summary="这一步没有完成，可以重试", detail="用户输入已经保留。", error_code=code, recovery_action="retry")
    finally:
        if not failed:
            def complete(item: HarnessTaskRecord) -> None:
                if action.action_id not in item.completed_action_ids:
                    item.completed_action_ids.append(action.action_id)

            harness_store.mutate(task_id, complete)


def record_action(task_id: str, action: TaskActionRequest) -> tuple[HarnessTaskRecord | None, bool]:
    duplicate = False

    def apply(record: HarnessTaskRecord) -> None:
        nonlocal duplicate
        if action.action_id in record.completed_action_ids or action.action_id in record.processed_action_ids:
            duplicate = True
            return
        record.processed_action_ids.append(action.action_id)
        record.action_history.append({**action.model_dump(), "created_at": now_iso()})

    return harness_store.mutate(task_id, apply), duplicate


def resume_incomplete_tasks() -> None:
    """Replay durable work after a local service restart without inventing a new task."""
    for record in harness_store.all_records():
        if record.context.get("conversation_managed"):
            continue
        pending_action = next(
            (
                item
                for item in record.action_history
                if item.get("action_id") not in record.completed_action_ids
            ),
            None,
        )
        if pending_action:
            try:
                process_action(record.task_id, TaskActionRequest.model_validate(pending_action))
            except Exception:  # noqa: BLE001
                continue
        elif record.status in {"accepted", "queued", "running"}:
            process_task(record.task_id)
