"""Behavioral checks for the opt-in real Harness decision boundaries."""
import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from tests import test_conversation_v2 as legacy
from agent_service.conversation import ConversationHarness
from agent_service.conversation_store import Superseded
from agent_service.jev_client import JevClient
from agent_service.judgments import JudgmentEngine
from agent_service.judgment_types import MODEL, JudgmentRequest, JudgmentResult, question
from agent_service.judgment_nodes import (IntentRemainder, OWNED, entry_request, resolve_entry, select, assess_evidence,
                                          TeachingPreparationWithClaims)
from agent_service.judgment_grading import (ScoredConversationOutput, ScoredProblemCoachBundle, ScoredMasteryEvaluation, JudgmentFeedback,
    bind_standard, standard_for, grading_request)
from agent_service.schemas import ScoringSpec, IntentDecision, MemoryChoice, EvidenceAssessmentV2

LESSON = "RAG 先检索相关资料，再把资料提供给模型生成回答。它不保证回答一定正确。"


def rubric():
    return ScoringSpec(learning_goal="解释 RAG",
        must_cover=["检索相关资料", "将资料作为上下文用于生成"],
        common_misconceptions=["检索后保证绝不出错"], evidence=LESSON)


def raw_answers(request, choices):
    return {key: dict(type="choice", choice=choices.get(key, "unsure"), confidence=1.0,
        probabilities={label: float(label == choices.get(key, "unsure")) for label in q["criteria"]})
        for key, q in request["questions"].items()}


class TransportTests(unittest.TestCase):
    def request(self):
        return JudgmentRequest(node="test", state={"text": "合成材料"},
                               questions={"a": question("相关吗", {"yes": "相关", "no": "无关"})})

    def test_valid_negative_is_distinct_from_all_failure_shapes(self):
        good = dict(model=MODEL, answers=raw_answers(self.request().payload(), {"a": "no"}),
                    usage={"input_tokens": 12, "output_tokens": 3})
        bads = [dict(good, answers={}), dict(good, model="jev-latest"),
                dict(good, answers={"illegal_candidate": good["answers"]["a"]}),
                dict(good, answers={"a": dict(good["answers"]["a"], confidence=True)}),
                dict(good, answers={"a": dict(good["answers"]["a"], probabilities={"yes": .2, "no": .2, "unsure": .2})})]
        for payload in [good, *bads]:
            with self.subTest(payload=payload):
                with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as http:
                    result, _ = JevClient("synthetic-key", client=http).call(self.request())
                self.assertEqual(result.status, "ok" if payload is good else "failed")

    def test_authentication_failure_disables_instance_without_retry(self):
        calls = []
        def reject(req):
            calls.append(req)
            return httpx.Response(401, text="untrusted upstream body")
        with httpx.Client(transport=httpx.MockTransport(reject)) as http:
            client = JevClient("synthetic-key", client=http)
            first, _ = client.call(self.request())
            second, _ = client.call(self.request())
        self.assertEqual(first.reason, "authentication_failed")
        self.assertEqual(second.status, "skipped")
        self.assertEqual(len(calls), 1)

    def test_timeout_does_not_retry_and_does_not_return_a_negative(self):
        calls = []
        def timeout(req):
            calls.append(req)
            raise httpx.ReadTimeout("synthetic")
        with httpx.Client(transport=httpx.MockTransport(timeout)) as http:
            result, _ = JevClient("synthetic-key", client=http).call(self.request())
        self.assertEqual((result.status, result.reason, result.answers), ("failed", "timeout", {}))
        self.assertEqual(len(calls), 1)

    def test_response_cannot_echo_credential_into_evidence(self):
        def response(req):
            return httpx.Response(200, json=dict(model=MODEL, debug="synthetic-key",
                answers=raw_answers(json.loads(req.content), {"a": "yes"})))
        with httpx.Client(transport=httpx.MockTransport(response)) as http:
            _, raw = JevClient("synthetic-key", client=http).call(self.request())
        self.assertNotIn("synthetic-key", json.dumps(raw))

    def test_invalid_nonfinite_or_huge_probability_is_recordable_without_credentials(self):
        for probability in (float("nan"), float("inf"), 10 ** 400):
            def response(req):
                answers = raw_answers(json.loads(req.content), {"a": "yes"})
                answers["a"]["probabilities"]["yes"] = probability
                return httpx.Response(200, content=json.dumps(dict(model=MODEL, debug="synthetic-key", answers=answers)))
            with httpx.Client(transport=httpx.MockTransport(response)) as http:
                result, raw = JevClient("synthetic-key", client=http).call(self.request())
            self.assertEqual((result.status, result.reason), ("failed", "invalid_response"))
            self.assertNotIn("synthetic-key", json.dumps(raw, allow_nan=False))


class HarnessJudgmentTests(unittest.TestCase):
    send = legacy.ConversationTests.send
    state = legacy.ConversationTests.state
    control = legacy.ConversationTests.control

    def setUp(self):
        legacy.ConversationTests.setUp(self)
        self.labels = {"intent": "question", "workflow": "none", "relation": "continuation",
                       "needs_verification": "no", "cross_check_sources": "no", "refresh_sources": "no",
                       "misconception": "absent"}
        self.replacement = None
        self.updates = {}
        self.http_calls, self.records = [], []
        self.http = httpx.Client(transport=httpx.MockTransport(self.transport))
        self.engine = JudgmentEngine(JevClient("synthetic-key", client=self.http), observer=self.records.append)
        self.extra_delay = 0

    def tearDown(self):
        self.http.close()
        legacy.ConversationTests.tearDown(self)

    def enable(self):
        self.harness = ConversationHarness(self.store, judgments=self.engine)

    def transport(self, req):
        body = json.loads(req.content)
        self.http_calls.append(body)
        if self.extra_delay:
            time.sleep(self.extra_delay)
        labels = dict(self.labels)
        for key, q in body["questions"].items():
            if key not in labels:
                labels[key] = ("covered" if key.startswith("point_") else "supported" if key.startswith("claim_")
                               else "irrelevant" if "irrelevant" in q["criteria"] else "pass" if "pass" in q["criteria"] else "unsure")
        return httpx.Response(200, json=dict(model=MODEL, answers=raw_answers(body, labels),
                                             usage={"input_tokens": 10, "output_tokens": 5}))

    def model(self, system, user, schema, **kwargs):
        if schema.__name__ == "QuestionQualityReview":
            self.calls.append((schema, json.loads(user)))
            return schema(minimum_answer="检索资料，再用于生成。", issues=[], **{
                k: "pass" for k in schema.model_fields if k not in {"minimum_answer", "issues"}})
        if schema is IntentRemainder:
            self.calls.append((schema, json.loads(user)))
            fields = self.decision.model_dump(exclude=OWNED)
            return IntentRemainder(**fields, replacement=self.replacement, updates=self.updates)
        if schema is TeachingPreparationWithClaims:
            self.calls.append((schema, json.loads(user)))
            return TeachingPreparationWithClaims(concepts=[], public_query=self.decision.public_search_query)
        if schema is ScoredConversationOutput:
            self.calls.append((schema, json.loads(user)))
            return ScoredConversationOutput(message=LESSON, check_question="RAG 如何工作？",
                                           check_scoring_spec=rubric())
        if schema is ScoredProblemCoachBundle:
            self.calls.append((schema, json.loads(user)))
            return ScoredProblemCoachBundle.model_validate(legacy.bundle().model_dump())
        if schema is JudgmentFeedback:
            payload = json.loads(user)
            self.calls.append((schema, payload))
            return JudgmentFeedback(correctness="按要点判断", completeness="按要点判断", expression="可理解",
                transfer="待验证", feedback="本题通过。" if payload["effective_passed"] else "本题尚未独立通过。",
                followup_question="换个应用场景说明 RAG。", followup_scoring_spec=rubric())
        if schema.__name__ == "PointJudgmentFallback":
            self.calls.append((schema, json.loads(user)))
            return schema(**{k: "absent" if k == "misconception" else "covered" for k in schema.model_fields})
        if schema is ScoredMasteryEvaluation:
            self.calls.append((schema, json.loads(user)))
            return ScoredMasteryEvaluation(passed=False, correctness="旧题路径", completeness="", expression="",
                transfer="", feedback="继续练习", followup_question="下一题", followup_scoring_spec=None)
        return legacy.ConversationTests.model(self, system, user, schema, **kwargs)

    def active_run(self):
        accepted = self.send("合成测试问题", drain=False)
        with self.store.transaction(self.sid) as data:
            run = data["runs"][accepted.run_id]
            run["status"] = "running"
            data["foreground"] = accepted.run_id
        return accepted.run_id, self.state()["runs"][accepted.run_id]["revision"]

    def test_disabled_uses_unchanged_schema_and_no_jev(self):
        self.decision = legacy.intent("question", answer_only=True)
        self.send("RAG 是什么")
        self.assertFalse(self.http_calls)
        self.assertTrue(any(s is IntentDecision for s, _ in self.calls))
        self.assertFalse(any(s is IntentRemainder for s, _ in self.calls))

    def test_valid_entry_is_merged_and_ordinary_question_does_not_create_task(self):
        self.enable()
        self.decision = legacy.intent("question", answer_only=True)
        self.send("RAG 是什么")
        data = self.state()
        self.assertFalse(data["tasks"])
        run = next(iter(data["runs"].values()))
        self.assertEqual(run["intent"]["intents"], ["question"])
        self.assertTrue(run["judgments"][0]["applied"])
        self.assertEqual(sum(s is IntentRemainder for s, _ in self.calls), 1)
        self.assertFalse(any(s is IntentDecision for s, _ in self.calls))

    def test_mixed_request_uses_full_llm_and_does_not_publish_greeting_only(self):
        self.enable()
        self.labels["intent"] = "mixed"
        self.decision = legacy.intent("greeting", "question", answer_only=True)
        self.send("你好，顺便解释 RAG")
        run = next(iter(self.state()["runs"].values()))
        self.assertFalse(run["judgments"][0]["applied"])
        self.assertTrue(any(s is IntentDecision for s, _ in self.calls))
        self.assertIn("question", run["intent"]["intents"])

    def test_empty_session_relation_is_program_owned_and_not_asked_of_jev(self):
        self.enable()
        self.decision = legacy.intent("question", answer_only=True)
        self.updates = {"relation": {"value": "continuation", "reason": "模型错误地想延续不存在的前文"}}
        self.send("harness 是什么")
        run = next(iter(self.state()["runs"].values()))
        self.assertEqual(run["intent"]["relation"], "new_topic")
        self.assertNotIn("relation", self.http_calls[0]["questions"])
        self.assertEqual(run["judgments"][0]["field_decisions"]["relation"]["source"], "program")

    def test_existing_context_does_not_force_new_topic(self):
        for key, value in [("task", {"context": {}}), ("session_goal", "理解 RAG"),
                           ("summary", "已讲解检索"), ("recent_messages", [{"content": "RAG"}])]:
            with self.subTest(key=key):
                request = entry_request({"current_inputs": ["举个例子"], key: value})
                self.assertIn("relation", request.questions)
                self.assertNotIn("relation", request.state["program_fields"])

    def test_uncertain_tool_field_is_filled_without_discarding_main_intent(self):
        self.enable()
        self.decision = legacy.intent("question", answer_only=True)
        self.labels["refresh_sources"] = "unsure"
        self.updates = {"refresh_sources": {"value": "no", "reason": "原话没有更新来源要求"}}
        self.send("RAG 是什么")
        run = next(iter(self.state()["runs"].values()))
        judgment = run["judgments"][0]
        self.assertTrue(judgment["applied"])
        self.assertEqual(judgment["status"], "uncertain")
        self.assertEqual(judgment["answers"]["refresh_sources"]["choice"], "unsure")
        self.assertEqual(judgment["field_decisions"]["intent"]["source"], "jev")
        self.assertEqual(judgment["field_decisions"]["refresh_sources"]["source"], "llm")
        payload = next(p for s, p in self.calls if s is IntentRemainder)
        self.assertEqual(payload["pending_fields"], ["refresh_sources"])
        self.assertEqual(sum(s is IntentRemainder for s, _ in self.calls), 1)
        self.assertFalse(any(s is IntentDecision for s, _ in self.calls))

    def test_uncertain_intent_uses_llm_for_that_field_only(self):
        self.enable()
        self.labels["intent"] = "unsure"
        self.decision = legacy.intent("question", answer_only=True)
        self.updates = {"intent": {"value": "question", "reason": "用户明确询问概念"}}
        self.send("RAG 是什么")
        run = next(iter(self.state()["runs"].values()))
        self.assertEqual(run["intent"]["intents"], ["question"])
        self.assertEqual(run["judgments"][0]["field_decisions"]["intent"]["source"], "llm")
        self.assertEqual(run["judgments"][0]["field_decisions"]["needs_verification"]["source"], "jev")
        self.assertFalse(any(s is IntentDecision for s, _ in self.calls))

    def test_unresolved_tool_need_is_not_converted_to_no(self):
        self.enable()
        self.labels["refresh_sources"] = "unsure"
        self.decision = legacy.intent("question", answer_only=True)
        self.send("解释 RAG")
        judgment = next(iter(self.state()["runs"].values()))["judgments"][0]
        self.assertFalse(judgment["applied"])
        self.assertTrue(any(s is IntentDecision for s, _ in self.calls))
        self.assertEqual(judgment["field_decisions"]["refresh_sources"]["reason"], "incomplete_local_resolution")

    def test_relation_conflict_preserves_knowledge_intent_after_greeting(self):
        self.send("你好")
        self.calls.clear()
        self.enable()
        self.decision = legacy.intent("question", answer_only=True)
        self.updates = {"relation": {"value": "new_topic", "reason": "前文仅为寒暄，此次首次提出知识主题"}}
        self.send("harness 是什么")
        run = list(self.state()["runs"].values())[-1]
        self.assertEqual(run["intent"]["relation"], "new_topic")
        self.assertEqual(run["judgments"][0]["field_decisions"]["intent"]["source"], "jev")
        self.assertEqual(run["judgments"][0]["field_decisions"]["relation"]["source"], "llm")
        self.assertFalse(self.state()["tasks"])
        self.assertFalse(any(s is IntentDecision for s, _ in self.calls))

    def test_tool_conflict_is_corrected_without_replacing_other_fields(self):
        self.enable()
        self.labels["needs_verification"] = "yes"
        self.decision = legacy.intent("question", answer_only=True)
        self.updates = {"needs_verification": {"value": "no", "reason": "用户说不需要联网，且为稳定概念"}}
        self.send("解释 API Key，不需要联网")
        run = next(iter(self.state()["runs"].values()))
        self.assertFalse(run["intent"]["needs_verification"])
        self.assertEqual(run["judgments"][0]["field_decisions"]["needs_verification"]["raw_choice"], "yes")
        self.assertEqual(run["judgments"][0]["field_decisions"]["intent"]["source"], "jev")
        self.assertFalse(any(s is IntentDecision for s, _ in self.calls))

    def test_full_replacement_agreement_is_not_counted_as_jev_adoption(self):
        self.enable()
        self.decision = legacy.intent("question", answer_only=True)
        self.replacement = self.decision
        self.send("解释 RAG")
        judgment = next(iter(self.state()["runs"].values()))["judgments"][0]
        self.assertFalse(judgment["applied"])
        self.assertEqual({v["source"] for v in judgment["field_decisions"].values()}, {"llm"})

    def test_response_feedback_is_reserved_for_llm_even_if_jev_says_greeting(self):
        self.enable()
        self.labels["intent"] = "greeting"
        self.decision = legacy.intent("question", reply_feedback="response_only",
                                      light_reply="抱歉，刚才的回应太机械了。我会回应你具体问的内容。")
        self.replacement = self.decision
        with patch.object(self.harness, "_prepare_teaching", side_effect=AssertionError("no teaching")):
            accepted = self.send("为什么你只会回我这句话")
        run = self.state()["runs"][accepted.run_id]
        self.assertTrue(run["reply_feedback_handled"])
        self.assertFalse(run["judgments"][0]["applied"])
        self.assertEqual([s for s, _ in self.calls], [IntentRemainder])
        self.assertEqual(self.state()["messages"][-1]["content"], self.decision.light_reply)

    def test_cross_session_replacement_cannot_be_overruled_by_program_new_topic(self):
        self.enable()
        rid, rev = self.active_run()
        self.replacement = legacy.intent("continue", scope="continue_goal", continuation_evidence="继续上次没学完的 RAG")
        out = resolve_entry(self.harness, self.sid, rid, rev,
            {"current_inputs": ["继续上次没学完的 RAG"], "task": None}, "受控测试", "router")
        self.assertEqual(out.intents, ["continue"])
        self.assertEqual(out.scope, "continue_goal")
        self.assertEqual(out.continuation_evidence, "继续上次没学完的 RAG")
        self.assertFalse(self.state()["runs"][rid]["judgments"][0]["applied"])

    def test_social_with_unresolved_tool_conflict_requires_full_decision(self):
        self.enable()
        self.labels.update(intent="greeting", needs_verification="yes")
        self.decision = legacy.intent("greeting", "question", answer_only=True)
        self.send("你好，解释 RAG")
        run = next(iter(self.state()["runs"].values()))
        self.assertIn("question", run["intent"]["intents"])
        self.assertFalse(run["judgments"][0]["applied"])
        self.assertEqual(run["judgments"][0]["reason"], "social_tool_conflict")

    def test_entry_cache_invalidation_includes_rule_version_and_old_records_are_readable(self):
        self.enable()
        rid, rev = self.active_run()
        request = entry_request({"current_inputs": ["解释 RAG"]})
        first = self.engine.judge(self.harness, self.sid, rid, rev, request)
        self.engine.judge(self.harness, self.sid, rid, rev, request.model_copy(update={"version": "future-rule"}))
        self.assertEqual(len(self.http_calls), 2)
        old = first.model_dump(exclude={"field_decisions"})
        self.assertEqual(JudgmentResult.model_validate(old).field_decisions, {})

    def test_late_llm_patch_cannot_commit_after_revision_changes(self):
        self.enable()
        rid, rev = self.active_run()
        self.labels["refresh_sources"] = "unsure"
        remainder = IntentRemainder(**legacy.intent("question", answer_only=True).model_dump(exclude=OWNED),
            updates={"refresh_sources": {"value": "no", "reason": "无刷新要求"}})
        def late(*args, **kwargs):
            with self.store.transaction(self.sid) as data:
                data["runs"][rid]["revision"] += 1
            return remainder
        with patch.object(self.harness, "_call", side_effect=late), self.assertRaises(Superseded):
            resolve_entry(self.harness, self.sid, rid, rev, {"current_inputs": ["解释 RAG"]}, "受控测试", "router")
        judgment = self.state()["runs"][rid]["judgments"][0]
        self.assertFalse(judgment["applied"])
        self.assertFalse(judgment["field_decisions"])

    def test_report_separates_field_adoption_from_full_llm_agreement_and_legacy(self):
        from tests.judgment_comparison.harness_integration import entry_composition
        fields = {"intent": {"source": "jev", "value": "question", "raw_choice": "question"},
                  "relation": {"source": "program", "value": "new_topic"},
                  "refresh_sources": {"source": "llm", "value": "no", "raw_choice": "unsure"}}
        partial = dict(node="entry", status="uncertain", applied=True, field_decisions=fields)
        replacement = dict(node="entry", status="ok", applied=False, field_decisions={
            key: dict(value, source="llm") for key, value in fields.items()})
        legacy_record = dict(node="entry", status="ok", applied=True)
        result = entry_composition([dict(id=str(i), kind="dialogue", variant="jev", run={"judgments": [j]})
            for i, j in enumerate([partial, replacement, legacy_record])])
        self.assertEqual(result["categories"], {"partial_jev": 1, "full_llm": 1, "legacy_without_field_trace": 1})
        self.assertEqual(result["field_sources"]["intent"], {"jev": 1, "llm": 1})

    def test_explicit_mode_is_not_replaced_with_auto_answer_only(self):
        self.enable()
        self.decision = legacy.intent("question", workflow="problem_solving", scope="learning")
        self.send("RAG 是什么", mode="problem_solving")
        data = self.state()
        self.assertEqual(data["tasks"][data["active_task_id"]]["mode"], "problem_solving")
        self.assertTrue(any(s is ScoredProblemCoachBundle for s, _ in self.calls))
        self.assertNotIn("workflow", self.http_calls[0]["questions"])

    def test_companionship_retains_existing_bounded_reply(self):
        self.enable()
        self.labels["intent"] = "companionship"
        self.decision = legacy.intent("social", conversation_kind="companionship")
        self.send("只想随便聊聊")
        run = next(iter(self.state()["runs"].values()))
        self.assertEqual(run["social_reply_kind"], "companionship")
        self.assertFalse(self.state()["tasks"])

    def test_oversized_node_inputs_fall_back_without_invalid_jev_request(self):
        self.enable()
        rid, rev = self.active_run()
        self.assertIsNone(select(self.harness, self.sid, rid, rev, node="memory_selection", topic=["RAG"],
            candidates=[{"id": str(i), "excerpt": "合成记录"} for i in range(129)]))
        task = {"context": {"last_lesson": LESSON}}
        bind_standard(task, "解释 RAG", rubric().model_copy(update={"must_cover": ["要点"] * 128}))
        self.assertNotIn("check_standard", task["context"])
        self.assertFalse(self.http_calls)

    def test_llm_product_boundary_overrules_entry_without_field_overwrite(self):
        self.enable()
        self.decision = legacy.intent("capabilities", programming_boundary="capability_question")
        self.replacement = self.decision
        self.send("你有 coding 的能力吗")
        run = next(iter(self.state()["runs"].values()))
        self.assertTrue(run.get("programming_scope_reply"))
        self.assertFalse(run.get("resource_scope_reply"))
        self.assertFalse(run["judgments"][0]["applied"])

    def test_llm_defer_is_respected_even_if_jev_proposes_knowledge(self):
        self.enable()
        self.replacement = legacy.intent("defer", light_reply="好的，先休息。")
        self.send("今天先不学了")
        data = self.state()
        self.assertFalse(data["tasks"])
        self.assertFalse(any(s is ScoredConversationOutput for s, _ in self.calls))
        self.assertIn("先休息", data["messages"][-1]["content"])

    def test_entry_does_not_receive_cross_session_candidates_or_handoff(self):
        request = entry_request(dict(current_inputs=["继续讲解"], recent_messages=[], task=None,
            continuation_candidates=[{"goal": "别的课程"}], related_learning=["旧记录"],
            handoff={"goal": "另一个目标"}, continuation_selection={"task_ids": ["foreign"]}))
        self.assertNotIn("别的课程", json.dumps(request.state, ensure_ascii=False))
        self.assertNotIn("handoff", request.state)
        self.assertNotIn("continuation_selection", request.state)

    def test_empty_selection_is_success_not_a_request_to_call_llm(self):
        self.enable()
        rid, rev = self.active_run()
        out = select(self.harness, self.sid, rid, rev, node="memory_selection", topic=["RAG"],
                     candidates=[{"id": "a", "excerpt": "无关内容"}])
        self.assertEqual(out.selections, [])
        self.assertFalse(self.calls)
        self.assertTrue(self.state()["runs"][rid]["judgments"][-1]["applied"])

    def test_selection_deduplicates_and_enforces_official_domain(self):
        self.enable()
        rid, rev = self.active_run()
        self.labels.update(a="relevant", b="relevant", c="relevant")
        out = select(self.harness, self.sid, rid, rev, node="source_candidates", topic="官方解释",
            candidates=[{"id": "a", "url": "https://docs.example.org/a"},
                        {"id": "b", "url": "https://docs.example.org/a"},
                        {"id": "c", "url": "https://mirror.invalid/a"}], domains=["example.org"])
        self.assertEqual([x.url for x in out.candidates], ["https://docs.example.org/a"])

    def test_duplicate_ids_and_uncertainty_request_fallback(self):
        self.enable()
        rid, rev = self.active_run()
        candidates = [{"id": "a", "excerpt": "合成"}, {"id": "a", "excerpt": "另一条"}]
        self.assertIsNone(select(self.harness, self.sid, rid, rev, node="memory_selection", topic="x", candidates=candidates))
        self.assertFalse(self.http_calls)
        self.labels["a"] = "unsure"
        self.assertIsNone(select(self.harness, self.sid, rid, rev, node="memory_selection", topic="x", candidates=candidates[:1]))

    def test_evidence_reports_only_supporting_pages_and_complex_conflict_falls_back(self):
        self.enable()
        rid, rev = self.active_run()
        pages = [{"url": "https://a.example/a", "content": "合成支持正文"},
                 {"url": "https://b.example/b", "content": "无关正文"}]
        self.labels["claim_0_page_1"] = "insufficient"
        out = assess_evidence(self.harness, self.sid, rid, rev, claims=["合成事实"], pages=pages,
                              query="核对事实", current_date="2026-09-20")
        self.assertEqual(out.sources, ["https://a.example/a"])
        self.assertEqual(out.state, "scoped")
        self.labels["claim_0_page_1"] = "contradicted"
        out = assess_evidence(self.harness, self.sid, rid, rev, claims=["另一个事实"], pages=pages,
                              query="核对事实", current_date="2026-09-20")
        self.assertIsNone(out)

    def test_cache_is_bound_to_candidate_content_version_and_mode(self):
        self.enable()
        rid, rev = self.active_run()
        req = JudgmentRequest(node="memory_selection", state={"candidate": "a", "version": 1},
                              questions={"a": question("相关性", {"relevant": "相关", "irrelevant": "无关"})})
        first = self.engine.judge(self.harness, self.sid, rid, rev, req)
        again = self.engine.judge(self.harness, self.sid, rid, rev, req)
        self.assertTrue(again.cached)
        self.assertEqual(len(self.http_calls), 1)
        changed = req.model_copy(update={"state": {"candidate": "a", "version": 2}})
        self.engine.judge(self.harness, self.sid, rid, rev, changed)
        with self.store.transaction(self.sid) as data:
            data["mode"] = "source_learning"
        self.engine.judge(self.harness, self.sid, rid, rev, changed)
        self.assertEqual(len(self.http_calls), 3)

    def test_budget_reserves_fallback_without_increasing_limits(self):
        self.enable()
        rid, rev = self.active_run()
        with self.store.transaction(self.sid) as data:
            data["runs"][rid]["execution_budget"] = dict(attempts=11, estimated_input_tokens=0, started=time.time())
        out = self.engine.judge(self.harness, self.sid, rid, rev, entry_request({"current_inputs": ["合成"]}))
        self.assertEqual(out.reason, "fallback_budget_reserved")
        self.assertFalse(self.http_calls)

    def test_timeout_returns_without_accepting_late_result(self):
        self.enable()
        self.engine.timeout = .03
        self.extra_delay = .12
        rid, rev = self.active_run()
        out = self.engine.judge(self.harness, self.sid, rid, rev, entry_request({"current_inputs": ["合成"]}))
        self.assertEqual((out.status, out.reason), ("failed", "timeout"))
        time.sleep(.15)
        run = self.state()["runs"][rid]
        self.assertFalse(run.get("judgment_cache"))
        self.assertFalse(run["judgments"][0]["applied"])
        self.assertEqual(run["model_calls"][0]["status"], "late_return")

    def test_fallback_keeps_original_failure_cause(self):
        self.enable()
        self.engine.client.blocked.set()
        rid, rev = self.active_run()
        out = self.engine.judge(self.harness, self.sid, rid, rev, entry_request({"current_inputs": ["合成"]}))
        self.engine.disposition(self.harness, self.sid, rid, rev, out, applied=False, reason="llm_point_fallback")
        self.assertEqual(self.state()["runs"][rid]["judgments"][-1]["reason"], "authentication_disabled")

    def test_superseded_result_raises_instead_of_falling_back(self):
        self.enable()
        self.extra_delay = .12
        rid, rev = self.active_run()
        def supersede():
            with self.store.transaction(self.sid) as data:
                data["runs"][rid]["revision"] += 1
        timer = threading.Timer(.03, supersede)
        timer.start()
        try:
            with self.assertRaises(Superseded):
                self.engine.judge(self.harness, self.sid, rid, rev, entry_request({"current_inputs": ["合成"]}))
        finally:
            timer.join()
            time.sleep(.13)
        self.assertFalse(self.state()["runs"][rid].get("judgments"))
        self.assertFalse(self.calls)

    def teach(self):
        self.enable()
        self.labels["intent"] = "other"
        self.decision = legacy.intent("goal", workflow="source_learning", scope="learning",
                                      direct_teaching=True, learning_goal_ready=True, target_description="学习 RAG")
        self.send("直接教我 RAG")
        return self.state()["tasks"][self.state()["active_task_id"]]

    def test_rubric_is_bound_before_answer_and_misconception_prevents_pass(self):
        task = self.teach()
        self.assertIsNotNone(standard_for(task, task["context"]["check_question"]))
        fingerprint = task["context"]["check_standard"]["fingerprint"]
        self.labels["misconception"] = "present"
        self.decision = legacy.intent("answer", scope="continue_goal")
        self.send("先检索再生成，而且保证永远不会出错")
        run = list(self.state()["runs"].values())[-1]
        self.assertEqual(run["point_evaluation"]["standard_fingerprint"], fingerprint)
        self.assertFalse(run["point_evaluation"]["passed"])
        self.assertNotEqual(self.state()["tasks"][task["task_id"]]["context"]["understanding"], "verified")

    def test_uncertain_point_is_rejudged_with_same_standard_not_rewritten_answer(self):
        self.teach()
        self.labels["point_1"] = "unsure"
        self.decision = legacy.intent("answer", scope="continue_goal")
        answer = "找相关文档，再让模型据此组织回答"
        self.send(answer)
        run = list(self.state()["runs"].values())[-1]
        self.assertEqual(run["point_evaluation"]["llm_fallback_items"], ["point_1"])
        payload = next(p for s, p in self.calls if s.__name__ == "PointJudgmentFallback")
        self.assertEqual(payload["state"]["answer"], answer)
        self.assertEqual(list(payload["questions"]), ["point_1"])
        self.assertTrue(run["point_evaluation"]["passed"])

    def test_hint_and_missing_points_do_not_mark_mastery(self):
        task = self.teach()
        with self.store.transaction(self.sid) as data:
            data["tasks"][task["task_id"]]["context"]["hint_used"] = True
        self.decision = legacy.intent("answer", scope="continue_goal")
        self.send("先检索，然后用检索结果生成")
        run = list(self.state()["runs"].values())[-1]
        self.assertFalse(run["point_evaluation"]["effective_passed"])
        self.assertNotEqual(self.state()["tasks"][task["task_id"]]["context"]["understanding"], "verified")
        self.labels["point_0"] = "missing"
        self.labels["point_1"] = "missing"
        self.send("我懂了")
        run = list(self.state()["runs"].values())[-1]
        self.assertFalse(run["point_evaluation"]["passed"])

    def test_changed_question_or_reference_invalidates_standard(self):
        task = self.teach()
        task["context"]["check_question"] = "另一个问题"
        self.assertIsNone(standard_for(task, task["context"]["check_question"]))
        task = copy.deepcopy(self.state()["tasks"][task["task_id"]])
        task["context"]["last_lesson"] += "修改过的内容"
        self.assertIsNone(standard_for(task, task["context"]["check_question"]))

    def test_question_binding_uses_actual_pre_answer_material_instead_of_generated_quote(self):
        task = {"context": {"last_lesson": "RAG **先检索**相关资料，再据此生成。"}}
        bind_standard(task, "RAG 如何工作", rubric().model_copy(update={"evidence": "先检索……再生成。"}))
        frozen = standard_for(task, "RAG 如何工作")
        self.assertIsNotNone(frozen)
        self.assertEqual(frozen.evidence, task["context"]["last_lesson"])

    def test_legacy_question_keeps_old_evaluation_and_never_builds_a_rubric_after_answer(self):
        task = self.teach()
        with self.store.transaction(self.sid) as data:
            data["tasks"][task["task_id"]]["context"].pop("check_standard")
        self.decision = legacy.intent("answer", scope="continue_goal")
        before = len(self.http_calls)
        self.send("旧题答案")
        run = list(self.state()["runs"].values())[-1]
        self.assertNotIn("point_evaluation", run)
        self.assertTrue(any(s is ScoredMasteryEvaluation for s, _ in self.calls))
        self.assertEqual(len(self.http_calls) - before, 1)  # entry only, no Jev grading

    def test_real_memory_node_skips_original_llm_selection(self):
        from tests.judgment_comparison.harness_integration import node_cases, run_node
        self.enable()
        self.labels.update(m1="prerequisite", m2="irrelevant")
        row = next(c for c in node_cases() if c["id"] == "memory-direct")
        result = run_node(self.harness, row)
        self.assertTrue(result["checks"]["selection"])
        self.assertFalse(any(s is MemoryChoice for s, _ in self.calls))
        self.assertEqual(result["run"]["model_calls"][0]["transport_requests"], 1)

    def test_real_source_pipeline_uses_jev_with_frozen_search_results(self):
        from tests.judgment_comparison.harness_integration import node_cases, run_node
        from agent_service.schemas import SourceList
        self.enable()
        self.labels.update({"0": "irrelevant", "1": "relevant", "2": "irrelevant"})
        row = next(c for c in node_cases() if c["id"] == "source-official")
        result = run_node(self.harness, row)
        self.assertTrue(result["checks"]["selection"])
        self.assertFalse(any(s is SourceList for s, _ in self.calls))
        self.assertEqual(result["run"]["judgments"][0]["node"], "source_candidates")

    def test_real_evidence_pipeline_uses_claims_and_original_pages(self):
        from tests.judgment_comparison.harness_integration import node_cases, run_node
        self.enable()
        row = next(c for c in node_cases() if c["id"] == "evidence-supported")
        result = run_node(self.harness, row)
        self.assertTrue(result["checks"]["support_state"])
        self.assertEqual(result["run"]["judgments"][-1]["node"], "evidence_assessment")
        self.assertFalse(any(s is EvidenceAssessmentV2 for s, _ in self.calls))

    def test_node_probe_binds_grading_before_real_evaluation(self):
        from tests.judgment_comparison.harness_integration import node_cases, run_node
        self.enable()
        row = next(c for c in node_cases() if c["id"] == "grade-photosynthesis-correct")
        result = run_node(self.harness, row)
        self.assertTrue(result["checks"]["passed"])
        self.assertIn("point_evaluation", result["run"])

    def test_preflight_is_offline_and_rejects_credential_flags(self):
        import contextlib
        import io
        from tests.run_jev_harness import main
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([]), 0)
        self.assertEqual(json.loads(output.getvalue())["paired_runs"], 116)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--jev-key-stdin"])
        self.assertFalse(self.http_calls)

    def test_selection_audit_distinguishes_equivalence_duplicates_and_irrelevance(self):
        from tests.judgment_comparison.harness_integration import node_cases, selection_outcome
        row = next(c for c in node_cases() if c["id"] == "memory-duplicates")
        self.assertTrue(selection_outcome(row, ["m2"])["content_selection_passed"])
        self.assertFalse(selection_outcome(row, ["m1", "m2"])["content_selection_passed"])
        self.assertEqual(selection_outcome(row, ["m3"])["false_selected"], ["m3"])
        self.assertFalse(selection_outcome(row, ["unknown"])["content_selection_passed"])


if __name__ == "__main__":
    unittest.main()
