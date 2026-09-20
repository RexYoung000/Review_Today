"""Frozen single-factor experiment; production configuration stays untouched."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.judgment_comparison.boundaries import (
    BASE_VARIANTS, FACTORS, analyze, eligible, load_scenarios, markdown, plan, selection, verify_selection,
)
from tests.run_judgment_comparison import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--stage', choices=['regression', 'combination', 'validation'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--markdown', type=Path)
    parser.add_argument('--regression-report', type=Path)
    parser.add_argument('--combination-report', type=Path)
    parser.add_argument('--freeze-selection', type=Path)
    parser.add_argument('--selection', type=Path)
    parser.add_argument('--jev-key-stdin', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.report:
            if any((args.live, args.stage, args.output, args.regression_report, args.combination_report,
                    args.freeze_selection, args.selection, args.jev_key_stdin)):
                parser.error('--report cannot be combined with execution or selection')
            result = analyze(args.report)
            if args.markdown:
                with args.markdown.open('x') as f:
                    f.write(markdown(args.report))
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['all_calls_valid'] else 1
        if args.markdown:
            parser.error('--markdown requires --report')
        if args.freeze_selection:
            if not args.regression_report or any((args.live, args.stage, args.output, args.selection, args.jev_key_stdin)):
                parser.error('--freeze-selection requires regression evidence and no execution options')
            value = selection(args.regression_report, args.combination_report)
            with args.freeze_selection.open('x') as f:
                json.dump(value, f, ensure_ascii=False, indent=2)
                f.write('\n')
            print(json.dumps(value, ensure_ascii=False))
            return 0
        if args.combination_report:
            parser.error('--combination-report is only used to freeze selection')
        scenarios = load_scenarios()
        variants = BASE_VARIANTS
        if args.stage == 'combination':
            if not args.regression_report or args.selection:
                parser.error('combination requires --regression-report')
            options = eligible(analyze(args.regression_report))
            if len(options) < 2:
                parser.error('fewer than two eligible factors; no combination experiment')
            # Verify the complete regression manifest before deriving a combination.
            try:
                selection(args.regression_report)
            except ValueError as exc:
                if not str(exc).startswith('eligible factors require a combination regression'):
                    raise
            variants = ('v1', '+'.join(f for f in FACTORS if f in options))
        elif args.regression_report:
            parser.error('--regression-report requires combination or freeze-selection')
        if args.stage == 'validation':
            if not args.selection:
                parser.error('validation requires a frozen --selection')
            candidate = verify_selection(args.selection)['candidate']
            if not candidate:
                parser.error('no eligible candidate; validation not authorized by experiment criteria')
            variants = ('v0', 'v1', candidate)
        elif args.selection:
            parser.error('--selection only applies to validation')
        if args.stage:
            split = 'validation' if args.stage == 'validation' else 'regression'
            scenarios = [s for s in scenarios if s.split == split]
        cases, metadata = plan(scenarios, variants)
        if not args.live:
            if args.output or args.jev_key_stdin:
                parser.error('--output/--jev-key-stdin require --live')
            print(json.dumps(dict(result='VALID', scenarios=len(scenarios), trials=len(cases),
                questions=sum(len(c.questions) for c in cases), variants=variants,
                note='Offline only; default is structure inventory, not an execution authorization.')))
            return 0
        if not args.stage or not args.output or args.output.exists():
            parser.error('--live requires a stage and new output path')
        from tests.judgment_comparison.adapters import Adapter
        adapter = None
        try:
            with tempfile.TemporaryDirectory(prefix='review-jev-boundaries-') as directory:
                os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'unused.sqlite3')
                key = (getpass.getpass('Jev credential (hidden, not saved): ') if sys.stdin.isatty()
                       else sys.stdin.readline().strip()) if args.jev_key_stdin else os.getenv('TYPESAFE_API_KEY', '').strip()
                adapter = Adapter('jev', key, {})
                key = None
                run(cases, {'jev': adapter}, {}, args.output, experiment=metadata)
                result = analyze(args.output)
                print(json.dumps(dict(all_calls_valid=result['all_calls_valid'], groups=result['groups']), ensure_ascii=False))
                return 0 if result['all_calls_valid'] else 1
        finally:
            if adapter:
                adapter.close()
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
