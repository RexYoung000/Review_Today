"""Three frozen Jev variants; development first, then reserved validation data."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.judgment_comparison.calibration import analyze, load_scenarios, markdown, plan
from tests.run_judgment_comparison import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--split', choices=['development', 'validation'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--markdown', type=Path)
    parser.add_argument('--jev-key-stdin', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.report:
            if args.live or args.split or args.output or args.jev_key_stdin:
                parser.error('--report cannot be combined with execution options')
            result = analyze(args.report)
            if args.markdown:
                with args.markdown.open('x', encoding='utf-8') as file:
                    file.write(markdown(args.report))
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['all_calls_valid'] else 1
        if args.markdown:
            parser.error('--markdown requires --report')
        scenarios = load_scenarios()
        if args.split:
            scenarios = [s for s in scenarios if s.split == args.split]
        cases, metadata = plan(scenarios)
        if not args.live:
            if args.output or args.jev_key_stdin:
                parser.error('--output/--jev-key-stdin require --live')
            print(json.dumps(dict(result='VALID', scenarios=len(scenarios), trials=len(cases),
                questions=sum(len(c.questions) for c in cases),
                note='Offline only; no provider configuration, model call or database.')))
            return 0
        if not args.split or not args.output or args.output.exists():
            parser.error('--live requires an explicit split and a new output path')
        from tests.judgment_comparison.adapters import Adapter
        adapter = None
        try:
            with tempfile.TemporaryDirectory(prefix='review-jev-calibration-') as directory:
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
            if adapter is not None:
                adapter.close()
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
