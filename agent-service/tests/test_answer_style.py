import unittest
from types import SimpleNamespace as NS
from agent_service.answer_style import with_question, render_jd, render_sources
from agent_service.harness import _render_problem
from agent_service.response_projection import public_preview


class AnswerStyleTests(unittest.TestCase):
    def test_question_appears_once_and_stays_in_history(self):
        text = with_question("解释内容。", "为什么需要检索？")
        self.assertEqual(text.count("为什么需要检索？"), 1)
        self.assertIn("---\n\n### 想一想", text)
        self.assertEqual(with_question(text, "为什么需要检索？"), text)
        echoed = "解释。\n\n**为什么需要检索？**"
        self.assertEqual(with_question(echoed, "为什么需要检索？"), echoed)
        self.assertEqual(with_question("简短回答。", ""), "简短回答。")

    def test_problem_keeps_assumptions_close_and_plan_out_of_v2_body(self):
        bundle = NS(answer=NS(direct_answer="核心回答", assumptions=["关键前提"], spoken_answer="口头表达"),
                    gap_map=NS(related_knowledge=["相关概念"], likely_gaps=["补充概念"], learning_order=["第一步"]),
                    analysis=NS(calibration_question="当前问题？"))
        result = with_question(_render_problem(bundle, compact=True), bundle.analysis.calibration_question)
        self.assertLess(result.index("关键前提"), result.index("口头表达"))
        self.assertNotIn("第一步", result)
        self.assertEqual(result.count("当前问题？"), 1)
        self.assertIn("第一步", _render_problem(bundle))  # Legacy caller keeps its own plan.

    def test_preview_and_final_jd_share_structure(self):
        value = dict(role_goal="岗位目标", competency_map=["能力A"], risk_points=["风险B"],
                     prioritized_questions=["问题C"])
        self.assertEqual(public_preview("jd_analysis", value), render_jd(value))
        self.assertIn("## 优先问题\n\n1. 问题C", render_jd(value))
        self.assertIn("## 优先问题\n\n1. 问题C", render_jd({**value, 'prioritized_questions': ['1. 问题C']}))
        self.assertNotIn("None", render_jd(dict(role_goal=None, competency_map=[None])))
        self.assertEqual(public_preview("problem_answer", {"answer": {"direct_answer": "直接答案"}}), "直接答案")

    def test_private_fields_never_enter_public_projection(self):
        self.assertEqual(public_preview("lesson", {"message": "知识正文", "check_question": "稍后发布",
                                                  "evidence_state": "verified"}), "知识正文")
        self.assertEqual(public_preview("intent", {"rationale": "private"}), "")

    def test_source_labels_are_readable_and_urls_preserved(self):
        url = "https://example.org/docs/guide.md"
        text = render_sources([{"url": url, "title": url}, {"url": "https://example.org", "title": "标题[补充]"}])
        self.assertIn("- [example.org · guide.md](" + url + ")", text)
        self.assertIn("标题\\[补充\\]", text)


if __name__ == "__main__":
    unittest.main()
