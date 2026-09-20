"""Synthetic node probes through production Harness methods, plus honest metrics."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import uuid
from unittest.mock import patch
from urllib.parse import urlsplit

from .cases import FIXTURES
from .reporting import price_range


def node_cases():
    fixtures = json.loads((FIXTURES / "special.json").read_text())
    result = [*fixtures["selections"], *fixtures["grades"]]
    claim = "RAG 使用检索结果辅助生成回答。"
    for suffix, texts, expected in [
        ("supported", [claim + " 这不是训练模型参数。"], ["supported", "scoped"]),
        ("insufficient", ["这段资料只介绍番茄炒蛋。"], ["insufficient"]),
        ("conflicting", [claim, "本资料认为 RAG 不使用检索结果，单独生成回答。"], ["conflicting", "insufficient"]),
    ]:
        result.append(dict(id="evidence-" + suffix, kind="evidence", topic="核验以下结论：" + claim,
            claim=claim, pages=[dict(url=f"https://source{i}.example.org/rag", title="合成资料", text=text)
                               for i, text in enumerate(texts)], expected_states=expected, provenance="synthetic"))
    return result


def run_node(h, case):
    """Non-focus preparation/web data are frozen. Focus model calls are real."""
    from agent_service.harness_store import HarnessTaskRecord
    from agent_service.learning_progress import set_plan
    from agent_service.judgment_grading import bind_standard
    from agent_service.judgment_nodes import TeachingPreparationWithClaims
    from agent_service.judgment_nodes import select as original_select
    from agent_service.schemas import (SessionMessageRequest, ScoringSpec, IntentDecision, MasteryEvaluation,
        TeachingPreparation, EvidenceAssessmentV2, SourceList, SourceCandidate)
    sid, tid = str(uuid.uuid4()), str(uuid.uuid4())
    kind = case["kind"]
    candidates = [{k: v for k, v in c.items() if k != "expected"} for c in case.get("candidates", [])]
    context = {}
    if kind == "memory":
        context["memory_candidates"] = [dict(c, knowledge_id=c["id"], concept=case["topic"],
                                              excerpt=c["text"], content_version=1) for c in candidates]
    if kind == "grading":
        task = asdict(HarnessTaskRecord(task_id=tid, session_id=sid, client_message_id=str(uuid.uuid4()),
            content=case["topic"], content_type="text", primary_language="zh",
            mode_preset="source_learning", mode="source_learning", status="awaiting_user", stage="practice",
            context=dict(conversation_managed=True, requires_mastery=False, understanding="unknown",
                         check_question=case["question"], reference_answer=case["reference"], last_lesson=case["reference"])))
        set_plan(task, ["独立说明"])
        spec = ScoringSpec(learning_goal=case["question"], must_cover=list(case["points"].values()),
                           common_misconceptions=[case["misconception"]], evidence=case["reference"])
        bind_standard(task, case["question"], spec)  # frozen BEFORE accepting answer
        with h.store.transaction(sid) as data:
            data["tasks"][tid], data["active_task_id"] = task, tid
    text = case["answer"] if kind == "grading" else case.get("claim", case["topic"])
    accepted = h.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text, context=context))
    rid = accepted.run_id
    with h.store.transaction(sid) as data:
        run = data["runs"][rid]
        run.update(status="running", task_id=tid if kind == "grading" else None)
        data["foreground"] = rid
    rev = h.store.get(sid)["runs"][rid]["revision"]
    checks, observed = {}, {}
    if kind == "memory":
        h._lookup_memory(sid, rid, rev, [case["topic"]])
        selected = [r["id"] for r in h.store.get(sid)["runs"][rid].get("memory_references", [])]
        observed = selection_outcome(case, selected)
        checks["selection"] = observed["content_selection_passed"]
    elif kind in {"source", "evidence"}:
        if kind == "evidence":
            candidates = [dict(c, id=str(i)) for i, c in enumerate(case["pages"])]
        results = [dict(url=c["url"], title=c.get("title", c.get("text", "")), snippet=c.get("text", "")) for c in candidates]
        by_url = {c["url"]: c for c in candidates}
        read_urls = []
        original = h._call
        def focus_call(*args, **kwargs):
            schema = args[6]
            if schema in {TeachingPreparation, TeachingPreparationWithClaims}:
                fields = dict(concepts=[], public_query=case["topic"],
                    official_sources_required=bool(case.get("allowed_domains")), source_domains=case.get("allowed_domains", []))
                if schema is TeachingPreparationWithClaims:
                    fields["verification_claims"] = [case["claim"]] if kind == "evidence" else []
                return schema(**fields)
            if kind == "evidence" and schema is SourceList:
                return SourceList(candidates=[SourceCandidate(url=c["url"], title=c.get("title", "")) for c in candidates])
            if kind == "source" and schema is EvidenceAssessmentV2:
                return EvidenceAssessmentV2(state="insufficient", summary="本试验仅核对候选选择。")
            return original(*args, **kwargs)
        def read(*args, **kwargs):
            if kwargs.get("operation") == "context":
                from agent_service.call_errors import WebToolError
                raise WebToolError("UNSUPPORTED")
            url = args[3]
            read_urls.append(url)
            return by_url[url].get("title", "合成资料"), by_url[url]["text"]
        def focus_select(*args, **kwargs):
            if kind == "evidence" and kwargs.get("node") == "source_candidates":
                return SourceList(candidates=[SourceCandidate(url=c["url"], title=c.get("title", "")) for c in candidates])
            return original_select(*args, **kwargs)
        decision = IntentDecision(intents=["question"], relation="continuation", scope="conversation",
                                  answer_only=True, needs_verification=True, public_search_query=case["topic"],
                                  cross_check_sources=kind == "evidence" and case["id"] == "evidence-conflicting",
                                  rationale="合成节点试验；非焦点准备与网页数据冻结。")
        with patch.object(h, "_call", side_effect=focus_call), patch.object(h, "_search",
                return_value=json.dumps(dict(protocol="harness_web_tools_v1", results=results), ensure_ascii=False)), \
                patch.object(h, "_read_page", side_effect=read), \
                patch("agent_service.judgment_nodes.select", side_effect=focus_select):
            evidence, _ = h._prepare_teaching(sid, rid, rev, decision)
        if kind == "source":
            selected = list(dict.fromkeys(next(c["id"] for c in candidates if c["url"] == url) for url in read_urls))
            observed = selection_outcome(case, selected)
            checks["selection"] = observed["content_selection_passed"]
        else:
            observed = dict(evidence=evidence)
            checks["support_state"] = evidence["state"] in case["expected_states"]
    else:
        decision = IntentDecision(intents=["answer"], relation="continuation", scope="continue_goal",
                                  answer_evidence=case["answer"], rationale="固定题目下的真实模型评价。")
        data = h.store.get(sid)
        last = next(m for m in data["messages"] if m["message_id"] in data["runs"][rid]["input_ids"])
        original = h._call
        def fixed_rubric(*args, **kwargs):
            # A node comparison supplies the same pre-answer rubric to both
            # variants. Whole dialogue baselines remain entirely unchanged.
            if h.judgments is None and args[6] is MasteryEvaluation:
                args = list(args)
                args[4] += " 按 scoring_spec 固定标准判断：必需要点全部满足且无核心误解才通过；同义表达有效。"
                args[5] = json.dumps(dict(json.loads(args[5]), scoring_spec=spec.model_dump()), ensure_ascii=False)
            return original(*args, **kwargs)
        with patch.object(h, "_call", side_effect=fixed_rubric):
            h._evaluate(sid, rid, rev, decision, last)
        data = h.store.get(sid)
        actual = data["tasks"][tid]["context"]["practice"][-1]["evaluation"]["passed"]
        observed = dict(passed=actual, expected=case["expected_complete"],
                        false_mastery=actual and not case["expected_complete"],
                        scoring_spec=spec.model_dump(),
                        point_evaluation=data["runs"][rid].get("point_evaluation"))
        checks["passed"] = actual == case["expected_complete"]
    data = h.store.get(sid)
    return dict(run=data["runs"][rid], observed=observed, checks=checks, input=text,
                replies=[m["content"] for m in data["messages"] if m["role"] == "coach" and m["run_id"] == rid])


def selection_outcome(case, selected):
    identities = {c["id"]: c.get("canonical_id") or c.get("url") or c["id"] for c in case["candidates"]}
    actual = [identities.get(i, "invalid:" + i) for i in selected]
    expected = {identities[i] for i in case["expected_selected"]}
    false = [i for i in selected if identities.get(i, "invalid:" + i) not in expected]
    missed = [i for i in case["expected_selected"] if identities[i] not in actual]
    duplicates = len(actual) - len(set(actual))
    return dict(selected=selected, false_selected=false, missed_selected=missed, duplicate_selected=duplicates,
                exact_ids_match=set(selected) == set(case["expected_selected"]),
                content_selection_passed=not (false or missed or duplicates))


def partial_adoption(judgment):
    fields = judgment.get("field_decisions", {})
    if fields:
        return judgment.get("applied", False) and {"jev", "llm"} <= {v["source"] for v in fields.values()}
    return judgment.get("applied", False) and (judgment["status"] == "uncertain" or judgment.get("reason") == "llm_point_fallback")


def entry_composition(results):
    records, field_sources = [], defaultdict(Counter)
    for row in results:
        if row.get("kind") != "dialogue" or row.get("variant") != "jev":
            continue
        for judgment in row.get("run", {}).get("judgments", []):
            if judgment["node"] != "entry":
                continue
            fields = judgment.get("field_decisions", {})
            for key, value in fields.items():
                field_sources[key][value["source"]] += 1
            if judgment["status"] not in {"ok", "uncertain"}:
                category = "unavailable"
            elif not fields:
                category = "legacy_without_field_trace"
            elif not judgment.get("applied", False):
                category = "full_llm"
            elif partial_adoption(judgment):
                category = "partial_jev"
            else:
                category = "retained_jev_with_program_fields"
            records.append(dict(id=row["id"], category=category, status=judgment["status"],
                reason=judgment.get("reason", ""), fields=fields))
    return dict(categories=dict(Counter(r["category"] for r in records)),
                field_sources={k: dict(v) for k, v in field_sources.items()}, records=records,
                note="字段来源只表示实际采用，不是正确率；程序确定项不计 Jev 成功，完整 LLM 替换不因标签相同计采用。")


def summary(path):
    rows = [json.loads(x) for x in Path(path).read_text().splitlines()]
    header = rows[0]
    results = [r for r in rows if r.get("type") == "result"]
    ids = [r["id"] for r in results]
    if len(set(ids)) != len(ids) or set(ids) - set(header["planned"]):
        raise ValueError("invalid result inventory")
    groups = defaultdict(list)
    for row in results:
        groups[row["kind"] + "/" + row["variant"]].append(row)
    metrics = {}
    node_lookup = {c["id"]: c for c in header["fixture"]["nodes"]}
    for group, values in groups.items():
        calls = [c for r in values for c in r.get("run", {}).get("model_calls", [])]
        usages = [(c, u) for c in calls for u in c.get("usage", [])]
        prices = [price_range(c["model"], u, header["fixture"]["prices"]) for c, u in usages]
        times = [r["elapsed_ms"] for r in values]
        judgments = [j for r in values for j in r.get("run", {}).get("judgments", [])]
        selections = [selection_outcome(node_lookup[r["id"].rsplit("/", 1)[0]], r["observed"]["selected"])
                      for r in values if "selected" in r.get("observed", {})]
        metrics[group] = dict(count=len(values), passed=sum(r["automatic_result"] == "PASS" for r in values),
            failed=[r["id"] for r in values if r["automatic_result"] != "PASS"],
            median_ms=round(statistics.median(times), 3), range_ms=[min(times), max(times)],
            logical_calls=len(calls), http_requests=sum(c["transport_requests"] for c in calls),
            jev_http_requests=sum(c["transport_requests"] for c in calls if c["model"] == "jev-1.13.0"),
            reported_usages=len(usages), calls_missing_usage=sum(
                c.get("usage_state") != "reported" or any(
                    type(u.get(k)) is not int for u in c.get("usage", []) for k in ("input_tokens", "output_tokens")) for c in calls),
            input_tokens=sum(u.get("input_tokens") or 0 for _, u in usages),
            output_tokens=sum(u.get("output_tokens") or 0 for _, u in usages),
            known_cost_usd=[round(sum(p[i] for p in prices if p), 9) for i in (0, 1)] if any(prices) else None,
            cost_complete=sum(p is not None for p in prices) == sum(c["transport_requests"] for c in calls),
            judgments=len(judgments), applied=sum(j.get("applied", False) for j in judgments),
            partial_adoption=sum(partial_adoption(j) for j in judgments),
            fallback=sum(not j.get("applied", False) or partial_adoption(j) for j in judgments),
            reasons=dict(__import__("collections").Counter(j["reason"] for j in judgments if j.get("reason"))),
            content_selections_passed=sum(r["content_selection_passed"] for r in selections),
            false_selected=sum(len(r["false_selected"]) for r in selections),
            missed_selected=sum(len(r["missed_selected"]) for r in selections),
            duplicate_selected=sum(r["duplicate_selected"] for r in selections),
            false_mastery=sum(r.get("observed", {}).get("false_mastery", False) for r in values))
    return dict(experiment="jev-harness-integration-1", planned=len(header["planned"]), executed=len(results),
                missing=[i for i in header["planned"] if i not in ids], groups=metrics,
                node_semantics=local_semantics(header, results),
                entry_composition=entry_composition(results),
                limitations=header["fixture"]["limitations"],
                result="PASS" if len(results) == len(header["planned"]) and all(r["automatic_result"] == "PASS" for r in results) else "FAIL")


def local_semantics(header, results):
    """Score raw node labels separately from program guards and LLM fallbacks.

    Only frozen gold that is comparable to the new contract is scored. Entry
    exposes a different taxonomy, so its raw labels remain for qualitative
    review; it must not inherit the final routed turn's PASS as its own grade.
    """
    cases = {c["id"]: c for c in header["fixture"]["nodes"]}
    reports = []
    for row in results:
        if row["variant"] != "jev" or row["kind"] not in {"memory", "source", "grading", "evidence"}:
            continue
        case = cases[row["id"].rsplit("/", 1)[0]]
        for judgment in row["run"].get("judgments", []):
            if judgment["status"] not in {"ok", "uncertain"}:
                reports.append(dict(id=row["id"], node=judgment["node"], status=judgment["status"],
                                    scored=0, correct=0, uncertain=0, errors=[], reason=judgment["reason"]))
                continue
            labels = {k: v["choice"] for k, v in judgment["answers"].items()}
            expected = {}
            if case["kind"] == "grading":
                expected = {f"point_{i}": case["expected"]["point_" + key] for i, key in enumerate(case["points"])}
                expected["misconception"] = case["expected"]["misconception"]
            elif case["kind"] in {"memory", "source"}:
                for i, candidate in enumerate(case["candidates"]):
                    relevant = candidate["expected"] == "relevant"
                    if case.get("allowed_domains"):
                        host = urlsplit(candidate["url"]).hostname or ""
                        relevant &= any(host == d or host.endswith("." + d) for d in case["allowed_domains"])
                    key = candidate["id"] if case["kind"] == "memory" else str(i)
                    expected[key] = "selected" if relevant else "irrelevant"
                    if labels.get(key) not in {"irrelevant", "unsure"}:
                        labels[key] = "selected"
            elif case["kind"] == "evidence" and case["id"] != "evidence-conflicting":
                expected = {"claim_0_page_0": "supported" if case["id"] == "evidence-supported" else "insufficient"}
            errors = [dict(field=k, expected=v, actual=labels.get(k)) for k, v in expected.items()
                      if labels.get(k) not in {v, "unsure"}]
            reports.append(dict(id=row["id"], node=judgment["node"], status=judgment["status"],
                scored=len(expected), correct=sum(labels.get(k) == v for k, v in expected.items()),
                uncertain=sum(labels.get(k) == "unsure" for k in expected), errors=errors))
    return reports
