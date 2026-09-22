"""Bounded social acknowledgement; never a learning task or an operation grant."""
import json
import re

from agent_service.config import ROUTER_MODEL
from agent_service.conversation_prompts import COACH_SYSTEM
from agent_service.schemas import ConversationOutput
from agent_service.source_links import bound_source_links

SOCIAL_INTENTS = {"social", "greeting", "thanks", "capabilities", "defer"}
SUPPORT_INTENTS = {"social", "question", "followup", "defer"}

# Filter generated acknowledgements, never classify user requests by keywords.
# Keep a usable sentence instead of discarding it together with an invitation.
_UNSUITABLE_ACK = re.compile(
    r"随便.*聊|随时.*(?:说|聊|找我|问我|告诉我|发给我|发我)|"
    r"(?:想|要不要).*(?:聊|学什么|了解什么|梳理哪)|准备好.*继续|"
    r"(?:你|您|用户).*(?:没给|没提供|没说清|没有信息量|没有具体内容)|"
    r"提示词|系统(?:规定|设置)|内部(?:机制|设置)|路由|模型限制|没必要.*闲聊|偷懒|故意敷衍",
    re.I,
)


def bounded_reply(reply, fallback, *, allow_introduction=False):
    reply = reply.strip()
    if not reply or len(reply) > 120:
        return fallback
    # Greetings/capability questions can carry useful orientation. A response
    # complaint or simple thanks must not turn into another product pitch.
    if not allow_introduction and re.search(r"学习教练|Review\s*Today", reply, re.I):
        return fallback
    sentences = re.findall(r"[^。！？.!?；;～~\n]+[。！？.!?；;～~]?", reply)
    kept = [sentence for sentence in sentences
            if not re.search(r"[?？]", sentence) and not _UNSUITABLE_ACK.search(sentence)]
    return "".join(kept).strip() or fallback


def kind_for(decision, last):
    # A social label alone cannot suppress a mixed request, a bound action,
    # conversation repair, real teaching/resume, or the programming boundary.
    if (last.get("operation") or decision.proposed_actions or decision.requested_mode
            or decision.direct_teaching or decision.continuation_evidence
            or decision.conversation_repair or decision.reply_feedback != "none" or decision.clarification
            or decision.is_jd or decision.programming_boundary != "none" or decision.resource_boundary != "none"):
        return None
    intents = set(decision.intents)
    kind = decision.conversation_kind
    if kind == 'background' and intents == {'social'} and decision.scope == 'conversation' and not (
            decision.workflow or decision.needs_verification or decision.refresh_sources or decision.cross_check_sources):
        return kind
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
    fallback = "不客气。" if "thanks" in decision.intents else "你好。" if "greeting" in decision.intents else "嗯，按自己的节奏来就好。"
    return bounded_reply(decision.light_reply, fallback,
                         allow_introduction=bool(set(decision.intents) & {"greeting", "capabilities"}))


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
    if kind == 'background':
        reply = decision.light_reply.strip()
        if not reply or len(reply) > 240:
            context = {k: v for k, v in context.items() if k not in {
                'memory_candidates', 'related_knowledge', 'related_learning', 'continuation_candidates'}}
            output = h._call(sid, rid, rev, 'answer', COACH_SYSTEM, json.dumps(dict(context=context,
                instruction='用户仅补充背景、经验或用途。用一两句自然承接，可以问一个尚未说明、具体且有助于下一步的问题。'
                    '已知在准备面试时，不再问学完要做什么；可以询问想聚焦的面试内容。'
                    '没有开始课程或切换目标的授权，不创建学习计划、不出题、不评价掌握。'
                    '不重复身份介绍或旧的记忆限制说明，check_question、learning_plan、learning_concepts 留空。'),
                ensure_ascii=False), ConversationOutput, ROUTER_MODEL)
            reply = output.message
        h._publish(sid, rid, rev, bound_source_links(reply, []))
    elif kind == "learning_support":
        context = {k: v for k, v in context.items() if k not in {
            "memory_candidates", "related_knowledge", "related_learning", "continuation_candidates"}}
        output = h._call(sid, rid, rev, "answer", COACH_SYSTEM, json.dumps(dict(context=context,
            instruction="结合最近对话回应当前学习困难，不重复已经给过的建议。没有最低字数，也不要求每次给建议。"
                        "用户嫌建议复杂、拒绝继续听建议或只想停一下时，用一两句接住，停止追加任务、步骤或反问。"
                        "用户确实在求办法时，先回答当前障碍，再给至多一个低负担的小建议，通常150字以内。"
                        "必要时只问一个与学习障碍直接相关的问题，不追问泛泛近况、不诊断心理状态。"
                        "这是局部支持，不是开始课程或修改计划；不宣称掌握，不检查作答，不追加保存或来源。"
                        "check_question、learning_plan、learning_concepts 留空。当前用户没有问记忆时，不复述旧的记忆范围说明。"),
            ensure_ascii=False), ConversationOutput)
        h._publish(sid, rid, rev, bound_source_links(output.message, []))
    else:
        h._publish(sid, rid, rev, short_reply(data, decision, kind))
    return True
