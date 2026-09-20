"""Run current DeepSeek and a cached resource-field intervention in temporary DBs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.judgment_comparison.resource_replay import bind_interceptor, load_cache, summarize_harness
from tests.judgment_comparison.cases import FIXTURES
from tests.case_library.schema import load


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--selection', type=Path)
    parser.add_argument('--validation', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.report:
            if any((args.live, args.selection, args.validation, args.output)):
                parser.error('--report cannot be combined with execution')
            result = summarize_harness(args.report)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['audited_result'] == 'PASS' else 1
        if not args.selection or not args.validation:
            parser.error('requires frozen selection and validation evidence')
        cache, experiment = load_cache(args.selection, args.validation)
        _, suite = load()
        scenarios = suite.scenarios
        if any(s.id not in cache for s in scenarios):
            parser.error('missing cached judgments')
        planned = [s.id + '/' + v for index, s in enumerate(scenarios)
                   for v in (('deepseek', 'resource') if index % 2 == 0 else ('resource', 'deepseek'))]
        if not args.live:
            if args.output:
                parser.error('--output requires --live')
            print(json.dumps(dict(result='VALID', paired_turns=len(planned), new_jev_requests=0,
                note='Preflight only; no App, provider config or database imported.')))
            return 0
        if not args.output or args.output.exists():
            parser.error('--live requires a new output path')
        with tempfile.TemporaryDirectory(prefix='review-jev-resource-harness-') as directory:
            os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'unused.sqlite3')
            from agent_service import conversation
            from agent_service.conversation import ConversationHarness
            from agent_service.conversation_store import ConversationStore
            from agent_service.harness_store import HarnessStore
            from tests.case_library.recording import RunReport
            from tests.case_library.replay import run_one

            class ResourceReport(RunReport):
                def __enter__(self):
                    super().__enter__()
                    # The parent observer records the actual DeepSeek response first.
                    # Intervention is applied AFTER observation, never relabelled as model output.
                    observed_parse = conversation.parse_model
                    intercept = bind_interceptor(observed_parse, lambda: dict(
                        variant=self.variant, cached=cache[self.identity], events=self.interventions))
                    self.stack.enter_context(patch('agent_service.conversation.parse_model', side_effect=intercept))
                    return self

                def turn(self, *args, **kwargs):
                    start = time.perf_counter()
                    record = super().turn(*args, **kwargs)
                    record['replay_elapsed_ms'] = round((time.perf_counter() - start) * 1000, 3)
                    record['resource_interventions'] = list(self.interventions)
                    return record

                def add(self, identity, record, checks):
                    super().add(identity + '/' + self.variant, record, checks)

            fixture = dict(experiment=experiment, scenarios=[s.model_dump() for s in scenarios],
                prices=json.loads((FIXTURES / 'prices.json').read_text()),
                cached_judgments={s.id: cache[s.id] for s in scenarios})
            with ResourceReport(args.output, layer='live_fixed_context', planned=planned, fixture=fixture) as report:
                for index, scenario in enumerate(scenarios):
                    variants = ('deepseek', 'resource') if index % 2 == 0 else ('resource', 'deepseek')
                    for variant in variants:
                        report.variant, report.identity, report.interventions = variant, scenario.id, []
                        harness = ConversationHarness(ConversationStore(HarnessStore(str(Path(directory) / f'{index}-{variant}.sqlite3'))))
                        calls_start, tools_start = len(report.calls), len(report.tool_attempts)
                        try:
                            run_one(harness, report, scenario)
                        except Exception as exc:
                            report.write(dict(type='case_error', id=scenario.id + '/' + variant,
                                error_type=type(exc).__name__, model_calls=report.calls[calls_start:],
                                tool_attempts=report.tool_attempts[tools_start:], resource_interventions=list(report.interventions)))
                        print(json.dumps(dict(case=scenario.id, variant=variant,
                            recorded=any(r['id'] == scenario.id + '/' + variant for r in report.records))), flush=True)
            result = summarize_harness(args.output)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['audited_result'] == 'PASS' else 1
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
