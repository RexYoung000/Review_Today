"""Fault injection and evidence integrity, entirely offline."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import httpx

from tests.judgment_comparison.adapters import Adapter, JEV_MODEL, usage_of
from tests.judgment_comparison.cases import ROOT, evaluate, load_suite, select_cases, validate_answers
from tests.judgment_comparison.reporting import markdown_report, price_range, validate_report
from tests.run_judgment_comparison import run


def answers_for(case, labels=None):
    labels = labels or case.expected
    return {key: dict(type='choice', choice=labels[key], confidence=1.0,
                     probabilities={c: float(c == labels[key]) for c in q.criteria})
            for key, q in case.questions.items()}


def response_for(case, provider='jev', answers=None, model=None):
    answers = answers if answers is not None else answers_for(case)
    value = dict(model=model or (JEV_MODEL if provider == 'jev' else 'deepseek-flash'),
                 usage=dict(input_tokens=200, output_tokens=100, input_tokens_details=dict(cached_tokens=100)))
    if provider == 'jev':
        value['answers'] = answers
    else:
        value.update(status='completed', output=[dict(type='message', content=[
            dict(type='output_text', text=json.dumps(dict(answers=answers)))])])
    return value


class JudgmentFixturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_suite()

    def test_complete_coverage_and_original_history(self):
        self.assertEqual(len(self.cases), 55)
        self.assertEqual(sum(len(c.questions) for c in self.cases), 299)
        self.assertEqual({k: len(select_cases(self.cases, [k])) for k in ('dialogue', 'memory', 'source', 'grading')},
                         dict(dialogue=31, memory=6, source=6, grading=12))
        prior = next(c for c in self.cases if c.id == 'A013-foreign-goal-transition')
        self.assertTrue(prior.state['initial']['other_goals'])
        self.assertEqual(prior.expected['progress'], 'clarify_next')

    def test_gold_is_not_sent_to_model(self):
        for case in self.cases:
            with self.subTest(case=case.id):
                def inspect(value):
                    if isinstance(value, dict):
                        self.assertFalse(any(k.startswith('expected') for k in value))
                        for v in value.values():
                            inspect(v)
                    elif isinstance(value, list):
                        for v in value:
                            inspect(v)
                self.assertEqual(set(case.payload()), {'state', 'questions'})
                inspect(case.payload())
                self.assertTrue(evaluate(case, answers_for(case))['all_match'])

    def test_unknown_and_duplicate_selectors_rejected(self):
        for names in (['missing'], ['dialogue', 'dialogue']):
            with self.assertRaises(ValueError):
                select_cases(self.cases, names)

    def test_all_irrelevant_does_not_select_first_ranked(self):
        for kind in ('memory', 'source'):
            case = next(c for c in self.cases if c.id == kind + '-none')
            self.assertEqual(evaluate(case, answers_for(case))['selected'], [])

    def test_deduplication_and_exact_official_domain_are_program_gates(self):
        for identity, expected in [('memory-duplicates', ['m1']), ('source-duplicates', ['s1']), ('source-official', ['s2'])]:
            case = next(c for c in self.cases if c.id == identity)
            self.assertEqual(evaluate(case, answers_for(case))['selected'], expected)

    def test_misconception_and_self_report_cannot_become_complete_answer(self):
        for case in select_cases(self.cases, ['grading']):
            if case.id.endswith(('wrong', 'mixed', 'self-report', 'omission')):
                self.assertFalse(evaluate(case, answers_for(case))['complete_answer'])
        case = next(c for c in self.cases if c.id == 'grade-rag-mixed')
        invented = {k: 'absent' if k == 'misconception' else 'covered' for k in case.questions}
        result = evaluate(case, answers_for(case, invented))
        self.assertTrue(result['false_mastery'])
        self.assertFalse(result['all_match'])

    def test_unsure_is_review_not_a_confident_negative(self):
        case = self.cases[0]
        labels = dict(case.expected, progress='unsure')
        result = evaluate(case, answers_for(case, labels))
        self.assertTrue(result['needs_review'])
        self.assertFalse(result['all_match'])

    def test_offline_cli_does_not_require_provider_or_create_database(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'must-not-exist.sqlite3'
            env = {**os.environ, 'REVIEW_TODAY_LLM_PROVIDER': 'invalid-do-not-load',
                   'REVIEW_TODAY_HARNESS_DB': str(db), 'TYPESAFE_API_KEY': '', 'DEEPSEEK_API_KEY': ''}
            process = subprocess.run([sys.executable, str(ROOT / 'agent-service/tests/run_judgment_comparison.py')],
                                     capture_output=True, text=True, env=env)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)['cases'], 55)
            self.assertFalse(db.exists())


class JudgmentTransportTests(unittest.TestCase):
    def setUp(self):
        self.case = load_suite()[0]
        self.models = dict(router='deepseek-flash', coach='deepseek-v4-flash', risk='deepseek-v4-pro')
        self.adapters = []

    def tearDown(self):
        for adapter in self.adapters:
            adapter.close()

    def adapter(self, handler, provider='jev'):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        adapter = Adapter(provider, 'test-secret-not-a-key', self.models, client=client, sleeper=lambda _: None)
        self.adapters.append(adapter)
        return adapter

    def test_both_providers_receive_identical_semantic_material_and_questions(self):
        bodies = {}
        for provider in ('jev', 'deepseek'):
            def handler(request, provider=provider):
                bodies[provider] = json.loads(request.content)
                self.assertEqual(request.url.host, 'api.typesafe.ai' if provider == 'jev' else 'api.deepseek.com')
                return httpx.Response(200, json=response_for(self.case, provider))
            self.assertEqual(self.adapter(handler, provider).call(self.case)['status'], 'ok')
        jev = {k: bodies['jev'][k] for k in ('state', 'questions')}
        deepseek = json.loads(bodies['deepseek']['input'][1]['content'])
        self.assertEqual(jev, deepseek)
        self.assertEqual(bodies['deepseek']['reasoning'], {'effort': 'none'})

    def test_auth_and_permission_errors_stop_provider_without_retries(self):
        for status in (401, 403):
            with self.subTest(status=status):
                adapter = self.adapter(lambda _: httpx.Response(status, text='sensitive upstream body'))
                failed = adapter.call(self.case)
                blocked = adapter.call(self.case)
                self.assertEqual(len(failed['attempts']), 1)
                self.assertEqual(blocked['status'], 'unavailable')
                self.assertEqual(blocked['attempts'], [])
                self.assertIsNone(failed['answers'])
                self.assertIsNone(failed['raw_response'])

    def test_transient_http_retries_once_and_records_both_requests(self):
        for status in (429, 529):
            responses = iter([httpx.Response(status), httpx.Response(200, json=response_for(self.case))])
            record = self.adapter(lambda _: next(responses)).call(self.case)
            self.assertEqual(record['status'], 'ok')
            self.assertEqual([a['status'] for a in record['attempts']], [status, 200])
            self.assertIsNone(record['attempts'][0]['usage'])

    def test_timeouts_do_not_become_negative_answers_or_retry_forever(self):
        def handler(request):
            raise httpx.ReadTimeout('private error text', request=request)
        adapter = self.adapter(handler)
        for _ in range(3):
            record = adapter.call(self.case)
            self.assertEqual(len(record['attempts']), 2)
            self.assertEqual(record['error'], 'timeout')
            self.assertIsNone(record['answers'])
        self.assertEqual(adapter.call(self.case)['status'], 'unavailable')
        self.assertEqual(adapter.requests, 6)

    def test_redirect_cannot_send_key_to_another_host(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(307, headers={'location': 'https://other.invalid/collect'})
        result = self.adapter(handler).call(self.case)
        self.assertEqual(len(requests), 1)
        self.assertEqual(result['error'], 'HTTP_307')

    def test_invalid_answers_and_model_drift_do_not_retry(self):
        base = response_for(self.case)
        missing = copy.deepcopy(base)
        missing['answers'].pop('progress')
        extra = copy.deepcopy(base)
        extra['answers']['fabricated_candidate'] = extra['answers']['progress']
        wrong_model = dict(base, model='jev-latest-new-version')
        for body in (missing, extra, wrong_model):
            result = self.adapter(lambda _, body=body: httpx.Response(200, json=body)).call(self.case)
            self.assertEqual(result['error'], 'invalid_response')
            self.assertEqual(len(result['attempts']), 1)
            self.assertIsNone(result['answers'])

    def test_malformed_json_and_refusal_are_errors(self):
        adapter = self.adapter(lambda _: httpx.Response(200, text='{'))
        self.assertEqual(adapter.call(self.case)['error'], 'invalid_response')
        body = response_for(self.case, 'deepseek')
        body['output'] = [dict(content=[dict(type='refusal', refusal='no')])]
        result = self.adapter(lambda _: httpx.Response(200, json=body), 'deepseek').call(self.case)
        self.assertEqual(result['error'], 'invalid_response')

    def test_unknown_labels_invalid_probabilities_and_missing_fields_rejected(self):
        for invalid in (-0.1, 1.1, float('nan'), float('inf'), True, None):
            with self.subTest(invalid=invalid):
                answers = answers_for(self.case)
                answers['progress']['confidence'] = invalid
                with self.assertRaises(ValueError):
                    validate_answers(self.case, answers)
        for mutation in ('label', 'sum', 'probability_key', 'winner'):
            answers = answers_for(self.case)
            a = answers['progress']
            if mutation == 'label':
                a['choice'] = 'nonexistent'
            elif mutation == 'sum':
                a['probabilities']['none'] = 0.5
            elif mutation == 'probability_key':
                a['probabilities'].pop('none')
            else:
                a['choice'] = 'none'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_answers(self.case, answers)

    def test_response_credentials_are_redacted_and_usage_is_not_invented(self):
        body = response_for(self.case)
        body['debug'] = 'test-secret-not-a-key'
        result = self.adapter(lambda _: httpx.Response(200, json=body)).call(self.case)
        self.assertNotIn('test-secret-not-a-key', json.dumps(result))
        self.assertIsNone(usage_of({}))
        self.assertEqual(usage_of({'usage': {'input_tokens': -5}})['input_tokens'], None)


class JudgmentReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'results.jsonl'
        self.case = load_suite()[0]
        self.adapter = Adapter('jev', 'test-secret', {}, sleeper=lambda _: None,
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_for(self.case)))))

    def tearDown(self):
        self.adapter.close()
        self.tmp.cleanup()

    def generate(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return run([self.case], {'jev': self.adapter}, {}, self.path)

    def read(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def write(self, rows):
        self.path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')

    def test_report_replays_and_markdown_exports_offline(self):
        result = self.generate()
        self.assertEqual(validate_report(self.path), result)
        self.assertTrue(result['execution_complete'])
        self.assertTrue(result['all_assertions_match'])
        self.assertIn('不是完整会话', markdown_report(self.path))
        self.assertFalse(result['native_tested'])

    def test_existing_evidence_cannot_be_overwritten_or_trigger_calls(self):
        self.generate()
        before, requests = self.path.read_bytes(), self.adapter.requests
        with self.assertRaises(FileExistsError):
            self.generate()
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(requests, self.adapter.requests)

    def test_truncated_duplicate_missing_and_tampered_reports_are_rejected(self):
        self.generate()
        original = self.read()
        variants = [original[:-1], [original[0], original[1], original[1], original[2]], [original[0], original[2]]]
        for field, value in [('input', {}), ('evaluation', {}), ('id', 'unknown'), ('status', 'made-up'), ('elapsed_ms', -1)]:
            changed = copy.deepcopy(original)
            changed[1][field] = value
            variants.append(changed)
        for mutate in ('answer', 'request', 'summary', 'empty_plan', 'usage'):
            changed = copy.deepcopy(original)
            if mutate == 'answer':
                changed[1]['answers']['progress']['choice'] = 'none'
            elif mutate == 'request':
                changed[1]['request']['state']['current_input'] = 'different'
            elif mutate == 'summary':
                changed[-1]['groups']['jev/dialogue']['correct_questions'] += 1
            elif mutate == 'empty_plan':
                changed[0]['cases'] = []
            else:
                changed[1]['attempts'][0]['usage']['input_tokens'] = -1
            variants.append(changed)
        for index, values in enumerate(variants):
            self.write(values)
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_report(self.path)

    def test_model_error_is_recorded_as_incomplete_not_pass(self):
        self.adapter.client.close()
        self.adapter.client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401)))
        result = self.generate()
        self.assertFalse(result['execution_complete'])
        self.assertFalse(result['all_assertions_match'])
        self.assertEqual(result['groups']['jev/dialogue']['valid'], 0)
        self.assertIsNone(result['groups']['jev/dialogue']['known_cost_usd_range'])
        self.assertFalse(result['groups']['jev/dialogue']['cost_complete'])
        self.assertEqual(validate_report(self.path), result)

    def test_missing_usage_cost_is_unknown_not_free(self):
        prices = {'rates': {'m': {'input': [1, 2], 'cached': [0.1, 0.2], 'output': [3, 4]}}}
        self.assertIsNone(price_range('m', None, prices))
        self.assertIsNone(price_range('m', dict(input_tokens=None, output_tokens=2), prices))
        self.assertEqual(price_range('m', dict(input_tokens=100, output_tokens=50, cached_input_tokens=20), prices),
                         [0.000232, 0.000364])
        self.assertEqual(price_range('m', dict(input_tokens=100, output_tokens=50, cached_input_tokens=None), prices),
                         [0.00016, 0.0004])


if __name__ == '__main__':
    unittest.main()
