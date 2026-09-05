"""Recovery data is state, never an instruction to resume generation."""
import copy
import unittest
import uuid

from agent_service.checkpoint_delta import apply_changes, changes, recovery_projection
from agent_service.learning_progress import set_plan, record_understanding


class CheckpointDeltaTests(unittest.TestCase):
    def test_first_plan_ignores_model_invented_ids_without_inheriting_evidence(self):
        from agent_service.learning_progress import set_plan
        task = {"task_id": "task", "content": "RAG", "context": {}}
        plan = set_plan(task, ["检索", "生成"], "解释原理", ["step-1", "step-2"])
        self.assertNotEqual([s["id"] for s in plan["steps"]], ["step-1", "step-2"])
        self.assertTrue(all(s["understanding"] == "unknown" for s in plan["steps"]))
    def test_nested_delta_appends_unicode_and_preserves_unrelated_state(self):
        before = {"runs": {"r": {"text": "中文", "steps": {"done": 1}}}, "messages": [1], "pending": {"version": 1}}
        after = copy.deepcopy(before)
        after["runs"]["r"]["text"] += "😀 **未闭合"
        after["messages"].append(2)
        after["pending"] = None
        delta = changes(before, after)
        self.assertEqual(apply_changes(before, delta), after)
        self.assertNotIn("steps", str(delta))
        self.assertEqual(before["messages"], [1])

    def test_projection_has_cursor_but_no_recursive_journal(self):
        data = {"session_id": "s", "events": [{"seq": 7}], "event_base_seq": 6,
                "last_acked_seq": 5, "recovery_version": 2, "recovery_journal": ["large"],
                "recovery_state": {"old": True}, "pending": {"version": 3}}
        result = recovery_projection(data)
        self.assertEqual(result["event_base_seq"], 7)
        self.assertEqual(result["events"], [])
        self.assertNotIn("recovery_journal", result)
        self.assertEqual(result["pending"]["version"], 3)

    def test_invalid_patch_does_not_partially_modify_original(self):
        state = {"one": 1}
        with self.assertRaises(ValueError):
            apply_changes(state, [{"op": "set", "path": ["one"], "value": 2},
                                  {"op": "append", "path": ["missing"], "value": "no"}])
        self.assertEqual(state, {"one": 1})

    def test_explicit_step_id_keeps_evidence_across_rename_and_reorder(self):
        task = {"task_id": str(uuid.uuid4()), "content": "RAG", "context": {}}
        old = set_plan(task, ["检索", "生成"])
        first, second = old["steps"]
        record_understanding(task, "verified")
        first["message_ids"].append("answer-1")
        new = set_plan(task, ["生成", "检索原理", "权限"], step_ids=[second["id"], first["id"], ""])
        self.assertEqual(new["current_step_id"], first["id"])
        self.assertEqual(new["steps"][1]["understanding"], "verified")
        self.assertEqual(new["steps"][1]["message_ids"], ["answer-1"])
        self.assertEqual(new["version"], 2)
        self.assertEqual(new["steps"][2]["understanding"], "unknown")

    def test_foreign_or_duplicate_step_ids_cannot_reassign_evidence(self):
        task = {"task_id": str(uuid.uuid4()), "content": "RAG", "context": {}}
        old = set_plan(task, ["检索"])
        with self.assertRaises(ValueError):
            set_plan(task, ["陌生内容"], step_ids=[str(uuid.uuid4())])
        with self.assertRaises(ValueError):
            set_plan(task, ["检索", "生成"], step_ids=[old["steps"][0]["id"]] * 2)
        self.assertEqual(task["context"]["learning_plan"], old)
