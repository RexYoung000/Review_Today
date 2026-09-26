import unittest
from unittest.mock import patch

from agent_service.context_budget import prepare
from agent_service.execution_policy import AttemptBudget, ApprovedAlternative, alternatives


class ExecutionPolicyTests(unittest.TestCase):
    def test_stream_progress_passes_old_deadline_but_never_total_deadline(self):
        budget = AttemptBudget(seconds=180, first_output_seconds=90, idle_seconds=30)
        start = budget.started
        for elapsed in [20, 45, 70, 95, 120, 145, 170]:
            with patch('agent_service.execution_policy.time.monotonic', return_value=start + elapsed):
                budget.output_progress()
                self.assertGreater(budget.remaining(), 0)
        with patch('agent_service.execution_policy.time.monotonic', return_value=start + 180):
            with self.assertRaisesRegex(RuntimeError, 'TIMEOUT'):
                budget.output_progress()

    def test_first_output_and_idle_deadlines_are_distinct(self):
        budget = AttemptBudget(seconds=180, first_output_seconds=90, idle_seconds=30)
        start = budget.started
        with patch('agent_service.execution_policy.time.monotonic', return_value=start + 91):
            with self.assertRaisesRegex(RuntimeError, 'TIMEOUT'):
                budget.remaining()
        with patch('agent_service.execution_policy.time.monotonic', return_value=start + 10):
            budget.output_progress()
        with patch('agent_service.execution_policy.time.monotonic', return_value=start + 41):
            with self.assertRaisesRegex(RuntimeError, 'TIMEOUT'):
                budget.output_progress()

    def test_watchdog_closes_stalled_stream_after_progress(self):
        import threading
        from agent_service.execution_policy import budget_scope
        closed = threading.Event()
        with budget_scope(seconds=1, first_output_seconds=.8, idle_seconds=.03) as budget:
            budget.register(closed.set)
            budget.output_progress()
            self.assertTrue(closed.wait(.4))
            self.assertTrue(budget.expired)

    def test_budget_shared_and_finite(self):
        budget = AttemptBudget(limit=2, seconds=10)
        budget.take(); budget.take()
        with self.assertRaisesRegex(RuntimeError, "ATTEMPTS_EXHAUSTED"):
            budget.take()
        with patch("agent_service.execution_policy.time.monotonic", return_value=budget.started + 11):
            with self.assertRaisesRegex(RuntimeError, "TIMEOUT"):
                budget.remaining()

    def test_unverified_or_weaker_backup_is_never_selected(self):
        choices = (ApprovedAlternative("weak", frozenset({"smart"}), True, True, True, True),
                   ApprovedAlternative("unverified", frozenset({"deep"}), True, True, True, False),
                   ApprovedAlternative("allowed", frozenset({"deep"}), True, True, True, True))
        with patch("agent_service.execution_policy.APPROVED_ALTERNATIVES", {"primary": choices}):
            self.assertEqual(alternatives("primary", "deep", True), ["allowed"])
        self.assertEqual(alternatives("unknown", "smart", False), [])

    def test_nested_budget_reuses_deadline_and_closes_transports(self):
        import threading
        from agent_service.execution_policy import budget_scope, current_budget
        closed = threading.Event()
        with budget_scope(seconds=0.02) as outer:
            with budget_scope(seconds=10) as inner:
                self.assertIs(inner, outer)
                self.assertIs(current_budget.get(), outer)
                outer.register(closed.set)
                self.assertTrue(closed.wait(0.5))
                with self.assertRaisesRegex(RuntimeError, "TIMEOUT"):
                    outer.remaining()

    def test_context_removes_narrative_not_current_constraints_or_consent(self):
        import json
        protected = {"current_inputs": ["不要保存"], "pending": {"id": "p", "version": 3}, "task": {"state": "waiting"}}
        prompt, info = prepare("规则", json.dumps({"context": dict(protected, related_knowledge=["长检索" * 1000])}), local_limit=300)
        context = json.loads(prompt)["context"]
        for key, value in protected.items(): self.assertEqual(context[key], value)
        self.assertTrue(info["estimated"])
        self.assertLessEqual(info["ratio"], 1)
        self.assertIsNone(info["model_window"])
        self.assertIn("related_knowledge", info["omitted_narrative"])

    def test_oversize_current_input_fails_without_silent_truncation(self):
        import json
        with self.assertRaisesRegex(ValueError, "INPUT_TOO_LARGE"):
            prepare("rules", json.dumps({"current_inputs": ["约束" * 1000]}, ensure_ascii=False), local_limit=50)
        _, info = prepare("r", "u", window=5000, reserve=4096)
        self.assertEqual(info["input_budget"], 904)

    def test_window_is_scoped_to_provider_and_actual_model(self):
        from agent_service.context_budget import configured_window
        with patch.dict("os.environ", {"OPENAI_CONTEXT_WINDOW": "128000"}, clear=True):
            with patch("agent_service.config.PROVIDER", "deepseek"):
                self.assertEqual(configured_window("deepseek-v4-flash"), 1_000_000)
                self.assertEqual(configured_window("deepseek-v4-pro"), 1_000_000)
                self.assertEqual(configured_window("deepseek-flash"), 1_000_000)
                self.assertIsNone(configured_window("unknown"))
                _, info = prepare("rules", "prompt", window=configured_window("deepseek-v4-flash"))
                self.assertEqual(info["input_budget"], 256000)
                self.assertEqual(info["output_reserve"], 4096)
            with patch("agent_service.config.PROVIDER", "openai_compatible"):
                self.assertEqual(configured_window("any"), 128000)
        with patch.dict("os.environ", {"DEEPSEEK_CONTEXT_WINDOW": "64000"}, clear=True), patch("agent_service.config.PROVIDER", "deepseek"):
            self.assertEqual(configured_window("deepseek-v4-flash"), 64000)
        with patch.dict("os.environ", {}, clear=True), patch("agent_service.config.PROVIDER", "openai_compatible"):
            self.assertIsNone(configured_window("deepseek-v4-flash"))
