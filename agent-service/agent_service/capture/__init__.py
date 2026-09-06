from __future__ import annotations

import re
from typing import Any, Literal, TypedDict
from urllib.parse import quote

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from agent_service.capture.fetch import fetch_public_url, looks_like_url
from agent_service.capture.prompts import (
    CLASSIFY_SYSTEM,
    EXTRACT_SYSTEM,
    RISK_SYSTEM,
    SEARCH_FALLBACK_SYSTEM,
    SEMANTIC_SYSTEM,
    VERIFY_SYSTEM,
)
from agent_service.openai_client import dump, parse_model, web_search_text
from agent_service.schemas import (
    ExtractPayload,
    IntentClass,
    RiskVerdict,
    SemanticVerdict,
    SourceCandidate,
    SourceList,
    VerifyVerdict,
)

RISK_RULE = re.compile(
    r"(诊断|剂量|处方|疫苗|诉讼|合同|利率|股价|mg\b|usd\b|¥|法律|金融|医学|clinical|lawsuit|dosage|\d{4}年|\d+(\.\d+)?%)",
    re.I,
)


class CaptureState(TypedDict, total=False):
    task_id: str
    raw_text: str
    primary_language: str
    input_type: str
    url: str | None
    page_text: str
    intent: str
    topic: str
    semantic_ok: bool
    extracted: dict[str, Any]
    repair_used: bool
    force_source_view: bool
    source_candidates: list[dict[str, Any]]
    verify_reason: str
    events: list[dict[str, Any]]
    outcome: Literal["committing", "needs_attention", "retryable_failed"]
    error_code: str | None
    user_status: str


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _parse_capture_model(system: str, user: str, schema: type):
    """Retry one provider-completed but empty structured response at the failed node."""
    for attempt in range(2):
        try:
            return parse_model(system, user, schema)
        except RuntimeError as exc:
            if str(exc) != "RT.CAPTURE.MODEL_FAILED" or attempt == 1:
                raise
    raise RuntimeError("RT.CAPTURE.MODEL_FAILED")


def _language_drift_issues(payload: ExtractPayload, primary_language: str) -> list[str]:
    if not (primary_language or "zh").lower().startswith("zh"):
        return []
    issues: list[str] = []
    if not _has_cjk(payload.understood_as):
        issues.append("understood_as 必须使用用户主语言")
    titles = [item.title.strip() for item in payload.knowledge]
    if len(titles) != len(set(titles)):
        issues.append("同一批知识点的 title 不能重复")
    generic_themes = {"技术", "知识", "其他", "未分类", "内容", "笔记", "通用", "主题"}
    for item in payload.knowledge:
        if not _has_cjk(item.learning_goal):
            issues.append("learning_goal 必须使用用户主语言")
        if not _has_cjk(item.title):
            issues.append("title 必须使用用户主语言")
        if not _has_cjk(item.explanation):
            issues.append("explanation 必须使用用户主语言")
        if item.title.startswith(("说明", "描述", "概括", "解释", "写出", "列出", "总结", "简述")):
            issues.append("title 应是知识点名称，不要写成说明/描述句")
        if item.title.endswith(("在", "的", "与", "和", "或", "以及")):
            issues.append("title 不能停在半截，例如「……在」")
        if item.title.strip() in {"记住", "技术", "知识", "内容", "说明"}:
            issues.append("title 不能是「记住」「技术」这类空词")
        if item.theme.strip() in generic_themes:
            issues.append("theme 必须是具体主题名，不能是「技术」这类空分类")
        if re.search(r"第\s*[0-9一二三四五六七八九十]+\s*步", item.title):
            issues.append("流程步骤写入同一条 explanation，不要拆成多条「第N步」")
        if "......" in item.explanation or "……" in item.explanation:
            issues.append("explanation 不要用省略号拼接原文")
        lines = [line.strip() for line in item.explanation.splitlines() if line.strip()]
        numbered = sum(
            1
            for line in lines
            if re.match(r"^(\d+\s*[\.、．\)]|[-*•]|第.+[步点条])", line)
        )
        if numbered < 2 and len(item.explanation) > 50:
            issues.append("explanation 要用 1. 2. 3. 或列表分点，不要写成一整段")
        if not _has_cjk(item.scoring_spec.learning_goal):
            issues.append("scoring_spec.learning_goal 必须使用用户主语言")
        for question in item.questions:
            if question.variant_index == 0 and not _has_cjk(question.prompt_text):
                issues.append("主问题必须使用用户主语言")
    return issues


def _event(state: CaptureState, event_type: str, node: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    events = list(state.get("events") or [])
    events.append(
        {
            "seq": len(events) + 1,
            "event_type": event_type,
            "node": node,
            "payload": payload or {},
        }
    )
    return {"events": events}


def _source_text(state: CaptureState) -> str:
    page = (state.get("page_text") or "").strip()
    if page:
        return page
    return (state.get("raw_text") or "").strip()


def source_fidelity_issues(payload: ExtractPayload, source: str) -> list[str]:
    """Return hard source-provenance violations that a model verdict cannot override."""
    issues: list[str] = []
    for item in payload.knowledge:
        excerpt = item.evidence_excerpt
        scoring_evidence = item.scoring_spec.evidence
        if not excerpt.strip() or excerpt not in source:
            issues.append(f"{item.id}: evidence_excerpt 必须是原文的非空连续子串")
        if not scoring_evidence.strip() or scoring_evidence not in source:
            issues.append(f"{item.id}: scoring_spec.evidence 必须是原文的非空连续子串")
    return issues


def ingest_node(state: CaptureState) -> dict[str, Any]:
    updates = _event(state, "node_start", "ingest")
    url = (state.get("url") or "").strip() or looks_like_url(state.get("raw_text") or "")
    if url:
        updates["user_status"] = "读取网页"
        try:
            title, body = fetch_public_url(url)
        except ValueError as exc:
            code = str(exc)
            updates.update(_event({**state, **updates}, "node_failed", "ingest", {"error": code}))
            updates["outcome"] = "needs_attention" if code == "RT.CAPTURE.SSRF" else "retryable_failed"
            if code == "RT.CAPTURE.FETCH_FAILED":
                updates["outcome"] = "needs_attention"
            updates["error_code"] = code if code.startswith("RT.") else "RT.CAPTURE.FETCH_FAILED"
            updates["user_status"] = "无法读取网页，请粘贴正文" if code == "RT.CAPTURE.FETCH_FAILED" else (
                "需要处理" if updates["outcome"] == "needs_attention" else "需要重试"
            )
            updates["url"] = url
            return updates
        updates["url"] = url
        updates["page_text"] = f"{title}\n\n{body}"
        updates["input_type"] = "url"
        updates.update(_event({**state, **updates}, "node_success", "ingest", {"url": url}))
        return updates
    updates.update(_event({**state, **updates}, "node_success", "ingest"))
    return updates


def classify_node(state: CaptureState) -> dict[str, Any]:
    updates = _event(state, "node_start", "classify")
    if state.get("outcome") in {"retryable_failed", "needs_attention"}:
        return updates
    updates["user_status"] = "正在判断意图"
    source = _source_text(state)
    if state.get("page_text") or len(source) > 180:
        updates["intent"] = "remember_content"
        updates.update(_event({**state, **updates}, "node_success", "classify", {"intent": "remember_content", "heuristic": True}))
        return updates
    try:
        parsed = _parse_capture_model(
            CLASSIFY_SYSTEM,
            f"用户主语言：{state.get('primary_language', 'zh')}\n\n原文：\n{source}",
            IntentClass,
        )
        verdict = IntentClass.model_validate(parsed.model_dump())
        updates["intent"] = verdict.intent
        updates["topic"] = verdict.topic or source[:80]
        updates.update(_event({**state, **updates}, "node_success", "classify", {"intent": verdict.intent}))
        if verdict.intent == "too_broad":
            updates["outcome"] = "needs_attention"
            updates["error_code"] = "RT.CAPTURE.TOO_BROAD"
            updates["user_status"] = "需要处理"
        elif verdict.intent == "learn_topic" and not state.get("page_text"):
            updates["outcome"] = "needs_attention"
            updates["error_code"] = "RT.CAPTURE.NEED_SOURCE"
            updates["user_status"] = "需要处理"
        return updates
    except Exception as exc:  # noqa: BLE001
        updates.update(_event({**state, **updates}, "node_failed", "classify", {"error": str(exc)[:200]}))
        updates["outcome"] = "retryable_failed"
        updates["error_code"] = "RT.CAPTURE.MODEL_FAILED"
        updates["user_status"] = "需要重试"
        return updates


def extract_node(state: CaptureState) -> dict[str, Any]:
    updates = _event(state, "node_start", "extract")
    if state.get("outcome") in {"retryable_failed", "needs_attention"}:
        return updates
    updates["user_status"] = "正在整理"
    source = _source_text(state)
    extra = ""
    if state.get("force_source_view"):
        extra = "\n把 attribution 设为 source_view，学习目标加上来源限定，不要写成已证实事实。"
    try:
        parsed = _parse_capture_model(
            EXTRACT_SYSTEM + extra,
            f"用户主语言：{state.get('primary_language', 'zh')}\n\n原文：\n{source}",
            ExtractPayload,
        )
        payload = ExtractPayload.model_validate(parsed.model_dump())
        for item in payload.knowledge:
            if state.get("url") and not item.evidence_locator:
                item.evidence_locator = state["url"]
        updates.update(_event({**state, **updates}, "node_success", "extract", {"knowledge_count": len(payload.knowledge)}))
        updates["extracted"] = payload.model_dump()
        return updates
    except Exception as exc:  # noqa: BLE001
        updates.update(_event({**state, **updates}, "node_failed", "extract", {"error": str(exc)[:200]}))
        updates["outcome"] = "retryable_failed"
        updates["error_code"] = "RT.CAPTURE.MODEL_FAILED"
        updates["user_status"] = "需要重试"
        return updates


def structure_validate_node(state: CaptureState) -> dict[str, Any]:
    updates = _event(state, "node_start", "structure_validate")
    if state.get("outcome") in {"retryable_failed", "needs_attention"}:
        return updates
    try:
        ExtractPayload.model_validate(state.get("extracted") or {})
        updates.update(_event({**state, **updates}, "node_success", "structure_validate"))
        return updates
    except ValidationError as exc:
        updates.update(_event({**state, **updates}, "node_failed", "structure_validate", {"error": str(exc)[:200]}))
        updates["outcome"] = "needs_attention"
        updates["error_code"] = "RT.CAPTURE.STRUCTURE_INVALID"
        updates["user_status"] = "需要处理"
        return updates


def semantic_validate_node(state: CaptureState) -> dict[str, Any]:
    updates = _event(state, "node_start", "semantic_validate")
    if state.get("outcome") in {"retryable_failed", "needs_attention"}:
        return updates
    try:
        extracted = ExtractPayload.model_validate(state["extracted"])
        verdict = _parse_capture_model(
            SEMANTIC_SYSTEM,
            f"用户主语言：{state.get('primary_language', 'zh')}\n\n原文：\n"
            f"{_source_text(state)}\n\n整理结果：\n{dump(extracted)}",
            SemanticVerdict,
        )
        payload = SemanticVerdict.model_validate(verdict.model_dump())
        payload.issues.extend(_language_drift_issues(extracted, state.get("primary_language", "zh")))
        payload.issues.extend(source_fidelity_issues(extracted, _source_text(state)))
        if payload.issues:
            payload.ok = False
        if payload.ok:
            updates.update(_event({**state, **updates}, "node_success", "semantic_validate"))
            updates["semantic_ok"] = True
            return updates
        if state.get("repair_used"):
            updates.update(
                _event({**state, **updates}, "node_failed", "semantic_validate", {"issues": payload.issues})
            )
            updates["outcome"] = "needs_attention"
            updates["error_code"] = "RT.CAPTURE.SEMANTIC_INVALID"
            updates["user_status"] = "需要处理"
            return updates
        updates.update(_event({**state, **updates}, "branch", "semantic_validate", {"repair": True, "issues": payload.issues}))
        updates["user_status"] = "正在整理"
        return updates
    except Exception as exc:  # noqa: BLE001
        updates.update(_event({**state, **updates}, "node_failed", "semantic_validate", {"error": str(exc)[:200]}))
        updates["outcome"] = "retryable_failed"
        updates["error_code"] = "RT.CAPTURE.MODEL_FAILED"
        updates["user_status"] = "需要重试"
        return updates


def repair_node(state: CaptureState) -> dict[str, Any]:
    updates = _event(state, "node_start", "repair")
    updates["repair_used"] = True
    try:
        parsed = _parse_capture_model(
            EXTRACT_SYSTEM + "\n上一稿未通过语义校验，请只根据原文修正，不要引入新的外部事实。",
            f"用户主语言：{state.get('primary_language', 'zh')}\n\n原文：\n{_source_text(state)}\n\n上一稿：\n{dump(ExtractPayload.model_validate(state['extracted']))}",
            ExtractPayload,
        )
        payload = ExtractPayload.model_validate(parsed.model_dump())
        updates["extracted"] = payload.model_dump()
        updates.update(_event({**state, **updates}, "node_success", "repair"))
        return updates
    except Exception as exc:  # noqa: BLE001
        updates.update(_event({**state, **updates}, "node_failed", "repair", {"error": str(exc)[:200]}))
        updates["outcome"] = "retryable_failed"
        updates["error_code"] = "RT.CAPTURE.MODEL_FAILED"
        updates["user_status"] = "需要重试"
        return updates


def risk_node(state: CaptureState) -> dict[str, Any]:
    updates = _event(state, "node_start", "risk")
    if state.get("outcome") in {"retryable_failed", "needs_attention"}:
        return updates
    source = _source_text(state)
    rule_hit = bool(RISK_RULE.search(source))
    extracted = ExtractPayload.model_validate(state.get("extracted") or {})
    model_hit = extracted.risk_flagged
    try:
        parsed = _parse_capture_model(RISK_SYSTEM, source[:6000], RiskVerdict)
        model_hit = model_hit or RiskVerdict.model_validate(parsed.model_dump()).risk
    except Exception:  # noqa: BLE001
        pass
    risk = rule_hit or model_hit
    updates.update(_event({**state, **updates}, "node_success", "risk", {"risk": risk, "rule": rule_hit}))
    if not risk:
        updates["outcome"] = "committing"
        updates["user_status"] = "整理完成"
        updates["error_code"] = None
        return updates
    updates["user_status"] = "正在核验"
    return updates


def verify_node(state: CaptureState) -> dict[str, Any]:
    updates = _event(state, "node_start", "verify")
    if state.get("outcome") in {"retryable_failed", "needs_attention", "committing"}:
        if state.get("outcome") == "committing":
            return updates
        return updates
    source = _source_text(state)
    updates["user_status"] = "正在核验"
    search = web_search_text(f"核验以下主张是否与公开资料一致：\n{source[:1500]}")
    if not search:
        updates.update(_event({**state, **updates}, "node_failed", "verify", {"error": "empty_search"}))
        updates["outcome"] = "needs_attention"
        updates["error_code"] = "RT.CAPTURE.VERIFY_INSUFFICIENT"
        updates["verify_reason"] = "没有足够的公开检索结果"
        updates["user_status"] = "需要处理"
        return updates
    try:
        parsed = _parse_capture_model(
            VERIFY_SYSTEM,
            f"来源：\n{source[:4000]}\n\n检索：\n{search[:4000]}",
            VerifyVerdict,
        )
        verdict = VerifyVerdict.model_validate(parsed.model_dump())
    except Exception as exc:  # noqa: BLE001
        updates.update(_event({**state, **updates}, "node_failed", "verify", {"error": str(exc)[:200]}))
        updates["outcome"] = "retryable_failed"
        updates["error_code"] = "RT.CAPTURE.MODEL_FAILED"
        updates["user_status"] = "需要重试"
        return updates
    updates["verify_reason"] = verdict.reason
    if verdict.verdict == "confirmed":
        updates.update(_event({**state, **updates}, "node_success", "verify", {"verdict": verdict.verdict}))
        updates["outcome"] = "committing"
        updates["user_status"] = "整理完成"
        updates["error_code"] = None
        return updates
    code = "RT.CAPTURE.CONFLICT" if verdict.verdict == "conflict" else "RT.CAPTURE.VERIFY_INSUFFICIENT"
    updates.update(_event({**state, **updates}, "node_failed", "verify", {"verdict": verdict.verdict}))
    updates["outcome"] = "needs_attention"
    updates["error_code"] = code
    updates["user_status"] = "需要处理"
    return updates


def route_after_semantic(state: CaptureState) -> str:
    outcome = state.get("outcome")
    if outcome in {"retryable_failed", "needs_attention"}:
        return "done"
    if state.get("semantic_ok"):
        return "risk"
    if not state.get("repair_used"):
        return "repair"
    return "done"


def route_after_risk(state: CaptureState) -> str:
    if state.get("outcome") == "committing":
        return "done"
    if state.get("outcome") in {"retryable_failed", "needs_attention"}:
        return "done"
    return "verify"


def build_graph():
    graph = StateGraph(CaptureState)
    graph.add_node("ingest", ingest_node)
    graph.add_node("classify", classify_node)
    graph.add_node("extract", extract_node)
    graph.add_node("structure_validate", structure_validate_node)
    graph.add_node("semantic_validate", semantic_validate_node)
    graph.add_node("repair", repair_node)
    graph.add_node("risk", risk_node)
    graph.add_node("verify", verify_node)
    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "classify")
    graph.add_edge("classify", "extract")
    graph.add_edge("extract", "structure_validate")
    graph.add_edge("structure_validate", "semantic_validate")
    graph.add_conditional_edges(
        "semantic_validate",
        route_after_semantic,
        {"repair": "repair", "risk": "risk", "done": END},
    )
    graph.add_edge("repair", "structure_validate")
    graph.add_conditional_edges(
        "risk",
        route_after_risk,
        {"verify": "verify", "done": END},
    )
    graph.add_edge("verify", END)
    return graph.compile()


capture_graph = build_graph()


def find_source_candidates(topic: str) -> list[SourceCandidate]:
    search = web_search_text(f"公开百科或文档：{topic}")
    candidates: list[SourceCandidate] = []
    if search:
        try:
            parsed = _parse_capture_model(
                SEARCH_FALLBACK_SYSTEM,
                f"主题：{topic}\n\n检索摘录：\n{search[:4000]}",
                SourceList,
            )
            candidates = SourceList.model_validate(parsed.model_dump()).candidates
        except Exception:  # noqa: BLE001
            candidates = []
    if not candidates:
        slug = quote(topic.strip().replace(" ", "_"))
        candidates = [
            SourceCandidate(url=f"https://zh.wikipedia.org/wiki/{slug}", title=f"{topic} · 中文维基", snippet="公开百科候选"),
            SourceCandidate(url=f"https://en.wikipedia.org/wiki/{slug}", title=f"{topic} · English Wikipedia", snippet="Public encyclopedia candidate"),
        ]
    safe: list[SourceCandidate] = []
    for item in candidates[:3]:
        try:
            from agent_service.capture.fetch import assert_public_http_url

            assert_public_http_url(item.url)
            safe.append(item)
        except ValueError:
            continue
    return safe


def run_capture(
    task_id: str,
    raw_text: str,
    primary_language: str,
    input_type: str = "text",
    url: str | None = None,
    force_source_view: bool = False,
) -> CaptureState:
    return capture_graph.invoke(
        {
            "task_id": task_id,
            "raw_text": raw_text,
            "primary_language": primary_language,
            "input_type": input_type,
            "url": url,
            "repair_used": False,
            "force_source_view": force_source_view,
            "semantic_ok": False,
            "events": [],
        }
    )


def run_text_capture(task_id: str, raw_text: str, primary_language: str) -> CaptureState:
    return run_capture(task_id, raw_text, primary_language)
