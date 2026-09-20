"""Controls, freeze discipline, failure semantics, and honest impact reporting."""
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
from tests.judgment_comparison.boundaries import (
    BASE_VARIANTS, FACTORS, Scenario, analyze, eligible, factors, load_scenarios, plan,
    questions, risks, trial, validate_scenarios,
    selection, verify_selection,
)
from tests.judgment_comparison.calibration import load_scenarios as old_scenarios, trial as old_trial
from tests.judgment_comparison.cases import ROOT
from tests.judgment_comparison.reporting import summarize, validate_report
from tests.run_judgment_comparison import run
from tests.test_judgment_comparison import response_for


class BoundaryControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = load_scenarios()

    def test_seen_validation_is_now_regression_and_original_gold_is_unchanged(self):
        original = {s.base.id: s for s in old_scenarios()}
        for s in self.scenarios[:55]:
            with self.subTest(case=s.base.id):
                self.assertEqual(s.split, 'regression')
                self.assertEqual(s.base, original[s.base.id].base)
                for v in ('v0', 'v1'):
                    self.assertEqual(trial(s, v).payload(), old_trial(original[s.base.id], v).payload())
        self.assertEqual(len(self.scenarios[55:]), 48)
        self.assertEqual(len({s.family for s in self.scenarios[55:]}), 12)

    def test_each_single_factor_has_the_promised_scope_and_seven_raw_answers(self):
        s = self.scenarios[0]
        original = s.base.questions
        for v, changed in [('scope', set(original)), ('resource', {'resource_boundary'}),
                           ('progress', {'knowledge_request', 'progress'})]:
            result = trial(s, v)
            self.assertEqual(set(result.questions), set(original))
            self.assertEqual(result.expected, s.base.expected)
            self.assertEqual(result.state, trial(s, 'v1').state)
            self.assertEqual({k for k in original if result.questions[k] != original[k]}, changed)

    def test_combination_is_exactly_composed_of_frozen_changes(self):
        original = self.scenarios[0].base.questions
        combined = questions(original, 'scope+resource+progress')
        scoped = questions(original, 'scope')
        singles = {v: questions(original, v) for v in FACTORS}
        for key in original:
            factor = 'resource' if key == 'resource_boundary' else 'progress' if key in {'progress', 'knowledge_request'} else None
            self.assertEqual(combined[key].criteria, singles[factor][key].criteria if factor else original[key].criteria)
            if not factor:
                self.assertEqual(combined[key], scoped[key])
        for bad in ('', 'v2', 'progress+scope', 'scope+scope', 'v1+resource'):
            with self.assertRaises(ValueError):
                factors(bad)

    def test_gold_family_and_other_goals_cannot_influence_focused_input(self):
        for s in self.scenarios:
            changed = copy.deepcopy(s)
            changed.base.expected['knowledge_request'] = 'no' if s.base.expected['knowledge_request'] == 'yes' else 'yes'
            changed.family = 'different-family'
            changed.base.state['initial']['other_goals'] = []
            for variant in BASE_VARIANTS[1:]:
                self.assertEqual(trial(s, variant).payload(), trial(changed, variant).payload())

    def test_quotes_json_code_and_history_are_preserved_verbatim(self):
        for s in self.scenarios[55:]:
            for variant in BASE_VARIANTS:
                t = trial(s, variant)
                self.assertEqual(t.state['current_input'], s.base.state['current_input'])
                if variant != 'v0':
                    history = [{k: v for k, v in h.items() if k != 'index'} for h in t.state['earlier_exchanges']]
                    if t.state['recent_exchange']:
                        history.append(t.state['recent_exchange'])
                    self.assertEqual(history, s.base.state['initial']['history'])

    def test_family_leakage_duplicate_cases_and_invalid_binding_rejected(self):
        s = copy.deepcopy(self.scenarios)
        s[-1].family = s[0].family
        with self.assertRaises(ValueError):
            validate_scenarios(s)
        with self.assertRaises(ValueError):
            validate_scenarios([s[0], s[0]])
        value = next(s.model_dump() for s in self.scenarios if s.base.state['initial']['current_task'])
        value['base']['state']['initial']['task_history_index'] = 999
        with self.assertRaises(ValueError):
            Scenario.model_validate(value)

    def test_variant_order_rotates_and_no_extra_judgments_are_hidden(self):
        cases, metadata = plan(self.scenarios[:55])
        self.assertEqual(len(cases), 275)
        self.assertEqual(sum(len(c.questions) for c in cases), 1925)
        self.assertEqual([c.id.rsplit('/', 1)[1] for c in cases[5:10]], ['v1', 'scope', 'resource', 'progress', 'v0'])
        self.assertEqual(metadata['variants'], list(BASE_VARIANTS))

    def test_label_only_plan_difference_is_not_an_observed_routing_fault(self):
        s = next(s for s in self.scenarios if s.base.id == 'B017-plan-second-step')
        predicted = dict(s.base.expected, knowledge_request='yes')
        self.assertNotEqual(predicted, s.base.expected)
        self.assertEqual(risks(s.base.expected, predicted), [])
        self.assertEqual(risks(s.base.expected, dict(predicted, progress='resume_prior')), ['wrong_learning_target'])

    def test_potential_risks_cover_quoted_controls_mixed_requests_and_private_material(self):
        by_id = {s.base.id: s for s in self.scenarios}
        gold = by_id['B001-transcript-pause'].base.expected
        self.assertIn('unrequested_defer', risks(gold, dict(gold, progress='defer')))
        gold = by_id['B015-download-and-explain'].base.expected
        self.assertIn('resource_boundary_mixed_lost', risks(gold, dict(gold, resource_boundary='resource_delivery')))
        gold = by_id['B010-signed-note'].base.expected
        self.assertIn('external_scope_lost', risks(gold, dict(gold, web_scope='public_lookup')))

    def test_new_risk_disqualifies_a_higher_accuracy_candidate(self):
        base = dict(exact=50, label_errors=5, risk_cases=4, errors_by_field={'resource_boundary': 5})
        improved = dict(exact=53, label_errors=2, risk_cases=2, errors_by_field={'resource_boundary': 2})
        result = dict(all_calls_valid=True, details=[dict(split='regression')],
            groups={'regression/v1': base, 'regression/resource': improved},
            paired={'regression/resource': {'new_risks': []}})
        self.assertEqual(eligible(result), ['resource'])
        result['paired']['regression/resource']['new_risks'] = [{'id': 'new', 'risk': 'resource_boundary_false_block'}]
        self.assertEqual(eligible(result), [])
        result['all_calls_valid'] = False
        with self.assertRaises(ValueError):
            eligible(result)

    def test_default_offline_entry_does_not_load_providers_or_create_database(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'must-not-exist.sqlite3'
            env = {**os.environ, 'REVIEW_TODAY_LLM_PROVIDER': 'never-load', 'TYPESAFE_API_KEY': '',
                   'REVIEW_TODAY_HARNESS_DB': str(db)}
            result = subprocess.run([sys.executable, str(ROOT / 'agent-service/tests/run_jev_boundaries.py')],
                env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['scenarios'], 103)
            self.assertFalse(db.exists())


class BoundaryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'results.jsonl'
        scenarios = load_scenarios()
        self.cases, self.metadata = plan([scenarios[0], scenarios[-1]])

    def tearDown(self):
        self.directory.cleanup()

    def write_report(self, fail=False):
        by_payload = {json.dumps(c.payload(), sort_keys=True): c for c in self.cases}
        def handler(request):
            body = json.loads(request.content)
            case = by_payload[json.dumps({k: body[k] for k in ('state', 'questions')}, sort_keys=True)]
            return httpx.Response(401) if fail else httpx.Response(200, json=response_for(case))
        adapter = Adapter('jev', 'fake-boundary-key', {}, client=httpx.Client(transport=httpx.MockTransport(handler)))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                run(self.cases, {'jev': adapter}, {}, self.path, experiment=self.metadata)
        finally:
            adapter.close()

    def test_success_is_local_judgment_only_and_report_cannot_be_overwritten(self):
        self.write_report()
        result = analyze(self.path)
        self.assertTrue(result['all_calls_valid'])
        self.assertFalse(result['harness_executed'])
        self.assertFalse(result['production_integrated'])
        self.assertFalse(result['calibrated_threshold'])
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.write_report()
        self.assertEqual(self.path.read_bytes(), before)

    def test_authentication_failure_is_not_a_negative_answer_or_a_success(self):
        self.write_report(fail=True)
        result = analyze(self.path)
        self.assertFalse(result['all_calls_valid'])
        self.assertEqual(sum(g['requests'] for g in result['groups'].values()), 1)
        for detail in result['details']:
            self.assertIsNone(detail['labels'])
            self.assertIsNone(detail['errors'])
            self.assertIsNone(detail['potential_risks'])
            self.assertFalse(detail['exact'])
            self.assertEqual(detail['gate_reasons'], ['call_failed'])

    def test_missing_row_remains_in_plan_and_needs_review(self):
        self.write_report()
        values = [json.loads(line) for line in self.path.read_text().splitlines()]
        rows = values[1:-2]
        self.path.write_text(''.join(json.dumps(v) + '\n' for v in [values[0], *rows, summarize(values[0], rows)]))
        result = analyze(self.path)
        self.assertFalse(result['all_calls_valid'])
        self.assertEqual(sum(d['status'] == 'missing' for d in result['details']), 1)
        self.assertTrue(any(d['gate_reasons'] == ['missing_result'] for d in result['details']))

    def test_manifest_cannot_change_which_variant_was_run(self):
        self.write_report()
        values = [json.loads(line) for line in self.path.read_text().splitlines()]
        values[0]['experiment']['variants'] = ['v0', 'v1', 'resource']
        self.path.write_text(''.join(json.dumps(v) + '\n' for v in values))
        validate_report(self.path)
        with self.assertRaisesRegex(ValueError, 'manifest/trial'):
            analyze(self.path)


class BoundarySelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='.jev-selection-test-', dir=ROOT)
        cls.regression = Path(cls.directory.name) / 'regression.jsonl'
        cls.combination = Path(cls.directory.name) / 'combination.jsonl'
        scenarios = [s for s in load_scenarios() if s.split == 'regression']
        for path, variants in ((cls.regression, BASE_VARIANTS), (cls.combination, ('v1', 'scope+resource'))):
            cases, metadata = plan(scenarios, variants)
            by_payload = {json.dumps(c.payload(), sort_keys=True): c for c in cases}
            def handler(request):
                body = json.loads(request.content)
                case = copy.deepcopy(by_payload[json.dumps({k: body[k] for k in ('state', 'questions')}, sort_keys=True)])
                if case.id.split('/')[1] == 'A005-coding-capability' and case.id.split('/')[2] in {'v0', 'v1', 'progress'}:
                    case.expected['resource_boundary'] = 'capability_question'
                return httpx.Response(200, json=response_for(case))
            adapter = Adapter('jev', 'fake-selection-key', {}, client=httpx.Client(transport=httpx.MockTransport(handler)))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    run(cases, {'jev': adapter}, {}, path, experiment=metadata)
            finally:
                adapter.close()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_multiple_eligible_factors_require_combination_evidence(self):
        with self.assertRaisesRegex(ValueError, 'require a combination regression'):
            selection(self.regression)

    def test_selection_is_recomputed_and_tampered_candidate_is_rejected(self):
        value = selection(self.regression, self.combination)
        self.assertEqual(value['candidate'], 'scope+resource')
        self.assertEqual(value['validation_status'], 'not_run')
        path = Path(self.directory.name) / 'selection.json'
        path.write_text(json.dumps(value))
        self.assertEqual(verify_selection(path), value)
        value['candidate'] = 'progress'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'frozen criteria'):
            verify_selection(path)

    def test_subset_and_validation_evidence_cannot_select_a_candidate(self):
        with self.assertRaises(ValueError):
            selection(self.combination)
        result = analyze(self.regression)
        result['details'][0]['split'] = 'validation'
        with self.assertRaisesRegex(ValueError, 'regression-only'):
            eligible(result)


if __name__ == '__main__':
    unittest.main()
