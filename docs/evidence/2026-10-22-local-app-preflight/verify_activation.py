"""Read-only post-activation checks. Never launches an App or service."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess

from prepare import DAILY, DATABASES, OUT, PRIVATE, ROOT, SUPPORT, PROJECT_DIFF, digest, signature, stopped, write


def read(path):
    return json.loads(path.read_text())


def snapshot():
    result, integrity, history_counts = {}, {}, {}
    for rel in DATABASES:
        with sqlite3.connect((SUPPORT/rel).as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory = sqlite3.Row
            integrity[rel] = [r[0] for r in db.execute('pragma integrity_check')]
            assert integrity[rel] == ['ok']
            tables = {}
            for (table,) in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall():
                if table in ['ACHANGE','ATRANSACTION']:
                    history_counts[table] = db.execute('select count(*) from '+table).fetchone()[0]
                    continue
                rows = [dict(r) for r in db.execute('select * from "'+table+'"')]
                for row in rows:
                    for key,value in row.items():
                        if isinstance(value,bytes): row[key] = dict(bytes_hex=value.hex())
                tables[table] = rows
            result[rel] = tables
    return result, integrity, history_counts


def main():
    stopped()
    before = read(PRIVATE/'before-activation-detail.json')
    after, integrity, history = snapshot()
    assert after == read(PRIVATE/'after-activation-detail.json'), 'State changed after shutdown'
    native = 'Data/ReviewToday.store'
    strict = ['ZSOURCE','ZKNOWLEDGE','ZQUESTION','ZFSRSSTATE','ZREVIEWSESSION','ZREVIEWATTEMPT',
              'ZAGENTMESSAGE','ZKNOWLEDGEREFERENCE','ZSOURCEREFERENCE','ZAGENTRUN','ZSESSIONEVENTRECORD']
    assert all(before[native][table] == after[native][table] for table in strict)
    for a,b in zip(before[native]['ZLEARNINGTASK'],after[native]['ZLEARNINGTASK']):
        assert {k:v for k,v in a.items() if k not in ['ZUPDATEDAT','Z_OPT']} == {k:v for k,v in b.items() if k not in ['ZUPDATEDAT','Z_OPT']}
    for a,b in zip(before[native]['ZAGENTSESSION'],after[native]['ZAGENTSESSION']):
        assert {k:v for k,v in a.items() if k not in ['ZCHECKPOINTJSON','Z_OPT']} == {k:v for k,v in b.items() if k not in ['ZCHECKPOINTJSON','Z_OPT']}
    changes = read(PRIVATE/'changed-columns.json')
    assert set(changes[native]) == {'ZLEARNINGTASK','ZAGENTSESSION','Z_PRIMARYKEY'}
    service = 'agent-harness.sqlite3'
    assert set(changes[service]) == {'agent_capability_batches'}
    assert before[DATABASES[2]] == after[DATABASES[2]]
    old_batches = {r['batch_id']:r for r in before[service]['agent_capability_batches']}
    current_batches = {r['batch_id']:r for r in after[service]['agent_capability_batches']}
    assert all(current_batches[k] == v for k,v in old_batches.items())
    new_ids = set(current_batches)-set(old_batches)
    assert len(new_ids) == 1
    batch = json.loads(current_batches[new_ids.pop()]['payload'])
    assert batch['rounds'] == 1 and batch['status'] == 'finished' and len(batch['calls']) == 8
    q = read(PRIVATE/'activation/quota.json')
    assert q['closed'] and q['model_requests'] == 8 and q['web_operations'] == 0
    assert len(q['entries']) == 8 and all(e['dispatched'] and e['outcome']=='returned' for e in q['entries'])
    ids = {e['program_id'] for e in q['entries']}
    assert len(ids) == 8 and ids == {i for call in batch['calls'] for i in call['request_ids']}
    usage = [u for call in batch['calls'] for u in call['usage']]
    assert len(usage) == 8 and {u['request_id'] for u in usage} == ids
    assert all(len(e['usage']) == 1 for e in q['entries'])
    health = read(PRIVATE/'activation/health-final-live.json')
    assert all(v['status'] == 'ready' and v['next_probe_at'] is None for v in health['model_roles'].values())
    assert health['model_roles']['coach']['streaming'] == 'ready'
    assert health['model_roles']['coach']['strengths']['deep']['streaming'] == 'ready'
    installed = read(OUT/'installation.json')
    assert signature(DAILY) == installed['signature'] == read(OUT/'candidate.json')['signature']
    assert signature(Path(installed['previous'])) == read(OUT/'backup.json')['daily_signature']
    pins = read(OUT/'source-pins.json')
    assert all(digest((ROOT/name).read_bytes()) == value for name,value in pins.items())
    prior = read(ROOT/'docs/evidence/2026-10-21-status-presentation/setup.json')
    old_files = 0
    for directory,files in prior['protected_runtime_files'].items():
        for name,checksum in files.items():
            assert digest((Path(directory)/name).read_bytes()) == checksum
            old_files += 1
    assert digest(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)) == PROJECT_DIFF
    agent = (PRIVATE/'activation/native-agent.txt').read_text()
    library = (PRIVATE/'activation/native-library.txt').read_text()
    source = (PRIVATE/'activation/native-source.txt').read_text()
    assert '学习输入' in agent and '发送' in agent and '服务未能启动' not in agent
    assert '当前筛选总数 11' in library and '来源摘录' in source and 'Value: 0' in source
    logs = (PRIVATE/'activation/service.log').read_text()
    conflicts = len(re.findall(r'HTTP/1.1" 409',logs))
    assert conflicts == 82 and 'Application shutdown complete.' in logs
    observed = read(OUT/'sync-observation.json')
    assert observed['existed_before_install'] and observed['production_error'] == 'RT.SESSION.INVALID_ACTION'
    report = dict(status='UPDATED_ENTRY_AND_DATA_PASS_PREEXISTING_SYNC_ISSUE_OPEN',decision=257,
        actual_model_requests=8,actual_web_operations=0,new_probe_batches=1,new_probe_rounds=1,
        unique_request_ids=8,usage_receipts=8,
        reported_tokens={k:sum(u.get(k,0) or 0 for u in usage) for k in ['input_tokens','output_tokens','total_tokens','cached_input_tokens','reasoning_output_tokens']},
        all_roles_ready=True,coach_smart_and_deep_streaming_ready=True,
        daily_app_updated=True,daily_app_finally_closed=True,temporary_service_finally_closed=True,
        native_counts={t:len(after[native][t]) for t in ['ZKNOWLEDGE','ZAGENTMESSAGE','ZAGENTSESSION','ZFSRSSTATE']},
        native_strict_tables_unchanged=strict,learning_and_review_fields_preserved=True,
        previous_service_sessions_and_tasks_unchanged=True,previous_capability_batches_unchanged=True,
        database_integrity=integrity,changed_columns=changes,internal_history_counts=history,
        pins_unchanged=len(pins),old_runtime_files_unchanged=old_files,project_diff_sha256=PROJECT_DIFF,
        ui=dict(agent_entry=True,input_and_send_visible=True,no_blocking_banner=True,library_11=True,
                existing_detail_source_label=True,review_toggle_off=True,new_messages_sent=0,saves_clicked=0,
                appearance='light/current window',native_app_processes_observed=[25528,25715],
                quit_observation_reopened_window=True,additional_probe_after_reopen=0),
        stop_present=(PRIVATE/'activation/STOP').exists(),frozen_allowances_reused=False,
        open_issue=dict(kind='preexisting deletion outbox repeats invalid archive revision zero',http_409_count=conflicts,
                        reproduced_offline=True,daily_outbox_unchanged=True,data_cleanup_executed=False),
        not_verified=['new status query','new full learning chain','fresh managed-child startup','full VoiceOver','Rex experience'])
    write(OUT/'activation-result.json',report)
    write(PRIVATE/'activation/verification.json',report)
    print(json.dumps({k:report[k] for k in ['status','actual_model_requests','actual_web_operations','native_counts','reported_tokens','open_issue']},ensure_ascii=False))


if __name__ == '__main__':
    main()
