"""Offline replay of decision 268; no provider, web or daily store is used."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_service.answer_style import teaching_passages
from agent_service.learning_progress import bind_check, bound_check, current_step, set_plan
from agent_service.openai_client import ModelCallError
from agent_service.response_projection import public_preview
from agent_service.schemas import TeachingConversationOutput
from tests import test_conversation_v2 as fixture


FAILURE = Path(__file__).parent / "fixtures" / "teaching_scope_268.json"


def retained_failure():
    return json.loads(FAILURE.read_text())


def repaired_candidate():
    """Controlled correction of the retained case, not a new real model result."""
    original = retained_failure()["output"]
    question = original["check_question"]
    source = "来源资料本身可能错误或过时；"
    generation = "生成回答可能没有忠实依据资料；"
    start = question.index(source)
    end = start + len(source)
    parts = [question[:end], generation, question[end + len(generation):]]
    quotes = [
        "相似度比较的是问题与资料的相关程度，并不验证事实是否正确。",
        "来源可能本身写错，也可能属于旧版本；检索得再相似，仍会把错误或过时的信息交给模型。",
        "即使资料正确，生成回答也可能误读、补造或偏离资料，因而没有忠实依据资料。",
        "因此要核对来源是否可信、是否仍然有效，再核对时间、地区、版本等适用条件，并检查回答中的结论能否由资料支持；相关的资料未必适用于当前问题。",
    ]
    concepts = ["相似与正确的区别", "来源错误或过时", "生成忠实性", "核对来源与适用条件"]
    title = "高相似度为何不能保证 RAG 答案正确"
    return dict(message="RAG（检索增强生成）先检索资料，再结合资料生成回答。\n\n## 当前讲解\n\n" + "\n\n".join(quotes),
        check_question=question, evidence_state="unverified", learning_concepts=concepts,
        learning_plan=dict(goal=title, steps=[title], success_check="能复述两类失效及核对来源和适用条件的原因",
            step_conditions=["能说明相似度不验证正确性、来源和生成的失效，以及核对依据的原因"]),
        check_binding=dict(step_title=title, concepts=concepts, evidence_quotes=quotes, scope="concept"),
        question_coverage=[
            dict(question_quote=parts[0], taught=True, concepts=concepts[:2], evidence_quote_indices=[0, 1]),
            dict(question_quote=parts[1], taught=True, concepts=[concepts[2]], evidence_quote_indices=[2]),
            dict(question_quote=parts[2], taught=True, concepts=[concepts[3]], evidence_quote_indices=[3])])


def validate(value, payload=None):
    output = TeachingConversationOutput.model_validate(copy.deepcopy(value))
    output.validate_request(payload or retained_failure()["payload"])
    return output


class TeachingScopeCoverageTests(unittest.TestCase):
    def assert_rejected(self, value, diagnostic):
        with self.assertRaises(ModelCallError) as caught:
            validate(value)
        self.assertEqual(caught.exception.code, "RT.MODEL.SCHEMA")
        self.assertIn(diagnostic, caught.exception.diagnostic)

    def test_original_retained_output_is_unchanged_and_rejected(self):
        case = retained_failure()
        digest = hashlib.sha256(json.dumps(case["output"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        self.assertEqual(digest, case["provenance"]["source_model_output_sha256"])
        self.assert_rejected(case["output"], "teaching_check_coverage_missing")

    def test_partial_or_reordered_question_declaration_cannot_hide_requirements(self):
        for change in (lambda rows: rows.pop(), lambda rows: rows.reverse(),
                       lambda rows: rows[0].update(question_quote=rows[0]["question_quote"].replace("；", " "))):
            value = repaired_candidate()
            change(value["question_coverage"])
            with self.subTest(value=value["question_coverage"]):
                self.assert_rejected(value, "teaching_check_coverage_question")

    def test_uncovered_requirement_false_or_without_evidence_is_rejected(self):
        for fields, kind in ((dict(taught=False, evidence_quote_indices=[]), "untaught"),
                             (dict(evidence_quote_indices=[]), "evidence"),
                             (dict(evidence_quote_indices=[4]), "evidence"),
                             (dict(evidence_quote_indices=[-1]), "evidence")):
            value = repaired_candidate()
            value["question_coverage"][1].update(fields)
            self.assert_rejected(value, "teaching_check_coverage_" + kind)

    def test_question_and_frozen_binding_must_have_the_same_concept_scope(self):
        value = repaired_candidate()
        value["question_coverage"][1]["concepts"] = ["未经绑定的新要求"]
        self.assert_rejected(value, "teaching_check_coverage_binding")
        value = repaired_candidate()
        value["question_coverage"][1]["concepts"] = [value["learning_concepts"][0]]
        self.assert_rejected(value, "teaching_check_coverage_binding")

    def test_literal_map_labels_cannot_be_used_as_taught_evidence(self):
        value = repaired_candidate()
        quote = "生成没有忠实依据资料"
        value["message"] = "## 学习地图\n\n- 后续：" + quote + "\n\n### 当前第一步：相似度\n\n只讲相似度。"
        value["check_binding"]["evidence_quotes"] = [quote] * 4
        self.assert_rejected(value, "teaching_check_coverage_evidence")

    def test_same_retrieved_failure_with_honest_missing_items_is_rejected(self):
        value = copy.deepcopy(retained_failure()["output"])
        value["question_coverage"] = copy.deepcopy(repaired_candidate()["question_coverage"])
        value["question_coverage"][0].update(concepts=value["check_binding"]["concepts"], evidence_quote_indices=[0, 1, 2])
        for row in value["question_coverage"][1:]:
            row.update(taught=False, concepts=[], evidence_quote_indices=[])
        self.assert_rejected(value, "teaching_check_coverage_untaught")

    def test_full_correction_keeps_all_original_question_requirements(self):
        output = validate(repaired_candidate())
        self.assertEqual(output.check_question, retained_failure()["output"]["check_question"])
        self.assertEqual(len(output.learning_plan.steps), 1)
        self.assertEqual("".join(r.question_quote for r in output.question_coverage), output.check_question)

    def test_unrelated_narrow_http_check_does_not_require_rag_vocabulary_or_whole_step_scope(self):
        quote = "幂等表示同一请求执行多次与执行一次的预期效果相同，不保证每次响应内容相同。"
        output = validate(dict(message=quote, check_question="幂等为什么不保证每次响应相同？",
            learning_concepts=["幂等的效果边界"],
            check_binding=dict(step_title="当前资料讲解", concepts=["幂等的效果边界"], evidence_quotes=[quote]),
            question_coverage=[dict(question_quote="幂等为什么不保证每次响应相同？", taught=True,
                concepts=["幂等的效果边界"], evidence_quote_indices=[0])]))
        self.assertEqual(output.check_binding.scope, "concept")

    def test_map_filter_preserves_code_examples_and_resumes_at_current_lesson(self):
        for heading in ("## 学习地图", "## Learning map", "## 学习计划"):
            text = "定义。\n\n" + heading + "\n\n### 后续生成\n未来标签。\n\n### 当前第一步：相似度\n已讲。"
            eligible = "".join(teaching_passages(text))
            self.assertNotIn("未来标签", eligible)
            self.assertIn("定义。", eligible)
            self.assertIn("已讲。", eligible)
        example = "示例：\n```markdown\n## 学习地图\n这只是示例代码。\n```\n正文。"
        self.assertEqual("".join(teaching_passages(example)), example)

    def test_preview_hides_explicit_check_sections_and_private_coverage(self):
        for heading in ("## 检查题", "### 想一想", "## 检查一下", "## Quick check"):
            self.assertEqual(public_preview("lesson", dict(message="正文。\n\n" + heading + "\n不能预先发布的问题？",
                check_question="独立题目", question_coverage=[dict(private="internal")])), "正文。")
        example = "示例：\n```markdown\n## 检查题\n这是示例。\n```"
        self.assertEqual(public_preview("lesson", dict(message=example)), example)

    def test_coverage_is_frozen_and_invalid_declaration_cannot_be_bound(self):
        output = validate(repaired_candidate())
        task = dict(task_id="test", content="RAG", context=dict(last_lesson=output.message, check_question=output.check_question))
        set_plan(task, output.learning_plan.steps, step_conditions=output.learning_plan.step_conditions)
        binding = bind_check(task, output.check_question, output.check_binding, output.learning_concepts,
            question_coverage=output.question_coverage)
        self.assertEqual(binding["question_coverage"], [row.model_dump() for row in output.question_coverage])
        self.assertEqual(binding["step_id"], current_step(task)["id"])
        self.assertEqual(current_step(task)["understanding"], "unknown")
        output.question_coverage[0].concepts.clear()
        self.assertTrue(bound_check(task)["question_coverage"][0]["concepts"])
        self.assertIsNone(bind_check(task, output.check_question, output.check_binding, output.learning_concepts,
            question_coverage=output.question_coverage))


class TeachingScopeFlowTests(unittest.TestCase):
    setUp = fixture.ConversationTests.setUp
    tearDown = fixture.ConversationTests.tearDown
    send = fixture.ConversationTests.send
    state = fixture.ConversationTests.state
    model = fixture.ConversationTests.model

    def replay(self, *, repair=True):
        attempts = []
        def model(system, user, schema, **kwargs):
            if schema is TeachingConversationOutput:
                attempts.append(system)
                value = retained_failure()["output"] if len(attempts) == 1 or not repair else repaired_candidate()
                # A model may echo its draft question in prose. It must not leak
                # through response.delta while the coverage gate rejects it.
                preview = copy.deepcopy(value)
                preview["message"] += "\n\n## 检查题\n\n" + preview["check_question"]
                kwargs.get("on_partial", lambda value: None)(preview)
                return TeachingConversationOutput.model_validate(value)
            return self.model(system, user, schema, **kwargs)
        self.decision = fixture.intent("goal", workflow="source_learning", direct_teaching=True)
        with patch("socket.socket.connect", side_effect=AssertionError("offline replay forbids network")), \
                patch("agent_service.conversation.parse_model", side_effect=model):
            accepted = self.send("按原记录学习高相似度的局限", mode="source_learning")
        return accepted, attempts

    def test_real_failure_uses_exactly_one_repair_then_publishes_consistent_check(self):
        accepted, attempts = self.replay()
        state = self.state()
        self.assertEqual(len(attempts), 2)
        self.assertIn("question_coverage", attempts[-1])
        self.assertIn("不能删减其要求绕过校验", attempts[-1])
        task = state["tasks"][state["active_task_id"]]
        binding = task["context"]["check_binding"]
        self.assertEqual(state["runs"][accepted.run_id]["status"], "completed")
        self.assertEqual(binding["question"], task["required_action"]["prompt"])
        self.assertEqual(binding["question_coverage"], repaired_candidate()["question_coverage"])
        self.assertEqual(task["context"]["understanding"], "unknown")
        self.assertEqual(current_step(task)["understanding"], "unknown")
        question = retained_failure()["output"]["check_question"]
        self.assertEqual([m["content"].count(question) for m in state["messages"] if m["role"] == "coach"], [1])
        previews = [e["payload"]["response"] for e in state["events"] if e["stage"] == "response.delta"]
        self.assertTrue(previews, "lesson body must still stream")
        self.assertTrue(all(question not in r["text"] for r in previews))
        self.capture.assert_not_called()

    def test_exhausted_repair_does_not_publish_bind_or_mark_mastery(self):
        accepted, attempts = self.replay(repair=False)
        state = self.state()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(state["runs"][accepted.run_id]["status"], "retryable_failed")
        task = state["tasks"][state["active_task_id"]]
        self.assertFalse(task["context"].get("check_binding"))
        self.assertFalse(task["context"].get("check_question"))
        self.assertNotEqual((task.get("required_action") or {}).get("type"), "submit_answer")
        self.assertFalse(any(m["role"] == "coach" for m in state["messages"]))
        self.assertEqual(state["messages"][0]["role"], "user")
        self.capture.assert_not_called()

    def test_failed_next_lesson_preserves_prior_binding_history_and_progress(self):
        self.decision = fixture.intent("goal", workflow="source_learning", direct_teaching=True)
        self.send("先教当前原理", mode="source_learning")
        before = self.state()
        tid = before["active_task_id"]
        prior = copy.deepcopy(before["tasks"][tid]["context"])
        accepted, _ = self.replay(repair=False)
        after = self.state()
        self.assertEqual(after["runs"][accepted.run_id]["status"], "retryable_failed")
        for key in ("check_question", "check_binding", "learning_plan", "last_lesson", "lesson_index", "understanding"):
            self.assertEqual(after["tasks"][tid]["context"].get(key), prior.get(key), key)
        self.assertEqual(after["messages"][:len(before["messages"])], before["messages"])


if __name__ == "__main__":
    unittest.main()
