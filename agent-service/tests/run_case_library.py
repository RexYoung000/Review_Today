"""Validate the catalog offline; opt in to fixed-context real-model replays."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

# Support both `python tests/run_case_library.py` and `python -m tests.run_case_library`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.case_library.schema import digest, load, select


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--report', type=Path, help='check a recorded result offline, including missing/failing cases')
    args = parser.parse_args()
    try:
        if args.report:
            if args.live or args.cases or args.output:
                parser.error('--report cannot be combined with execution options')
            from tests.case_library.results import read_report
            result = read_report(args.report)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['automatic_result'] == 'PASS' else 1
        catalog, suite = load()
        if not args.live:
            if args.cases or args.output:
                parser.error('--cases/--output require explicit --live')
            print(json.dumps(dict(cases=len(catalog.cases), fixed_scenarios=len(suite.scenarios),
                                  result='VALID', note='Offline structure only; no model behavior evaluated.')))
            return 0
        selected = select(suite.scenarios, args.cases)
        if not args.output:
            parser.error('--live requires a new --output file')
        if args.output.exists():
            parser.error('output already exists; historical evidence cannot be overwritten')
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    # Set isolation before ANY service import (store modules create their DB).
    with tempfile.TemporaryDirectory(prefix='review-case-library-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'state.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from tests.case_library.recording import RunReport
        from tests.case_library.replay import run_one
        with RunReport(args.output, layer='live_fixed_context', planned=[s.id for s in selected],
                       fixture=dict(catalog_sha256=digest(catalog.model_dump()),
                                    scenarios=[s.model_dump() for s in selected])) as report:
            for i, scenario in enumerate(selected):
                # Each scenario has its own DB, so a failed/mutated previous case
                # cannot become an accidental cross-session resume candidate.
                harness = ConversationHarness(ConversationStore(HarnessStore(str(Path(directory) / f'{i}.sqlite3'))))
                calls_start, tools_start = len(report.calls), len(report.tool_attempts)
                try:
                    run_one(harness, report, scenario)
                except Exception as exc:
                    report.write(dict(type='case_error', id=scenario.id, error_type=type(exc).__name__,
                                      model_calls=report.calls[calls_start:], tool_attempts=report.tool_attempts[tools_start:]))
                print(json.dumps(dict(case=scenario.id, recorded=any(r['id'] == scenario.id for r in report.records))), flush=True)
        print(json.dumps(dict(result='PASS' if report.passed else 'FAIL', output=str(args.output))))
        return 0 if report.passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
