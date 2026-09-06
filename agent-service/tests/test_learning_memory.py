import unittest
from agent_service.learning_memory import make_evidence, select_references


class LearningMemoryTests(unittest.TestCase):
    def test_greeting_and_failed_output_are_not_learning_evidence(self):
        self.assertIsNone(make_evidence({"status": "completed", "intent": {"intents": ["greeting"]}}, None, "m", "hi", "s"))
        self.assertIsNone(make_evidence({"status": "retryable_failed", "activity_candidate": "knowledge_answer"}, None, "m", "partial", "s"))

    def test_explained_does_not_claim_verified_and_hint_blocks_independent_evidence(self):
        run = {"run_id": "r", "revision": 1, "status": "completed", "activity_candidate": "lesson_step", "intent": {"intents": ["hint"]}, "input_ids": ["u"]}
        task = {"task_id": "t", "content": "检索", "context": {"understanding": "verified", "hint_used": True}}
        record = make_evidence(run, task, "m", "讲解", "s")
        self.assertEqual(record["kind"], "explained")
        self.assertTrue(record["hint_used"])

    def test_only_supplied_ids_and_two_useful_relations_are_selected(self):
        candidates = [{"id": "a", "concept": "索引", "excerpt": "先建立索引", "kind": "explained"}]
        selected = select_references(candidates, [{"id": "a", "relation": "prerequisite"}, {"id": "fake", "relation": "analogy"}, {"id": "a", "relation": "contrast"}])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["relation"], "prerequisite")
        self.assertEqual(selected[0]["kind"], "explained")

    def test_evaluation_evidence_points_to_answered_not_next_step(self):
        run = dict(run_id="r", status="completed", evaluated_step_id="first", intent={"intents": ["answer"]})
        task = dict(task_id="t", context={"learning_plan": {"current_step_id": "next", "steps": [
            {"id": "first", "title": "刚才的作答"}, {"id": "next", "title": "待做的追问"}]},
            "practice": [{"hint_used": False, "evaluation": {"passed": True}}]})
        result = make_evidence(run, task, "m", "评价", "s")
        self.assertEqual(result["step_id"], "first")
        self.assertEqual(result["kind"], "independently_verified")
