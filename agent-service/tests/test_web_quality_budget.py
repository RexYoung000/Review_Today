"""The opt-in evaluator cannot silently repair/retry paid generation or invent evidence."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_service.call_errors import ModelCallError, WebToolError
from tests import compare_web_quality_live as comparison

MANIFEST = Path(__file__).resolve().parents[2] / 'docs/evidence/2026-10-18-web-quality/manifest.json'


class QualityBudgetTests(unittest.TestCase):
    def execute(self, directory, *, readable=True):
        from agent_service import config, openai_client, web_tools
        target = Path(directory) / 'new-evaluation'
        found = json.dumps(dict(results=[dict(url='https://example.com/one', title='One'),
                                        dict(url='https://example.com/two', title='Two')]))
        def generation(*args, on_request, on_usage, **kwargs):
            on_request()
            raise ModelCallError('SCHEMA')  # A failed first answer must remain failed.
        with patch('sys.argv', ['comparison', '--live', '--manifest', str(MANIFEST), '--directory', str(target)]), \
                patch.dict(os.environ, {'DEEPSEEK_WEB_API_KEY': 'TEST_ONLY'}), \
                patch.object(config, 'PROVIDER', 'deepseek'), patch.object(config, 'openai_key', return_value='TEST_ONLY'), \
                patch.object(openai_client, '_client') as client, \
                patch.object(openai_client, 'parse_model', side_effect=generation) as model, \
                patch.object(web_tools, 'web_search_text', return_value=found), \
                patch.object(web_tools, 'read_public_url', return_value=('Public', 'Public evidence about the current question.'),
                             side_effect=None if readable else WebToolError('READ_FAILED')), patch('builtins.print'):
            comparison.main()
            client.assert_not_called()
            return json.loads((target / 'results.json').read_text()), model.call_count

    def test_failed_generations_are_counted_once_and_never_repaired_or_retried(self):
        with tempfile.TemporaryDirectory(prefix='review-today-web-quality-budget-') as directory:
            report, calls = self.execute(directory)
        self.assertEqual(report['web_counts'], dict(search=18, read=36))
        self.assertEqual(calls, 9)
        self.assertEqual(len(report['model_requests']), 9)
        self.assertTrue(all(r['status'] == 'failed' for r in report['model_requests']))
        self.assertEqual(len({r['request_id'] for r in report['model_requests']}), 9)

    def test_no_readable_sources_means_no_generation_request(self):
        with tempfile.TemporaryDirectory(prefix='review-today-web-quality-budget-') as directory:
            report, calls = self.execute(directory, readable=False)
        self.assertEqual(calls, 0)
        self.assertEqual(report['model_requests'], [])
        generations = [r['generation']['status'] for r in report['cases'] if 'generation' in r]
        self.assertEqual(generations, ['skipped_no_readable_evidence'] * 9)
