"""Check experimental controls, composition boundaries and evidence integrity."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import httpx

from tests.judgment_comparison.adapters import Adapter
from tests.judgment_comparison.calibration import (
    Scenario, analyze, compose, focus_state, gate_reasons, inspect_result,
    load_scenarios, markdown, plan, trial, validate_scenarios,
)
from tests.judgment_comparison.cases import ROOT, load_suite
from tests.judgment_comparison.reporting import summarize, validate_report
from tests.run_judgment_comparison import run
from tests.test_judgment_comparison import response_for


class CalibrationControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = load_scenarios()

    def get(self, identity):
        return next(s for s in self.scenarios if s.base.id == identity)

    def test_three_variants_preserve_the_original_baseline_and_rotate_order(self):
        originals = {c.id: c for c in load_suite() if c.kind == 'dialogue'}
        cases, metadata = plan(self.scenarios)
        self.assertEqual(len(cases), 165)
        self.assertEqual(sum(len(c.questions) for c in cases), 1430)
        self.assertEqual([c.id.rsplit('/', 1)[1] for c in cases[:9]],
                         ['v0', 'v1', 'v2', 'v1', 'v2', 'v0', 'v2', 'v0', 'v1'])
        for s in self.scenarios:
            with self.subTest(identity=s.base.id):
                if s.split == 'development':
                    self.assertEqual(trial(s, 'v0').payload(), originals[s.base.id].payload())
                self.assertEqual(trial(s, 'v0').questions, trial(s, 'v1').questions)
                self.assertEqual(trial(s, 'v1').state, trial(s, 'v2').state)
        self.assertEqual(metadata['variants'], ['v0', 'v1', 'v2'])

    def test_focused_input_keeps_verbatim_history_and_cannot_reveal_gold(self):
        for s in self.scenarios:
            focused = focus_state(s.base.state)
            history = s.base.state['initial']['history']
            rebuilt = [{k: v for k, v in e.items() if k != 'index'} for e in focused['earlier_exchanges']]
            if focused['recent_exchange']:
                rebuilt.append(focused['recent_exchange'])
            self.assertEqual(history, rebuilt)
            self.assertNotIn('other_goals', focused)
            self.assertEqual(focused['current_input'], s.base.state['current_input'])
            def check(value):
                if isinstance(value, dict):
                    self.assertFalse(any(k in {'expected', 'atoms', 'family', 'split'} for k in value))
                    for item in value.values():
                        check(item)
                elif isinstance(value, list):
                    for item in value:
                        check(item)
            check(trial(s, 'v2').payload())

    def test_unrelated_goals_and_changed_gold_cannot_change_model_input(self):
        s = self.get('A013-foreign-goal-transition')
        changed = copy.deepcopy(s)
        changed.base.state['initial']['other_goals'] = []
        self.assertEqual(trial(s, 'v1').payload(), trial(changed, 'v1').payload())
        changed = copy.deepcopy(s)
        changed.base.expected['knowledge_request'] = 'yes'
        changed.atoms['asks_knowledge'] = 'yes'
        for variant in ['v0', 'v1', 'v2']:
            self.assertEqual(trial(s, variant).payload(), trial(changed, variant).payload())

    def test_family_leakage_and_inconsistent_gold_are_rejected(self):
        scenarios = copy.deepcopy(self.scenarios)
        scenarios[-1].family = scenarios[0].family
        with self.assertRaisesRegex(ValueError, 'family leaked'):
            validate_scenarios(scenarios)
        changed = self.scenarios[0].model_dump()
        changed['atoms']['requests_defer'] = 'no'
        with self.assertRaises(ValueError):
            Scenario.model_validate(changed)

    def test_mixed_social_request_does_not_become_pure_social(self):
        s = self.get('V015-greeting-bayes')
        self.assertEqual(s.atoms['social_purpose'], 'social')
        projected = compose(s.atoms, s.base.state)
        self.assertEqual(projected['conversation_kind'], 'ordinary')
        self.assertEqual(projected['knowledge_request'], 'yes')

    def test_rest_and_companionship_can_coexist_without_starting_learning(self):
        s = self.get('V017-companion-and-rest')
        projected = compose(s.atoms, s.base.state)
        self.assertEqual(projected['progress'], 'defer')
        self.assertEqual(projected['conversation_kind'], 'companionship')
        self.assertEqual(gate_reasons(projected, s.atoms, focus_state(s.base.state)), [])

    def test_current_task_not_other_session_goal_decides_next_step(self):
        for identity, expected in [('A013-foreign-goal-transition', 'clarify_next'),
                                   ('A013-current-plan-next', 'next_current')]:
            s = self.get(identity)
            self.assertEqual(compose(s.atoms, s.base.state)['progress'], expected)

    def test_repair_and_bare_continue_use_separate_reference_evidence(self):
        s = self.get('A006-repair-question')
        self.assertEqual(s.atoms['asks_knowledge'], 'no')
        self.assertEqual(compose(s.atoms, s.base.state)['knowledge_request'], 'yes')
        s = self.get('V007-anaphoric-errand')
        result = compose(s.atoms, s.base.state)
        self.assertEqual(result['resource_boundary'], 'resource_delivery')
        self.assertEqual(result['progress'], 'none')
        s = self.get('V008-cancel-errand-explain')
        self.assertEqual(s.atoms['prior_resource_request'], 'resource_delivery')
        self.assertEqual(compose(s.atoms, s.base.state)['resource_boundary'], 'none')

    def test_gates_do_not_claim_to_correct_every_wrong_answer(self):
        s = self.get('A013-local-transition')
        wrong = dict(s.base.expected, conversation_kind='social')
        self.assertIn('social_substantive_conflict', gate_reasons(wrong, wrong, s.base.state))
        wrong = dict(s.base.expected, progress='next_current')
        self.assertIn('missing_current_task', gate_reasons(wrong, wrong, s.base.state))
        s = self.get('A015-capability')
        wrong = dict(s.base.expected, resource_boundary='resource_delivery')
        self.assertEqual(gate_reasons(wrong, wrong, s.base.state), [])
        self.assertNotEqual(wrong, s.base.expected)

    def test_uncertainty_and_missing_reference_always_require_review(self):
        s = self.get('V003-official-lookup')
        atoms = dict(s.atoms, continuation_reference='recent_request')
        result = compose(atoms, s.base.state)
        self.assertIn('missing_reference', gate_reasons(result, atoms, focus_state(s.base.state)))
        atoms = dict(s.atoms, resource_request='unsure')
        self.assertIn('uncertain_judgment', gate_reasons(compose(atoms, s.base.state), atoms, focus_state(s.base.state)))

    def test_failed_calls_have_no_projected_answer(self):
        s = self.scenarios[0]
        result = inspect_result(s, 'v2', {'status': 'error', 'answers': None})
        self.assertIsNone(result['projected'])
        self.assertIsNone(result['errors'])
        self.assertFalse(result['exact'])
        self.assertEqual(result['gate_reasons'], ['call_failed'])

    def test_offline_entry_does_not_load_providers_or_create_database(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'must-not-exist.sqlite3'
            env = {**os.environ, 'REVIEW_TODAY_LLM_PROVIDER': 'never-load', 'TYPESAFE_API_KEY': '',
                   'REVIEW_TODAY_HARNESS_DB': str(db)}
            command = [sys.executable, str(ROOT / 'agent-service/tests/run_jev_calibration.py')]
            result = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['trials'], 165)
            self.assertFalse(db.exists())


class CalibrationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'results.jsonl'
        all_scenarios = load_scenarios()
        self.scenarios = [all_scenarios[0], next(s for s in all_scenarios if s.split == 'validation')]
        self.cases, self.metadata = plan(self.scenarios)
        by_payload = {json.dumps(c.payload(), sort_keys=True): c for c in self.cases}
        def handler(request):
            body = json.loads(request.content)
            case = by_payload[json.dumps({k: body[k] for k in ('state', 'questions')}, sort_keys=True)]
            return httpx.Response(200, json=response_for(case))
        self.adapter = Adapter('jev', 'fake-calibration-key', {}, client=httpx.Client(transport=httpx.MockTransport(handler)))
        with contextlib.redirect_stdout(io.StringIO()):
            run(self.cases, {'jev': self.adapter}, {}, self.path, experiment=self.metadata)

    def tearDown(self):
        self.adapter.close()
        self.directory.cleanup()

    def read(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def write(self, values):
        self.path.write_text(''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values))

    def test_raw_and_composed_scores_have_distinct_denominators(self):
        result = analyze(self.path)
        self.assertTrue(result['all_calls_valid'])
        self.assertEqual(result['groups']['development/v0']['raw_scored'], 7)
        self.assertEqual(result['groups']['development/v2']['raw_scored'], 12)
        self.assertEqual(result['groups']['development/v2']['contract_scored'], 7)
        self.assertFalse(result['production_integrated'])
        self.assertFalse(result['calibrated_threshold'])
        self.assertIn('不是原始模型输出', markdown(self.path))

    def test_manifest_change_cannot_rewrite_the_experiment(self):
        values = self.read()
        values[0]['experiment']['scenarios'][0]['base']['state']['current_input'] = 'rewritten'
        self.write(values)
        validate_report(self.path)  # Generic raw evidence does not interpret this metadata.
        with self.assertRaisesRegex(ValueError, 'manifest/trial'):
            analyze(self.path)

    def test_missing_trial_is_reported_even_with_an_honest_final_summary(self):
        values = self.read()
        header, rows = values[0], values[1:-2]
        self.write([header, *rows, summarize(header, rows)])
        result = analyze(self.path)
        self.assertFalse(result['all_calls_valid'])
        missing = [d for d in result['details'] if d['status'] == 'missing']
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['gate_reasons'], ['missing_result'])

    def test_existing_evidence_cannot_be_overwritten(self):
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            run(self.cases, {'jev': self.adapter}, {}, self.path, experiment=self.metadata)
        self.assertEqual(before, self.path.read_bytes())


if __name__ == '__main__':
    unittest.main()
