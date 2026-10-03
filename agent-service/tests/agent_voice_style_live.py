"""Paid single-turn style replay, using only a prior synthetic voice report.

Preserves the real first reply and original second input; does not run ASR,
readout, a microphone or the daily service. Semantics remain a human judgment.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', required=True, action='store_true')
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('use a new evidence file')
    source = [json.loads(line) for line in args.source.read_text().splitlines()]
    header = source[0]
    if header.get('type') != 'header' or header.get('fixture', {}).get('synthetic') is not True:
        parser.error('only an explicitly synthetic Agent voice report is accepted')
    original = next(record for record in source if record.get('type') == 'result' and record.get('id') == 'turn2')
    with tempfile.TemporaryDirectory(prefix='review-today-agent-voice-style-') as scratch:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(scratch) / 'synthetic.sqlite3')
        os.environ['REVIEW_TODAY_JEV_TEST'] = '0'
        from agent_service.conversation import ConversationHarness
        from agent_service.schemas import SessionMessageRequest
        from tests.case_library.recording import RunReport
        harness = ConversationHarness()
        sid = original['before']['session_id']
        with harness.store.transaction(sid) as data:
            # RunReport projects absent optional fields as null; omit those
            # placeholders instead of turning live collection defaults into None.
            data.update(copy.deepcopy({k: value for k, value in original['before'].items() if value is not None}))
        body = SessionMessageRequest(client_message_id=str(uuid4()), content=original['input']['content'], input_channel='voice')
        with RunReport(args.output, layer='live_fixed_context', planned=['turn2_style'],
                       fixture=dict(synthetic=True, input_channel='voice',
                                    source=args.source.name, source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                                    source_case='turn2', purpose='One voice style revision with the original real first-turn context')) as report:
            record = report.turn(harness, sid, body)
            report.add('turn2_style', record, dict(
                original_context=record['before']['messages'] == original['before']['messages'],
                exact_second_input=record['input']['content'] == original['input']['content'],
                voice_channel=record['run'].get('input_channel') == 'voice'))
            print(json.dumps(dict(replies=record['replies'], status=record['run']['status'],
                                  semantic_review='manual; no keyword or brevity pass', report=str(args.output)), ensure_ascii=False), flush=True)
        raise SystemExit(0 if report.passed else 1)


if __name__ == '__main__':
    main()
