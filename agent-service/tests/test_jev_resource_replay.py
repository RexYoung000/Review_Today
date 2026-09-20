"""The experimental field replacement preserves real intent and uncertainty."""
import copy
import unittest

from tests.judgment_comparison.boundaries import load_scenarios, trial
from tests.judgment_comparison.resource_replay import project
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


if __name__ == '__main__':
    unittest.main()
