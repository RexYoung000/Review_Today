"""Observe one new run and close this QA budget at its terminal boundary."""
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
EVIDENCE=Path(__file__).resolve().parent
setup=json.loads((EVIDENCE/'setup.json').read_text())
directory=Path(setup['directory'])
os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory/'checkpoint.sqlite3'),REVIEW_TODAY_JEV_TEST='0')
sys.path.insert(0,str(ROOT/'agent-service'))
from agent_service.conversation_store import ConversationStore
from agent_service.harness_store import HarnessStore

store=ConversationStore(HarnessStore(str(directory/'checkpoint.sqlite3')))
before=json.loads((EVIDENCE/'before-input.json').read_text())
started=time.monotonic()
while True:
    actual=store.get(setup['session_id'])
    runs=[r for identity,r in actual['runs'].items() if identity not in before['runs']]
    assert len(runs)<=1
    count=json.loads((directory/'request-count.json').read_text())['actual_requests']
    if runs and runs[0]['status'] in {'completed','retryable_failed','failed','cancelled','stopped'}:
        run=runs[0]
        marker=directory/'STOP'
        if not marker.exists():
            marker.write_text(f"STOP: one independent-topic real subcheck reached {run['status']} at {count}/30; no more model calls or later gates.\n")
        result=dict(request_count=count,limit=30,status=run['status'],run_id=run['run_id'],error=run.get('error_code'),terminal_stop_written=True,observer_seconds=time.monotonic()-started)
        (EVIDENCE/'stop-boundary.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result));break
    if time.monotonic()-started>=35:
        print(json.dumps(dict(request_count=count,status=runs[0]['status'] if runs else 'not accepted',terminal=False,observer_seconds=time.monotonic()-started)));break
    time.sleep(0.2)
