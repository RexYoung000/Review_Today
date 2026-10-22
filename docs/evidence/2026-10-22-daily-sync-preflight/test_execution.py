"""Exercise exact prepared executor components on protected copies, never daily."""
from contextlib import closing
import importlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from unittest.mock import patch
import uuid
from urllib.parse import urlsplit,unquote
from prepare import ROOT, OUT, PRIVATE, sha, write
import approval
import apply_prepared
import cleanup_backend

WORK=ROOT/'output/legacy-lifecycle-repair-2026-10-22'/('execution-twin-'+uuid.uuid4().hex);WORK.mkdir()
def audit(event,values):
    if event=='sqlite3.connect':
        raw=str(values[0]);path=unquote(urlsplit(raw).path) if raw.startswith('file:') else raw
        if not Path(path).resolve().is_relative_to(WORK):raise RuntimeError('Test cannot open a daily database')
    if event=='socket.connect' and not (isinstance(values[1],tuple) and values[1][0]=='127.0.0.1'):raise RuntimeError('No external sockets in executor tests')
sys.addaudithook(audit)
original={str(p):sha(p) for p in [PRIVATE/'operation-authorization.json',PRIVATE/'OPERATION_HOLD',PRIVATE/'activation/authorization.json',PRIVATE/'activation/HOLD']}
cases=[]
try:approval.require_approved()
except PermissionError:cases.append('actual_pending_operation_rejected_before_runtime')
else:raise AssertionError('Pending operation admitted')
assert 'agent_service.main' not in sys.modules
fixture=WORK/'approval';(fixture/'activation').mkdir(parents=True)
operation=json.loads((PRIVATE/'operation-authorization.json').read_text());operation['status']='approved'
activation=json.loads((PRIVATE/'activation/authorization.json').read_text());activation['status']='approved'
write(fixture/'operation-authorization.json',operation);write(fixture/'activation/authorization.json',activation)
(fixture/'OPERATION_HOLD').write_text('fixture')
with patch.object(approval,'PRIVATE',fixture):
    try:approval.require_approved()
    except PermissionError:cases.append('operation_hold_rejected')
    else:raise AssertionError('HOLD admitted')
(fixture/'OPERATION_HOLD').unlink();activation['actual_model_request_limit']=9;write(fixture/'activation/authorization.json',activation)
with patch.object(approval,'PRIVATE',fixture):
    try:approval.require_approved()
    except PermissionError:cases.append('unreviewed_model_limit_rejected')
    else:raise AssertionError('Wrong limit admitted')
activation['actual_model_request_limit']=8;activation['database_path']=str(WORK/'wrong.sqlite3');write(fixture/'activation/authorization.json',activation)
with patch.object(approval,'PRIVATE',fixture):
    try:approval.require_approved()
    except PermissionError:cases.append('wrong_startup_database_rejected')
    else:raise AssertionError('Wrong startup database admitted')
activation['database_path']=str(cleanup_backend.SUPPORT/'agent-harness.sqlite3')
for name in ['app.store','checkpoint.sqlite3','review.sqlite3']:
    shutil.copy2(PRIVATE/'fresh-input'/name,WORK/name)
shutil.copy2(PRIVATE/'fresh-input/pre-sept7-archive-proof.store',WORK/'archive-proof.store')
tool=apply_prepared.load_tool()
report=tool.repair(WORK,apply=True);assert report['written_records']==3
backend=WORK/'daily-twin';backend.mkdir()
for name in ['agent-harness.sqlite3','drift.sqlite3']:
    shutil.copy2(PRIVATE/'fresh-input/checkpoint.sqlite3',backend/name)
with closing(sqlite3.connect(backend/'drift.sqlite3')) as db:
    with db:db.execute("update agent_sessions_v2 set payload=payload||' ' where session_id=(select session_id from agent_sessions_v2 where session_id not in (?,?,?) order by session_id limit 1)",[r['session_id'] for r in tool.load_scope()['records']])
with closing(sqlite3.connect(backend/'drift.sqlite3')) as db:before=tool.table_snapshot(db)
try:apply_prepared.publish_metadata(WORK/'checkpoint.sqlite3',backend/'drift.sqlite3',tool)
except (RuntimeError,tool.RepairError):cases.append('unrelated_backend_drift_refused_without_writes')
else:raise AssertionError('Drift admitted')
with closing(sqlite3.connect(backend/'drift.sqlite3')) as db:assert tool.table_snapshot(db)==before
apply_prepared.publish_metadata(WORK/'checkpoint.sqlite3',backend/'agent-harness.sqlite3',tool)
with closing(sqlite3.connect(backend/'agent-harness.sqlite3')) as db:tool.selected_payloads(db,tool.load_scope(),already_applied=True)
cases.append('exact_three_metadata_delta_published_in_transaction')
# Only this fixture redirects the destination and approval callback; no cleanup logic is patched.
activation['actual_model_request_limit']=8
with patch.object(cleanup_backend,'SUPPORT',backend),patch.object(cleanup_backend,'require_approved',lambda: (operation,activation)):
    cleanup_backend.cleanup(WORK)
result=json.loads((WORK/'actual-backend-result.json').read_text())
assert result['sessions']==37 and result['production_http_requests']==68
cases.append('same_backend_executor_got_37_real_fixture_receipts')
assert all(sha(Path(p))==v for p,v in original.items())
assert not (PRIVATE/'activation/quota.json').exists() and not (PRIVATE/'execution.json').exists()
write(OUT/'execution-checks.json',dict(outcome='PASS',cases=cases,fixture_directory=str(WORK),
    actual_prepared_authorizations_unchanged=True,daily_database_access_forbidden=True,
    target_and_approval_overridden_in_fixture_only=True,actual_daily_executor_not_run=True,
    actual_model_requests=0,actual_web_operations=0))
print('PASS prepared executor: pending/HOLD/limits, drift rejection, transactional metadata, 37 fixture receipts')
