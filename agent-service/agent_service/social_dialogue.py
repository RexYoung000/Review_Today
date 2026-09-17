"""Bounded social acknowledgement; never a learning task or an operation grant."""
import json

from agent_service.config import ROUTER_MODEL
from agent_service.conversation_prompts import COACH_SYSTEM
from agent_service.schemas import ConversationOutput
from agent_service.source_links import bound_source_links

SOCIAL_INTENTS = {"social", "greeting", "thanks", "capabilities", "defer"}
SUPPORT_INTENTS = {"social", "question", "followup", "defer"}


def kind_for(decision, last):
    # A social label alone cannot suppress a mixed request, a bound action,
    # conversation repair, real teaching/resume, or the programming boundary.
    if (last.get("operation") or decision.proposed_actions or decision.requested_mode
            or decision.direct_teaching or decision.continuation_evidence
            or decision.conversation_repair or decision.clarification
            or decision.is_jd or decision.programming_boundary != "none" or decision.resource_boundary != "none"):
        return None
    intents = set(decision.intents)
    kind = decision.conversation_kind
    if kind in {"social", "companionship"} and intents <= SOCIAL_INTENTS:
        return kind
    if kind == "learning_support" and intents <= SUPPORT_INTENTS and intents != {"defer"} and not (
            decision.needs_verification or decision.refresh_sources or decision.cross_check_sources):
        return kind
    return None


def short_reply(data, decision, kind):
    if kind == "companionship":
        previous = next((m for m in reversed(data["messages"]) if m["role"] == "coach"), {})
        prior_run = data["runs"].get(previous.get("run_id"), {})
        if prior_run.get("social_reply_kind") == "companionship":
            return "嗯，先放松一下。想继续学习时再来就好。"
        if "defer" in decision.intents:
            return "今天不想学也没关系，可以先歇一歇。这里主要围绕学习和理解知识，想继续时再来就好。"
        return "我在。可以聊聊学习中遇到的困惑，或者最近想弄明白的事。"
    if "thanks" in decision.intents:
        return "不客气。"
    if "greeting" in decision.intents:
        return "你好。"
    reply = decision.light_reply.strip()
    if reply and len(reply) <= 120:
        return reply
    return "嗯，按自己的节奏来就好。"


def handle(h, sid, rid, rev, decision, last):
    kind = kind_for(decision, last)
    if not kind:
        return False
    data, run = h._snapshot(sid, rid, rev)
    # Capture the current learning context for advice, before detaching this
    # response. It is read-only; a suggestion is not permission to edit a plan.
    context, _ = h._context(data, run)
    with h.store.transaction(sid, rid, rev) as current:
        active = current["runs"][rid]
        active.update(intent=decision.model_dump(), decision_input_ids=list(active["input_ids"]),
                      decision_mode=current["mode"], dialogue_only=True, task_id=None,
                      social_reply_kind=kind, search_state="not_called", verification_notice="",
                      allowed_source_urls=[], learning_concepts=[], activity_candidate=None)
        h.store.event(current, active, "intent_decided",
                      "已识别为学习支持" if kind == "learning_support" else "已识别为轻量对话",
                      model=ROUTER_MODEL, detail=decision.rationale, payload={"intent": decision.model_dump()})
    if kind == "learning_support":
        context = {k: v for k, v in context.items() if k not in {
            "memory_candidates", "related_knowledge", "related_learning", "continuation_candidates"}}
        output = h._call(sid, rid, rev, "answer", COACH_SYSTEM, json.dumps(dict(context=context,
            instruction="回应当前学习困难：先简短接住感受，再给一两个可尝试的小建议，通常150–250字以内。"
                        "必要时只问一个与学习障碍直接相关的问题，不追问泛泛近况、不诊断心理状态。"
                        "这是局部支持，不是开始课程或修改计划；不宣称掌握，不检查作答，不追加保存或来源。"
                        "check_question、learning_plan、learning_concepts 留空。当前用户没有问记忆时，不复述旧的记忆范围说明。"),
            ensure_ascii=False), ConversationOutput)
        h._publish(sid, rid, rev, bound_source_links(output.message, []))
    else:
        h._publish(sid, rid, rev, short_reply(data, decision, kind))
    return True
