"""Offline provenance checks for invitation excerpts, separate from grading."""
import copy
import json
from contextlib import contextmanager
from types import SimpleNamespace
import unittest

from pydantic import ValidationError

from agent_service.call_errors import ModelCallError
from agent_service.judgment_grading import (
    CAPTURE_QUOTE_RULE, JudgmentFeedback, ScoredMasteryEvaluation,
    bind_standard, evaluate,
)
from agent_service.learning_progress import bind_check, bound_check, check_reference, set_plan
from agent_service.schemas import MasteryEvaluation, ScoringSpec


REFERENCE = "关键词匹配看字词重合。**语义匹配**看意思是否接近。阈值为 `0.8`，不保证命中。"
FEEDBACK = "语义接近不代表一定命中。你的回答已通过。下一题：索引怎样建立？"


def feedback_values(**changes):
    return dict(correctness="正确", completeness="足够", expression="清楚", transfer="尚未检查",
                feedback=FEEDBACK, **changes)


class EvaluationQuoteContractTests(unittest.TestCase):
    def evaluation(self, **changes):
        return MasteryEvaluation(passed=True, **feedback_values(**changes))

    def test_old_outputs_keep_empty_excerpts_and_original_pass(self):
        for value in (self.evaluation(), JudgmentFeedback(**feedback_values()),
                      ScoredMasteryEvaluation(passed=True, **feedback_values())):
            with self.subTest(schema=type(value).__name__):
                value.validate_request({})
                self.assertEqual(value.capture_quotes, [])
                self.assertEqual(value.capture_feedback_quotes, [])
                if hasattr(value, "passed"):
                    self.assertTrue(value.passed)

    def test_exact_excerpts_preserve_source_format_without_changing_grading(self):
        quotes = ["**语义匹配**看意思是否接近。", "阈值为 `0.8`，不保证命中。"]
        value = self.evaluation(capture_quotes=quotes, capture_feedback_quotes=["语义接近不代表一定命中。"])
        before = value.model_dump()
        value.validate_request(dict(reference=REFERENCE))
        self.assertEqual(value.model_dump(), before)

    def test_reference_excerpt_validation_runs_before_every_followup_early_return(self):
        payloads = [{}, dict(reference=REFERENCE), dict(reference=REFERENCE, check_binding={"step_id": "step"})]
        for payload in payloads:
            with self.subTest(payload=payload):
                value = self.evaluation(capture_quotes=["用户自己写的答案，未在参考中出现。"])
                with self.assertRaises(ModelCallError) as caught:
                    value.validate_request(payload)
                self.assertEqual(caught.exception.code, "RT.MODEL.SCHEMA")
                self.assertEqual(json.loads(caught.exception.diagnostic)[0]["field"], ["capture_quotes"])
                self.assertTrue(value.passed)

    def test_capture_quotes_require_verbatim_format_numbers_and_punctuation(self):
        for quote in ("语义匹配看意思是否接近。", "阈值为 `0.9`，不保证命中。", "关键词匹配看字词重合!", "未提供的资料"):
            with self.subTest(quote=quote), self.assertRaises(ModelCallError):
                self.evaluation(capture_quotes=[quote]).validate_request(dict(reference=REFERENCE))

    def test_feedback_excerpt_cannot_borrow_an_excerpt_from_reference(self):
        for schema in (MasteryEvaluation, JudgmentFeedback, ScoredMasteryEvaluation):
            with self.subTest(schema=schema.__name__):
                value = schema(**feedback_values(capture_feedback_quotes=["关键词匹配看字词重合。"]),
                               **({"passed": True} if issubclass(schema, MasteryEvaluation) else {}))
                with self.assertRaises(ModelCallError) as caught:
                    value.validate_request(dict(reference=REFERENCE))
                self.assertEqual(json.loads(caught.exception.diagnostic)[0]["field"], ["capture_feedback_quotes"])

    def test_blank_or_excessive_excerpts_fail_schema_validation(self):
        for schema in (MasteryEvaluation, JudgmentFeedback, ScoredMasteryEvaluation):
            for field in ("capture_quotes", "capture_feedback_quotes"):
                for quotes in (["  "], ["关键词匹配看字词重合。"] * 7):
                    with self.subTest(schema=schema.__name__, field=field, quotes=quotes), self.assertRaises(ValidationError):
                        schema(**feedback_values(**{field: quotes}),
                               **({"passed": True} if issubclass(schema, MasteryEvaluation) else {}))

    def test_valid_capture_excerpts_do_not_bypass_existing_followup_binding_check(self):
        value = self.evaluation(capture_quotes=["关键词匹配看字词重合。"], followup_question="解释这个知识点")
        value.passed = False
        with self.assertRaises(ModelCallError) as caught:
            value.validate_request(dict(reference=REFERENCE, check_binding={"step_id": "step"},
                                        retry_step=dict(title="语义检索")))
        self.assertEqual(json.loads(caught.exception.diagnostic)[0]["field"], ["followup_binding"])
        self.assertFalse(value.passed)


class RubricFallbackScopeTests(unittest.TestCase):
    def task(self):
        task = dict(task_id="task", content="理解语义检索", context=dict(
            last_lesson=REFERENCE, reference_answer="参考答案：语义匹配比较含义。",
            requires_mastery=True, check_question="语义匹配比较什么？"))
        set_plan(task, ["语义检索"], step_conditions=["解释语义匹配"])
        bind_standard(task, task["context"]["check_question"], ScoringSpec(
            learning_goal="解释语义匹配", must_cover=["比较含义"], evidence="模型概括，不作来源定位"))
        return task

    def test_rubric_fallback_is_marked_without_mutating_the_original_task(self):
        task = self.task()
        before = copy.deepcopy(task)
        binding = bound_check(task)
        self.assertEqual(binding["scope_source"], "rubric_fallback")
        self.assertEqual(binding["concepts"], ["比较含义"])
        self.assertEqual(binding["evidence_quotes"], [check_reference(task)])
        self.assertEqual(task, before)

    def test_explicit_check_binding_does_not_gain_a_rubric_fallback_marker(self):
        task = self.task()
        bind_check(task, task["context"]["check_question"], dict(step_title="语义检索", concepts=["比较含义"],
                                                               evidence_quotes=["**语义匹配**看意思是否接近。"]), ["比较含义"])
        self.assertNotIn("scope_source", bound_check(task))

    def test_stale_rubric_cannot_manufacture_a_fallback_binding(self):
        task = self.task()
        task["context"]["last_lesson"] = "新的讲解"
        self.assertIsNone(bound_check(task))

    def harness(self, task, feedback, *, passed=True):
        calls, dispositions, state = [], [], dict(runs={"run": {}})

        @contextmanager
        def transaction(*args):
            yield state

        def judge(h, sid, rid, rev, request):
            labels = {key: ("covered" if passed else "missing") if key.startswith("point_") else "absent"
                      for key in request.questions}
            return SimpleNamespace(status="ok", labels=labels)

        def call(sid, rid, rev, node, system, prompt, schema):
            payload = json.loads(prompt)
            calls.append(dict(node=node, system=system, payload=payload, schema=schema))
            value = schema.model_validate(feedback)
            value.validate_request(payload)
            return value

        h = SimpleNamespace(store=SimpleNamespace(transaction=transaction), _call=call,
                            _snapshot=lambda sid, rid, rev: (state, state['runs'][rid]),
                            judgments=SimpleNamespace(judge=judge, disposition=lambda *a, **kw: dispositions.append(kw)))
        return h, calls, dispositions, state

    def test_jev_uses_combined_actual_reference_and_keeps_one_feedback_call(self):
        task = self.task()
        feedback = feedback_values(capture_quotes=["参考答案：语义匹配比较含义。", "**语义匹配**看意思是否接近。"],
                                   capture_feedback_quotes=["语义接近不代表一定命中。"])
        h, calls, dispositions, state = self.harness(task, feedback)
        output = evaluate(h, "session", "run", 1, task, "比较意思是否相近。", "原判题规则")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["schema"], JudgmentFeedback)
        self.assertEqual(calls[0]["payload"]["reference"], check_reference(task))
        self.assertEqual(calls[0]["payload"]["checked_concepts"], ["比较含义"])
        self.assertIn(CAPTURE_QUOTE_RULE, calls[0]["system"])
        self.assertTrue(output.passed)
        self.assertEqual(output.capture_quotes, feedback["capture_quotes"])
        self.assertEqual(output.capture_feedback_quotes, feedback["capture_feedback_quotes"])
        self.assertTrue(state["runs"]["run"]["point_evaluation"]["passed"])
        self.assertEqual(len(dispositions), 1)

    def test_valid_jev_capture_excerpts_do_not_turn_a_failed_answer_into_a_pass(self):
        task = self.task()
        h, calls, _, _ = self.harness(task, feedback_values(capture_quotes=["参考答案：语义匹配比较含义。"]), passed=False)
        output = evaluate(h, "session", "run", 1, task, "仅匹配字词。", "原判题规则")
        self.assertFalse(output.passed)
        self.assertEqual(len(calls), 1)

    def test_jev_rejects_nonexistent_excerpts_before_returning_feedback(self):
        task = self.task()
        h, calls, _, state = self.harness(task, feedback_values(capture_quotes=["未在本次参考材料中出现的知识。"] ))
        with self.assertRaises(ModelCallError):
            evaluate(h, "session", "run", 1, task, "比较含义。", "原判题规则")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("point_evaluation", state["runs"]["run"])


if __name__ == "__main__":
    unittest.main()
