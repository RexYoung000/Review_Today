"""Ordinary checks must not turn partial answers into full-scope invitations."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_service.call_errors import ModelCallError
from agent_service.learning_progress import bind_check, current_step, guard_answer_coverage
from agent_service.schemas import MasteryEvaluation
from tests import test_conversation_v2 as fixture
from tests.test_conversation_v2 import intent


EVIDENCE = Path(__file__).resolve().parents[2] / "docs/evidence/2026-10-14-live-learning-save"
SEED = json.loads((EVIDENCE / "phase-01-lesson.json").read_text())["checkpoint"]
FAILED = json.loads((EVIDENCE / "phase-02-summary.json").read_text())["evaluation"]
TASK_ID = SEED["active_task_id"]
BINDING = SEED["tasks"][TASK_ID]["context"]["check_binding"]
REFERENCE = SEED["tasks"][TASK_ID]["context"]["last_lesson"]
PARTIAL = "相似度高只说明资料与问题在语义上接近，所以可能相关；但原资料仍可能有错误或过时。"
FULL = ("找出来的文字只是看着切题，不能凭这个分数保证事实。材料可能早就失效，或者本身写错。"
        "写回答时也可能自行添话，删掉原来的限制。要逐句找到原文根据，再看版本和使用场景是否合适。")
QUESTION_PARTS = ["为什么检索相似度高，仍不能保证 RAG 给出的答案正确", "来源资料方面",
                  "生成回答方面各有什么风险", "为什么还需要核对来源和适用条件"]
FULL_QUOTES = ["找出来的文字只是看着切题，不能凭这个分数保证事实。", "材料可能早就失效，或者本身写错。",
               "写回答时也可能自行添话，删掉原来的限制。", "要逐句找到原文根据，再看版本和使用场景是否合适。"]


def coverage(complete=False):
    quotes = FULL_QUOTES if complete else ["相似度高只说明资料与问题在语义上接近，所以可能相关", "原资料仍可能有错误或过时", "", ""]
    return [dict(question_quote=point, demonstrated=bool(quote), answer_quotes=[quote] if quote else [])
            for point, quote in zip(QUESTION_PARTS, quotes)]


def evaluation(**changes):
    return MasteryEvaluation.model_validate(dict(copy.deepcopy(FAILED), **changes))


class OrdinaryCoverageGuardTests(unittest.TestCase):
    def test_original_real_failure_without_answer_evidence_cannot_pass(self):
        value = evaluation()
        self.assertTrue(value.passed, "Preserve the original failed grader payload")
        guard_answer_coverage(value, BINDING, PARTIAL)
        self.assertFalse(value.passed)
        self.assertIn(FAILED["feedback"], value.feedback)
        self.assertIn("缺少可核对的作答依据", value.feedback)

    def test_missing_asked_items_override_true_without_erasing_partial_credit(self):
        value = evaluation(answer_coverage=coverage())
        value.validate_request(dict(check_binding=BINDING, reference=REFERENCE, answer=PARTIAL,
                                    learning_step=dict(title=BINDING["step_title"])))
        self.assertFalse(value.passed)
        self.assertIn("你答对了最关键的一点", value.feedback)
        self.assertIn("还缺两块", value.feedback)
        self.assertEqual(value.followup_question, FAILED["followup_question"])
        before = value.model_dump()
        guard_answer_coverage(value, BINDING, PARTIAL)
        self.assertEqual(value.model_dump(), before, "Request and publication guards must be idempotent")

    def test_complete_paraphrase_needs_no_matching_terminology(self):
        value = evaluation(answer_coverage=coverage(True), followup_question="")
        value.validate_request(dict(check_binding=BINDING, reference=REFERENCE, answer=FULL))
        self.assertTrue(value.passed)
        self.assertFalse(value.step_completion_demonstrated)
        self.assertNotIn("生成忠实性", FULL)

    def test_correctly_grounded_but_incorrect_item_cannot_pass(self):
        rows = coverage(True)
        rows[2]["demonstrated"] = False
        value = evaluation(answer_coverage=rows)
        guard_answer_coverage(value, BINDING, FULL)
        self.assertFalse(value.passed)

    def test_true_without_a_learner_quote_or_with_duplicate_items_cannot_pass(self):
        for kind in ("no_quote", "duplicate", "no_rows"):
            with self.subTest(kind=kind):
                rows = coverage(True)
                if kind == "no_quote":
                    rows[2]["answer_quotes"] = []
                elif kind == "duplicate":
                    rows.append(copy.deepcopy(rows[0]))
                else:
                    rows = []
                value = evaluation(answer_coverage=rows)
                guard_answer_coverage(value, BINDING, FULL)
                self.assertFalse(value.passed)

    def test_reference_feedback_question_or_paraphrase_cannot_replace_answer_quotes(self):
        invalid = [FAILED["capture_quotes"][2], FAILED["capture_feedback_quotes"][1],
                   QUESTION_PARTS[2], "模型会增加无依据的内容"]
        for quote in invalid:
            with self.subTest(quote=quote):
                rows = coverage(True)
                rows[2]["answer_quotes"] = [quote]
                value = evaluation(answer_coverage=rows)
                with self.assertRaises(ModelCallError) as caught:
                    value.validate_request(dict(check_binding=BINDING, reference=REFERENCE, answer=FULL))
                self.assertEqual(caught.exception.code, "RT.MODEL.SCHEMA")
                self.assertIn("question_answer_grounding", caught.exception.diagnostic)

    def test_lesson_only_requirement_cannot_be_added_to_question(self):
        rows = coverage(True)
        rows.append(dict(question_quote="说出完整索引构建流程", demonstrated=False, answer_quotes=[]))
        with self.assertRaises(ModelCallError):
            evaluation(answer_coverage=rows).validate_request(dict(check_binding=BINDING, reference=REFERENCE, answer=FULL))

    def test_existing_negative_verdict_is_never_promoted(self):
        value = evaluation(passed=False, answer_coverage=coverage(True))
        guard_answer_coverage(value, BINDING, FULL)
        self.assertFalse(value.passed)

    def test_legacy_unbound_and_comprehensive_grading_keep_their_own_contract(self):
        from agent_service.learning_progress import CHECK_SCOPE_POLICY
        comprehensive = dict(BINDING, scope="step", check_kind="comprehensive", scope_policy=CHECK_SCOPE_POLICY,
                             question="请说明来源和生成风险", request_message_id="message", request_run_id="run",
                             completion_condition="说明来源和生成风险", completion_requirements=["说明来源和生成风险"],
                             )
        from agent_service.learning_progress import comprehensive_bound
        self.assertTrue(comprehensive_bound(comprehensive))
        for binding in (None, comprehensive):
            with self.subTest(binding=binding):
                value = evaluation()
                guard_answer_coverage(value, binding, PARTIAL)
                self.assertTrue(value.passed)


class OrdinaryCoverageFlowTests(unittest.TestCase):
    setUp = fixture.ConversationTests.setUp
    tearDown = fixture.ConversationTests.tearDown
    send = fixture.ConversationTests.send
    state = fixture.ConversationTests.state

    def model(self, system, user, schema, **kwargs):
        if schema is MasteryEvaluation:
            self.calls.append((schema, json.loads(user)))
            return self.grade.model_copy(deep=True)
        return fixture.ConversationTests.model(self, system, user, schema, **kwargs)

    def seed(self, **changes):
        self.sid = SEED["session_id"]
        self.grade = evaluation(**changes)
        with self.store.transaction(self.sid) as data:
            data.update(copy.deepcopy(SEED))
        self.decision = intent("answer", workflow="source_learning", scope="continue_goal")

    def test_real_partial_failure_no_longer_creates_evidence_or_invitation(self):
        self.seed(answer_coverage=coverage())
        self.send(PARTIAL)
        state = self.state()
        task = state["tasks"][TASK_ID]
        practice = task["context"]["practice"][-1]
        run = state["runs"][practice["run_id"]]
        self.assertFalse(practice["evaluation"]["passed"])
        self.assertEqual(practice["verified_concepts"], [])
        self.assertEqual(run["verified_concepts"], [])
        self.assertFalse(current_step(task).get("verified_concepts"))
        self.assertEqual(task["context"]["understanding"], "unknown")
        self.assertFalse(state["capture_offers"])
        self.assertIsNone(state["draft"])
        self.assertIn(FAILED["followup_question"], state["messages"][-1]["content"])
        self.assertIn("你答对了最关键的一点", state["messages"][-1]["content"])
        self.assertEqual(task["context"]["check_question"], FAILED["followup_question"])
        self.assertEqual(sum(schema is MasteryEvaluation for schema, _ in self.calls), 1)
        self.capture.assert_not_called()

    def test_complete_answer_invites_only_this_question_without_chapter_mastery(self):
        self.seed(answer_coverage=coverage(True), feedback="答对了，两类风险和核对原因都说明了。",
                  capture_feedback_quotes=[], followup_question="")
        self.send(FULL)
        state = self.state()
        task = state["tasks"][TASK_ID]
        self.assertTrue(task["context"]["practice"][-1]["evaluation"]["passed"])
        self.assertEqual(task["context"]["practice"][-1]["verified_concepts"], BINDING["concepts"])
        self.assertEqual(current_step(task)["understanding"], "unknown")
        self.assertEqual(len(state["capture_offers"]), 1)
        offer = next(iter(state["capture_offers"].values()))
        self.assertEqual(offer["trigger"], "verified_check")
        self.assertEqual(offer["concepts"], BINDING["concepts"])
        self.assertFalse(offer["knowledge_ids"])
        self.capture.assert_not_called()

    def test_one_asked_point_does_not_require_the_rest_of_the_lesson(self):
        question, answer = "检索相似度高说明什么？", "说明文字和问题看着切题。"
        self.seed(feedback="答对了，只能说明相关。", followup_question="", capture_feedback_quotes=[],
                  answer_coverage=[dict(question_quote=question, demonstrated=True, answer_quotes=[answer])])
        with self.store.transaction(self.sid) as data:
            task = data["tasks"][TASK_ID]
            task["context"]["check_question"] = question
            bind_check(task, question, dict(step_title=BINDING["step_title"], concepts=["检索相似度"],
                       evidence_quotes=BINDING["evidence_quotes"], scope="concept"))
        self.send(answer)
        task = self.state()["tasks"][TASK_ID]
        self.assertTrue(task["context"]["practice"][-1]["evaluation"]["passed"])
        self.assertEqual(task["context"]["practice"][-1]["verified_concepts"], ["检索相似度"])
        self.assertEqual(current_step(task)["understanding"], "unknown")

    def test_complete_but_hinted_answer_still_cannot_trigger_invitation(self):
        self.seed(answer_coverage=coverage(True))
        with self.store.transaction(self.sid) as data:
            data["tasks"][TASK_ID]["context"]["hint_used"] = True
        self.send(FULL)
        self.assertFalse(self.state()["capture_offers"])
        self.assertFalse(self.state()["tasks"][TASK_ID]["context"]["practice"][-1]["evaluation"]["passed"])

    def test_stale_binding_does_not_grant_a_pass_even_with_complete_evidence(self):
        self.seed(answer_coverage=coverage(True), followup_question="")
        with self.store.transaction(self.sid) as data:
            data["tasks"][TASK_ID]["context"]["last_lesson"] += " 新版讲解。"
        self.send(FULL)
        self.assertFalse(self.state()["capture_offers"])
        self.assertFalse(self.state()["tasks"][TASK_ID]["context"]["practice"][-1]["evaluation"]["passed"])

    def test_explicit_save_after_incomplete_answer_does_not_require_an_exam(self):
        from agent_service.schemas import IntentOperation
        from tests.test_m1_capture_contract import committing_result
        self.seed(answer_coverage=coverage())
        self.send(PARTIAL)
        self.calls.clear()
        text = "保存刚才这段讲解"
        self.decision = intent("confirm", workflow="source_learning", scope="continue_goal",
                               proposed_actions=[IntentOperation(kind="save", disposition="request", evidence=text)])
        self.capture.return_value = committing_result(REFERENCE)
        self.send(text)
        self.capture.assert_called_once()
        self.assertFalse(any(schema is MasteryEvaluation for schema, _ in self.calls))
        self.assertEqual(self.state()["tasks"][TASK_ID]["context"]["understanding"], "unknown")
