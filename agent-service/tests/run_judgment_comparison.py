"""Validate or compare fixed synthetic judgments; never connect to the App."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.judgment_comparison.cases import FIXTURES, digest, evaluate, load_suite, select_cases
from tests.judgment_comparison.reporting import code_version, markdown_report, summarize, validate_report


def write_row(file, row):
    file.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
    file.flush()


def run(cases, adapters, models, output):
    from tests.judgment_comparison.adapters import SYSTEM
    header = dict(type='header', schema_version=1, layer='paired_component_judgment',
        started_at=datetime.now(timezone.utc).isoformat(), code=code_version(),
        cases=[c.model_dump() for c in cases], suite_sha256=digest([c.model_dump() for c in cases]),
        providers=list(adapters), deepseek_models=models, deepseek_system=SYSTEM,
        prices=json.loads((FIXTURES / 'prices.json').read_text()),
        isolation='fixed synthetic text only; no App, database, web tool or knowledge write',
        order='alternate provider order per case; serial calls; pooled connection per provider')
    rows, interrupted = [], False
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as file:
        write_row(file, header)
        try:
            for index, case in enumerate(cases):
                names = list(adapters)
                if index % 2:
                    names.reverse()
                for name in names:
                    record = adapters[name].call(case)
                    record.update(type='result', id=case.id, kind=case.kind,
                                  case_sha256=digest(case.model_dump()), evaluation=None,
                                  manual_review=case.manual_review, human_review='pending')
                    if record['status'] == 'ok':
                        record['evaluation'] = evaluate(case, record['answers'])
                    rows.append(record)
                    write_row(file, record)
                    print(json.dumps(dict(case=case.id, provider=name, status=record['status'],
                        all_match=(record['evaluation'] or {}).get('all_match'),
                        elapsed_ms=record['elapsed_ms'], error=record['error'])), flush=True)
        except (Exception, KeyboardInterrupt):
            interrupted = True
            raise
        finally:
            summary = summarize(header, rows, interrupted=interrupted)
            write_row(file, summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--cases', nargs='+', help='case IDs or dialogue/memory/source/grading')
    parser.add_argument('--providers', nargs='+', choices=['jev', 'deepseek'], default=['jev', 'deepseek'])
    parser.add_argument('--output', type=Path, help='new append-only JSONL file')
    parser.add_argument('--report', type=Path, help='validate a self-contained existing report offline')
    parser.add_argument('--markdown', type=Path, help='new Markdown report; only with --report')
    parser.add_argument('--jev-key-stdin', action='store_true', help='read key without echo or file storage')
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args(argv)
    try:
        if args.report:
            if args.live or args.cases or args.output or args.jev_key_stdin:
                parser.error('--report cannot be combined with execution options')
            result = validate_report(args.report)
            if args.markdown:
                with args.markdown.open('x', encoding='utf-8') as file:
                    file.write(markdown_report(args.report))
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['execution_complete'] else 1
        if args.markdown:
            parser.error('--markdown requires --report')
        if len(args.providers) != len(set(args.providers)):
            parser.error('duplicate provider')
        cases = select_cases(load_suite(), args.cases)
        if not args.live:
            if args.output or args.jev_key_stdin:
                parser.error('--output/--jev-key-stdin require --live')
            print(json.dumps(dict(result='VALID', cases=len(cases),
                judgments=sum(len(c.questions) for c in cases),
                kinds={k: sum(c.kind == k for c in cases) for k in ('dialogue', 'memory', 'source', 'grading')},
                note='Offline structure only; no provider/config/database access.')))
            return 0
        if not args.output or args.output.exists():
            parser.error('--live requires a new --output file; history cannot be overwritten')
        from tests.judgment_comparison.adapters import Adapter, configured_deepseek
        adapters, models = {}, {}
        try:
            # Establish isolation before reading ANY project configuration.
            with tempfile.TemporaryDirectory(prefix='review-judgment-comparison-') as directory:
                os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'unused.sqlite3')
                if 'deepseek' in args.providers:
                    key, models = configured_deepseek()
                    adapters['deepseek'] = Adapter('deepseek', key, models, timeout=args.timeout)
                    key = None
                if 'jev' in args.providers:
                    if args.jev_key_stdin:
                        key = getpass.getpass('Jev credential (hidden, not saved): ') if sys.stdin.isatty() else sys.stdin.readline().strip()
                    else:
                        key = os.getenv('TYPESAFE_API_KEY', '').strip()
                    adapters['jev'] = Adapter('jev', key, {}, timeout=args.timeout)
                    key = None
                ordered = {p: adapters[p] for p in args.providers}
                result = run(cases, ordered, models, args.output)
                # Re-read evidence, including input/output and summary checks.
                validate_report(args.output)
                print(json.dumps(dict(execution_complete=result['execution_complete'],
                    all_assertions_match=result['all_assertions_match'], output=str(args.output))))
                return 0 if result['execution_complete'] else 1
        finally:
            for adapter in adapters.values():
                adapter.close()
    except (ValueError, OSError) as exc:
        # These errors originate in local validation; provider bodies/credentials
        # never become exception messages in the adapter.
        parser.error(str(exc))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
