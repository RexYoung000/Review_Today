"""Quality decisions are exercised through real Harness budgets and publication."""
import json
import threading
import time
import unittest
from unittest.mock import patch

from tests import test_judgment_harness as fixtures
from tests.test_m1_capture_contract import valid_extracted
from agent_service import conversation
from agent_service.capture import run_capture, semantic_validate_node
from agent_service.conversation_store import Superseded
from agent_service.judgment_grading import ScoredConversationOutput, ScoredProblemCoachBundle, standard_for
from agent_service.judgment_quality import capture_quality, checked_question, RepairedQuestion, question_request
from agent_service.schemas import ExtractPayload, SemanticVerdict, RiskVerdict

SOURCE = "植物利用光能，把二氧化碳和水转化为有机物，并释放氧气。"


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.HarnessJudgmentTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.f.enable()
        self.good = ExtractPayload.model_validate(valid_extracted(SOURCE))
        self.bad = self.good.model_copy(deep=True)
        self.bad.knowledge[0].explanation = "1. 植物直接从土壤吸收有机物。\n2. 植物不需要光能。"
        self.repair_good, self.extract_bad, self.fallback_unsure = True, False, False
        self.extra_calls = []
        patched = patch.object(conversation, "parse_model", side_effect=self.model)
        patched.start()
        self.addCleanup(patched.stop)

    def model(self, system, user, schema, **kwargs):
        self.extra_calls.append((schema, user))
        if schema is ExtractPayload:
            if "上一稿" in user and self.repair_good:
                self.f.labels["card_0_faithful"] = "pass"
                return self.good
            return self.bad if self.extract_bad else self.good
        if schema is SemanticVerdict:
            return SemanticVerdict(ok=True)
        if schema is RiskVerdict:
            return RiskVerdict(risk=False, reason="合成稳定知识")
        if schema.__name__ == "QualityJudgmentFallback":
            return schema(**{k: "unsure" if self.fallback_unsure else "pass" for k in schema.model_fields})
        if schema is RepairedQuestion:
            if self.repair_good:
                self.f.labels["scope"] = "pass"
            return RepairedQuestion(question="请解释 RAG 的两个主要步骤。", scoring_spec=fixtures.rubric())
        return self.f.model(system, user, schema, **kwargs)

    def active(self):
        rid, rev = self.f.active_run()
        return self.f.harness, self.f.sid, rid, rev

    def capture(self, args, *, enabled=True):
        h, sid, rid, rev = args
        return run_capture("synthetic-capture", SOURCE, "zh", confirmed_content=True,
            model_runner=lambda system, user, schema, **kw: h._call(sid, rid, rev, "memory_" + schema.__name__, system, user, schema),
            quality_runner=(lambda source, extracted, language, **kw:
                capture_quality(*args, source, extracted, language, task_id="synthetic-capture", **kw)) if enabled else None)

    def test_valid_capture_replaces_semantic_llm_and_keeps_program_checks(self):
        args = self.active()
        result = self.capture(args)
        self.assertEqual(result["outcome"], "committing")
        self.assertFalse(any(s is SemanticVerdict for s, _ in self.extra_calls))
        self.assertTrue(self.f.state()["runs"][args[2]]["judgments"][-1]["applied"])
        broken = self.good.model_copy(deep=True)
        broken.knowledge[0].evidence_excerpt = "不存在的引文"
        state = dict(raw_text=SOURCE, extracted=broken.model_dump(), primary_language="zh", events=[],
                     quality_runner=lambda *a, **kw: SemanticVerdict(ok=True))
        self.assertFalse(semantic_validate_node(state).get("semantic_ok", False))

    def test_disabled_capture_retains_existing_semantic_model(self):
        result = self.capture(self.active(), enabled=False)
        self.assertEqual(result["outcome"], "committing")
        self.assertTrue(any(s is SemanticVerdict for s, _ in self.extra_calls))
        self.assertFalse(self.f.http_calls)

    def test_bad_capture_repaired_once_with_specific_issues_and_rechecked(self):
        self.extract_bad = True
        self.f.labels["card_0_faithful"] = "needs_fix"
        result = self.capture(self.active())
        self.assertEqual(result["outcome"], "committing")
        self.assertEqual(len(self.f.http_calls), 2)
        repairs = [p for s, p in self.extra_calls if s is ExtractPayload and "上一稿" in p]
        self.assertEqual(len(repairs), 1)
        self.assertIn("card_0_faithful", repairs[0])
        self.assertEqual(result["extracted"], self.good.model_dump())

    def test_bad_capture_still_bad_after_repair_cannot_commit(self):
        self.extract_bad, self.repair_good = True, False
        self.f.labels["card_0_faithful"] = "needs_fix"
        result = self.capture(self.active())
        self.assertEqual(result["outcome"], "needs_attention")
        self.assertFalse(any(s is RiskVerdict for s, _ in self.extra_calls))
        self.assertEqual(sum(s is ExtractPayload for s, _ in self.extra_calls), 2)

    def test_capture_uncertainty_goes_back_to_existing_llm(self):
        self.f.labels["grouping"] = "unsure"
        result = self.capture(self.active())
        self.assertEqual(result["outcome"], "committing")
        prompts = [p for s, p in self.extra_calls if s is SemanticVerdict]
        self.assertEqual(len(prompts), 1)
        self.assertIn("原文", prompts[0])

    def test_question_partial_fallback_asks_only_unsure_fields(self):
        args = self.active()
        self.f.labels["scope"] = "unsure"
        text, spec = checked_question(*args, "RAG 如何工作？", fixtures.rubric(), fixtures.LESSON, owner="a")
        pending = next(json.loads(p) for s, p in self.extra_calls if s.__name__ == "QualityJudgmentFallback")
        self.assertEqual(list(pending["questions"]), ["scope"])
        self.assertEqual(text, "RAG 如何工作？")
        self.assertEqual(spec, fixtures.rubric())

    def test_question_failure_and_budget_skip_use_llm_not_pass_or_negative(self):
        for reason in ("authentication", "budget"):
            with self.subTest(reason=reason):
                args = self.active()
                if reason == "authentication":
                    self.f.engine.client.blocked.set()
                else:
                    self.f.engine.client.blocked.clear()
                    with self.f.store.transaction(self.f.sid) as data:
                        data["runs"][args[2]]["execution_budget"]["attempts"] = 10
                checked_question(*args, "RAG 如何工作？", fixtures.rubric(), fixtures.LESSON, owner="a")
                self.assertFalse(self.f.http_calls)
                run = self.f.state()["runs"][args[2]]
                self.assertEqual(run["judgments"][-1]["status"], "skipped")
                self.assertEqual(run["quality_checks"][-1]["reason"], "quality_llm_fallback")

    def test_question_repair_changes_binding_and_visible_embedded_question(self):
        self.f.labels["scope"] = "needs_fix"
        def model(system, user, schema, **kw):
            value = self.model(system, user, schema, **kw)
            if schema is ScoredConversationOutput:
                value.message += "\n\n" + value.check_question
                kw["on_partial"](value.model_dump())
            return value
        with patch.object(conversation, "parse_model", side_effect=model):
            task = self.f.teach()
        data = self.f.state()
        standard = standard_for(task, task["context"]["check_question"])
        self.assertIsNotNone(standard)
        self.assertEqual(task["context"]["check_question"], "请解释 RAG 的两个主要步骤。")
        replies = [m["content"] for m in data["messages"] if m["role"] == "coach"]
        self.assertNotIn("RAG 如何工作？", "\n".join(replies))
        self.assertFalse(any(e["stage"] == "response.delta" for e in data["events"]))
        self.assertEqual(len(next(iter(data["runs"].values()))["quality_checks"]), 2)

    def test_unresolved_question_is_not_published_or_bound(self):
        self.f.labels["scope"] = "needs_fix"
        self.repair_good = False
        self.f.teach()
        data = self.f.state()
        run = next(iter(data["runs"].values()))
        self.assertEqual(run["status"], "retryable_failed")
        self.assertFalse(any(m["role"] == "coach" for m in data["messages"]))
        self.assertNotIn("check_standard", data["tasks"][data["active_task_id"]]["context"])
        self.assertEqual(sum(s is RepairedQuestion for s, _ in self.extra_calls), 1)

    def test_old_or_open_question_does_not_create_a_new_rubric(self):
        args = self.active()
        self.assertEqual(checked_question(*args, "想学什么？", None, "", owner="a"), ("想学什么？", None))
        self.assertFalse(self.f.http_calls or self.extra_calls)

    def test_auto_material_with_explicit_teaching_keeps_learning_and_quality_gate(self):
        self.f.labels["intent"] = "other"
        self.f.decision = fixtures.legacy.intent("material", "goal", workflow="source_learning", scope="learning",
            direct_teaching=True, learning_goal_ready=True, target_description="按给定材料教学并检查理解")
        accepted = self.f.send("请直接教我这段 RAG 材料，并出一道理解检查题")
        data = self.f.state()
        task = data["tasks"][data["active_task_id"]]
        self.assertEqual(task["mode"], "source_learning")
        self.assertIsNotNone(standard_for(task, task["context"]["check_question"]))
        self.assertTrue(data["runs"][accepted.run_id].get("quality_checks"))

    def test_problem_calibration_is_checked_before_binding(self):
        self.f.labels["scope"] = "needs_fix"
        original_question = []
        def model(system, user, schema, **kw):
            value = self.model(system, user, schema, **kw)
            if schema is ScoredProblemCoachBundle:
                value.analysis.check_scoring_spec = fixtures.rubric()
                original_question.append(value.analysis.calibration_question)
                value.answer.spoken_answer = value.analysis.calibration_question
            if schema is RepairedQuestion:
                value.question = "请先说明：" + original_question[0]
            return value
        self.f.decision = fixtures.legacy.intent("question", workflow="problem_solving")
        with patch.object(conversation, "parse_model", side_effect=model):
            accepted = self.f.send("RAG 是什么？", mode="problem_solving")
        data = self.f.state()
        self.assertTrue(data["runs"][accepted.run_id].get("quality_checks"))
        task = data["tasks"][data["active_task_id"]]
        self.assertIsNotNone(standard_for(task, task["context"]["check_question"]))
        self.assertNotIn("请先说明：请先说明：", data["messages"][-1]["content"])
        self.assertIn("请先说明：" + original_question[0], data["messages"][-1]["content"])

    def test_oversized_atomic_rubric_falls_back_without_truncating_points(self):
        args = self.active()
        spec = fixtures.rubric().model_copy(update={"must_cover": ["检索"] * 126})
        checked_question(*args, "RAG 如何工作？", spec, fixtures.LESSON, owner="a")
        self.assertFalse(self.f.http_calls)
        prompt = next(json.loads(p) for s, p in self.extra_calls if s is SemanticVerdict)
        self.assertEqual(len(prompt["scoring_spec"]["must_cover"]), 126)
        self.assertEqual(self.f.state()["runs"][args[2]]["quality_checks"][-1]["reason"], "question_limit")

    def test_retry_repeats_failed_repair_instead_of_replaying_bad_cached_repair(self):
        self.f.labels["scope"] = "needs_fix"
        self.repair_good = False
        self.f.teach()
        rid = next(iter(self.f.state()["runs"]))
        self.repair_good = True
        self.f.control(rid, "retry")
        self.f.harness.drain(self.f.sid)
        self.assertEqual(self.f.state()["runs"][rid]["status"], "completed")
        self.assertEqual(sum(s is RepairedQuestion for s, _ in self.extra_calls), 2)

    def test_transport_faults_use_quality_fallback_without_fabricating_a_verdict(self):
        from agent_service.judgment_types import JudgmentResult
        for reason in ("timeout", "invalid_response", "connection_failed"):
            with self.subTest(reason=reason):
                args = self.active()
                failed = JudgmentResult(node="question_quality", input_hash="synthetic", status="failed", reason=reason)
                with patch.object(self.f.engine.client, "call", return_value=(failed, None)):
                    checked_question(*args, "RAG 如何工作？", fixtures.rubric(), fixtures.LESSON, owner="a")
                run = self.f.state()["runs"][args[2]]
                self.assertEqual(run["judgments"][-1]["reason"], reason)
                self.assertFalse(run["judgments"][-1]["applied"])
                self.assertEqual(run["quality_checks"][-1]["reason"], "quality_llm_fallback")

    def test_cache_invalidates_for_reference_question_rule_and_owner(self):
        args = self.active()
        request = question_request("RAG 如何工作？", fixtures.rubric(), fixtures.LESSON, owner="a")
        for changed in (request, request, request.model_copy(update={"version": "next"}),
                        question_request("说明局限", fixtures.rubric(), fixtures.LESSON, owner="a"),
                        question_request("RAG 如何工作？", fixtures.rubric(), fixtures.LESSON + "新参考", owner="a"),
                        question_request("RAG 如何工作？", fixtures.rubric(), fixtures.LESSON, owner="b")):
            self.f.engine.judge(*args, changed)
        self.assertEqual(len(self.f.http_calls), 5)

    def test_cancel_during_check_discards_late_result_without_fallback_or_repair(self):
        args = self.active()
        self.f.extra_delay = .15
        timer = threading.Timer(.035, lambda: self.f.control(args[2], "stop"))
        timer.start()
        try:
            with self.assertRaises(Superseded):
                checked_question(*args, "RAG 如何工作？", fixtures.rubric(), fixtures.LESSON, owner="a")
        finally:
            timer.join()
            time.sleep(.18)
        run = self.f.state()["runs"][args[2]]
        self.assertFalse(self.extra_calls or run.get("quality_checks") or run.get("judgments"))

    def test_answer_followup_checked_without_sending_student_answer_to_quality(self):
        self.f.teach()
        self.f.labels["misconception"] = "present"
        self.f.decision = fixtures.legacy.intent("answer", scope="continue_goal")
        answer = "用户独有答案标记：检索后保证永远不会出错"
        self.f.send(answer)
        run = list(self.f.state()["runs"].values())[-1]
        self.assertTrue(run.get("quality_checks"))
        quality_inputs = [p["state"] for p in self.f.http_calls if "question" in p["state"] and "reference" in p["state"]]
        self.assertTrue(quality_inputs)
        self.assertNotIn(answer, json.dumps(quality_inputs, ensure_ascii=False))
        task = self.f.state()["tasks"][self.f.state()["active_task_id"]]
        self.assertIsNotNone(standard_for(task, task["context"]["check_question"]))

    def test_save_memory_wires_real_capture_quality(self):
        self.f.decision = fixtures.legacy.intent("material", scope="organize", workflow="memory_organization")
        self.f.labels["intent"] = "other"
        self.f.send(SOURCE)
        with self.f.store.transaction(self.f.sid) as data:
            data["draft"].update(content=SOURCE, understanding="verified", source_type="user_material")
        pending = self.f.state()["pending"]
        self.f.decision = fixtures.legacy.intent("confirm")
        with patch.object(conversation, "run_capture", side_effect=run_capture):
            accepted = self.f.send("加入知识库", operation=pending)
        run = self.f.state()["runs"][accepted.run_id]
        self.assertTrue(any(j["node"] == "capture_quality" and j["applied"] for j in run.get("judgments", [])))
        task = self.f.state()["tasks"][run["task_id"]]
        self.assertEqual(task["status"], "committing")
        self.assertFalse(any(s is SemanticVerdict for s, _ in self.extra_calls))
