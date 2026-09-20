"""The experimental field replacement preserves real intent and uncertainty."""
import copy
import contextlib
import io
import unittest
from unittest.mock import patch

from tests.judgment_comparison.boundaries import load_scenarios, trial
from tests.judgment_comparison.resource_replay import bind_interceptor, observed_boundaries, project
from tests.test_judgment_comparison import answers_for


class ResourceInterventionTests(unittest.TestCase):
    def setUp(self):
        self.scenarios = {s.base.id: s for s in load_scenarios()}
        self.original = dict(resource_boundary='none', resource_learning_request='',
            programming_boundary='none', intents=['question'], answer_only=True,
            target_task_id='actual-task', rationale='actual DeepSeek response')

    def cached(self, identity, **labels):
        case = trial(self.scenarios[identity], 'resource')
        return dict(id=case.id, status='ok', input=case.payload(),
                    answers=answers_for(case, dict(case.expected, **labels)))

    def test_only_one_field_changes_and_original_output_is_retained(self):
        before = copy.deepcopy(self.original)
        cached = self.cached('A015-links-after-promise')
        result = project(self.original, cached)
        self.assertTrue(result['applied'])
        self.assertEqual(result['before'], before)
        self.assertEqual(self.original, before)
        self.assertEqual({k for k in before if before[k] != result['after'][k]}, {'resource_boundary'})
        self.assertEqual(result['after']['resource_boundary'], 'resource_delivery')

    def test_jev_failures_and_uncertainty_keep_deepseek_decision(self):
        self.original['resource_boundary'] = 'resource_delivery'
        for cached in ({'status': 'error', 'id': 'failed'},
                       self.cached('A015-links-after-promise', resource_boundary='unsure')):
            result = project(self.original, cached)
            self.assertFalse(result['applied'])
            self.assertEqual(result['after'], self.original)
            self.assertTrue(result['fallback_reason'])

    def test_inconsistent_raw_judgments_use_the_preexisting_review_gate(self):
        cached = self.cached('A015-quoted-request', resource_boundary='resource_delivery')
        result = project(self.original, cached)
        self.assertFalse(result['applied'])
        self.assertIn('mixed_request_conflict', result['fallback_reason'])

    def test_mixed_label_cannot_invent_a_missing_independent_learning_excerpt(self):
        cached = self.cached('A015-mixed-knowledge')
        for excerpt in ('', 'a fabricated knowledge request', cached['input']['state']['current_input']):
            original = dict(self.original, resource_learning_request=excerpt)
            result = project(original, cached)
            self.assertFalse(result['applied'])
            self.assertEqual(result['after'], original)
            self.assertEqual(result['fallback_reason'], 'missing_independent_learning_excerpt')

    def test_valid_mixed_excerpt_is_preserved_without_rewriting(self):
        cached = self.cached('B015-download-and-explain')
        original = dict(self.original, resource_learning_request='解释相机曝光时间是什么')
        result = project(original, cached)
        self.assertTrue(result['applied'])
        self.assertEqual(result['after']['resource_learning_request'], original['resource_learning_request'])
        self.assertEqual(result['after']['resource_boundary'], 'mixed_learning')

    def test_experiment_does_not_use_gold_to_hide_a_wrong_but_unflagged_label(self):
        cached = self.cached('A005-coding-capability', resource_boundary='capability_question')
        result = project(self.original, cached)
        self.assertTrue(result['applied'])
        self.assertEqual(result['after']['resource_boundary'], 'capability_question')

    def test_late_baseline_response_cannot_pick_up_the_next_resource_intervention(self):
        from agent_service.schemas import IntentDecision
        decision = IntentDecision(intents=['question'], relation='new_topic', scope='conversation', rationale='original')
        old = dict(variant='deepseek', events=[], cached=self.cached('A015-links-after-promise'))
        new = dict(variant='resource', events=[], cached=self.cached('A005-coding-capability', resource_boundary='capability_question'))
        context = [old]
        def delayed_parse(*args, **kwargs):
            context[0] = new
            return decision
        result = bind_interceptor(delayed_parse, lambda: context[0])('', '', IntentDecision)
        self.assertEqual(result, decision)
        self.assertEqual(old['events'], [])
        self.assertEqual(new['events'], [])

    def test_late_resource_response_keeps_its_original_case_and_event_list(self):
        from agent_service.schemas import IntentDecision
        decision = IntentDecision(intents=['question'], relation='new_topic', scope='conversation', rationale='original')
        old = dict(variant='resource', events=[], cached=self.cached('A015-links-after-promise'))
        new = dict(variant='resource', events=[], cached=self.cached('A005-coding-capability', resource_boundary='capability_question'))
        context = [old]
        def delayed_parse(*args, **kwargs):
            context[0] = new
            return decision
        result = bind_interceptor(delayed_parse, lambda: context[0])('', '', IntentDecision)
        self.assertEqual(result.resource_boundary, 'resource_delivery')
        self.assertEqual(len(old['events']), 1)
        self.assertEqual(new['events'], [])

    def test_scope_audit_catches_coding_reply_misrouted_as_resource_refusal(self):
        expected = self.scenarios['A005-coding-capability'].base.expected
        wrong = dict(run=dict(status='completed', resource_scope_reply=True), automatic_result='PASS')
        actual = observed_boundaries(wrong, expected)
        self.assertTrue(actual['scored'])
        self.assertFalse(actual['passed'])
        self.assertEqual(actual['errors'], ['wrong_resource_reply', 'missing_programming_reply'])
        right = dict(run=dict(status='completed', programming_scope_reply=True))
        self.assertTrue(observed_boundaries(right, expected)['passed'])

    def test_scope_audit_does_not_call_execution_failure_a_correct_absence(self):
        expected = self.scenarios['A010-local-example'].base.expected
        result = observed_boundaries(dict(run={'status': 'retryable_failed'}), expected)
        self.assertFalse(result['scored'])
        self.assertFalse(result['passed'])

    def test_cli_rejects_a_scope_failure_even_if_legacy_assertions_pass(self):
        from tests.run_jev_resource_harness import main
        result = dict(result={'automatic_result': 'PASS'}, audited_result='FAIL')
        with patch('tests.run_jev_resource_harness.summarize_harness', return_value=result):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--report', '/unused/synthetic-report.jsonl']), 1)


if __name__ == '__main__':
    unittest.main()
