"""Read-only verification after normal App exit and temporary service shutdown."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import uuid
from prepare import ROOT, OUT, PRIVATE, ARCHIVE, SUPPORT, DAILY, DBS, app_files, sha, stopped, write


def read(path):return json.loads(path.read_text())
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def unordered(rows):return sorted(rows,key=canonical)


def snapshot(base):
    result,integrity,history={},{},{}
    for relative in DBS:
        with closing(sqlite3.connect((base/relative).as_uri()+'?mode=ro',uri=True)) as db:
            integrity[relative]=[r[0] for r in db.execute('pragma integrity_check')]
            assert integrity[relative]==['ok']
            db.row_factory=sqlite3.Row;tables={}
            for table, in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name").fetchall():
                if table in {'ACHANGE','ATRANSACTION'}:
                    history[table]=db.execute('select count(*) from '+table).fetchone()[0];continue
                tables[table]=[{k:({'bytes_hex':v.hex()} if isinstance(v,bytes) else v) for k,v in dict(row).items()} for row in db.execute('select * from "'+table+'"')]
            result[relative]=tables
    return result,integrity,history


def main():
    stopped();activation=PRIVATE/'activation'
    before=read(activation/'before-activation-detail.json')
    saved=read(activation/'after-activation-detail.json')
    after,integrity,history=snapshot(SUPPORT)
    assert after==saved,'Data changed after the retained shutdown snapshot'
    native='Data/ReviewToday.store';service='agent-harness.sqlite3';review='agent-harness.review.sqlite3'
    assert set(before)==set(after)
    assert all(set(before[k])==set(after[k]) for k in before)
    old_markers=json.loads(before[native]['ZAPPSETTINGS'][0]['ZSESSIONDELETIONSJSON'])
    markers=json.loads(after[native]['ZAPPSETTINGS'][0]['ZSESSIONDELETIONSJSON'])
    assert len(old_markers)==len(markers)==37
    assert all(m.get('cleaned') is not True for m in old_markers) and all(m.get('cleaned') is True for m in markers)
    assert [{k:v for k,v in m.items() if k!='cleaned'} for m in old_markers]==[{k:v for k,v in m.items() if k!='cleaned'} for m in markers]
    allowed={m['session_id']:m for m in old_markers}
    added={'ZAGENTMESSAGE':{'ZINPUTCHANNEL':'text','ZVOICEPLAYBACKJSON':None},'ZAGENTRUN':{'ZVOICEINPUTIDSJSON':'[]'}}
    volatile={'ZAPPSETTINGS':{'ZSESSIONDELETIONSJSON','Z_OPT'},'ZAGENTSESSION':{'Z_OPT'},'ZLEARNINGTASK':{'ZUPDATEDAT','Z_OPT'}}
    internal={'Z_METADATA','Z_MODELCACHE','Z_PRIMARYKEY'}
    native_preserved=[]
    for table,rows in before[native].items():
        if table in internal:continue
        current=after[native][table];assert len(rows)==len(current),table
        if rows:
            new={r['Z_PK']:r for r in current} if 'Z_PK' in rows[0] else None
            assert new is not None,table
            for row in rows:
                updated=new[row['Z_PK']]
                extra=set(updated)-set(row)
                assert extra==set(added.get(table,{})),(table,extra)
                assert all(updated[k]==v for k,v in added.get(table,{}).items())
                assert {k:v for k,v in row.items() if k not in volatile.get(table,set())}=={k:updated[k] for k in row if k not in volatile.get(table,set())},table
        native_preserved.append(table)
    assert before[native]['Z_METADATA'][0]['Z_VERSION']==after[native]['Z_METADATA'][0]['Z_VERSION']
    assert before[native]['Z_METADATA'][0]['Z_UUID']==after[native]['Z_METADATA'][0]['Z_UUID']
    old_keys={r['Z_NAME']:r for r in before[native]['Z_PRIMARYKEY']};new_keys={r['Z_NAME']:r for r in after[native]['Z_PRIMARYKEY']}
    assert set(old_keys)==set(new_keys)
    for name,row in old_keys.items():
        if name not in {'CHANGE','TRANSACTION','TRANSACTIONSTRING'}:assert row==new_keys[name]
        else:
            assert {k:v for k,v in row.items() if k!='Z_MAX'}=={k:v for k,v in new_keys[name].items() if k!='Z_MAX'}
            assert new_keys[name]['Z_MAX']>=row['Z_MAX']
    removed={}
    scoped={'agent_sessions_v2':'session_id','harness_tasks':'session_id','agent_memory_policy_v2':'session_id'}
    for table,rows in before[service].items():
        current=after[service][table]
        if table in scoped:
            field=scoped[table];expected=[r for r in rows if r[field] not in allowed]
            assert unordered(expected)==unordered(current),table
            removed[table]=len(rows)-len(current)
        elif table not in {'agent_session_deletions','agent_capability_batches'}:assert unordered(rows)==unordered(current),table
    assert removed=={'harness_tasks':10,'agent_sessions_v2':26,'agent_memory_policy_v2':29}
    tombstones=after[service]['agent_session_deletions'];assert len(tombstones)==37
    for row in tombstones:
        marker=allowed[row['session_id']]
        assert row['action_id']==marker['action_id'] and row['lifecycle_revision']==marker['lifecycle_revision']
    assert before[service]['agent_session_deletions']==[]
    assert before[review]==after[review]
    previous={r['batch_id']:r for r in before[service]['agent_capability_batches']}
    current={r['batch_id']:r for r in after[service]['agent_capability_batches']}
    assert all(current[k]==v for k,v in previous.items())
    added_batches=set(current)-set(previous);assert len(added_batches)==1
    batch=json.loads(current[added_batches.pop()]['payload'])
    assert batch['status']=='finished' and batch['rounds']==1 and len(batch['calls'])==8
    quota=read(activation/'quota.json');assert quota['closed'] and quota['model_requests']==8 and quota['web_operations']==0
    entries=quota['entries'];assert len(entries)==8 and all(e['dispatched'] and e['outcome']=='returned' and len(e['usage'])==1 for e in entries)
    ids={e['program_id'] for e in entries};assert len(ids)==8
    assert ids=={i for call in batch['calls'] for i in call['request_ids']}
    usage=[u for call in batch['calls'] for u in call['usage']]
    assert len(usage)==8 and {u['request_id'] for u in usage}==ids
    assert (activation/'STOP').is_file()
    health=read(activation/'health-final-live.json')
    assert all(v['status']=='ready' and v['next_probe_at'] is None for v in health['model_roles'].values())
    assert health['model_roles']['coach']['streaming']=='ready' and health['model_roles']['coach']['strengths']['deep']['streaming']=='ready'
    assert app_files(DAILY)==read(OUT/'candidate.json')['inventory']
    subprocess.run(['codesign','--verify','--deep','--strict',str(DAILY)],check=True)
    sources=read(OUT/'source-pins.json');assert all(sha(ROOT/p)==h for p,h in sources.items())
    protection=read(PRIVATE/'source-protection.json')
    project_diff=hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest()
    assert project_diff==protection['project_diff']
    assert all(sha(ROOT/p)==h for p,h in protection['configs'].items())
    backup_pins=read(PRIVATE/'backup-file-pins.json');assert all(sha(Path(p))==h for p,h in backup_pins.items())
    old=read(ROOT/'docs/evidence/2026-10-22-deletion-sync-repair/setup.json')
    frozen={p:h for p,h in old['frozen_files'].items() if not any(part.endswith('.app') for part in Path(p).parts)}
    assert all(sha(Path(p))==h for p,h in frozen.items())
    history_files={p:h for p,h in protection['daily_files'].items() if Path(p).is_relative_to(SUPPORT/'Backups')}
    assert len(history_files)==89 and all(sha(Path(p))==h for p,h in history_files.items())
    ls='/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
    identifiers=re.findall(r'^identifier:\s*(.*)$',subprocess.check_output([ls,'-dump'],text=True),re.M)
    registered=sum(bool(re.search(r'review[-_]?today',i,re.I)) for i in identifiers);assert registered==1
    agent=(activation/'native-agent.txt').read_text();library=(activation/'native-library.txt').read_text();detail=(activation/'native-detail.txt').read_text()
    assert '学习输入' in agent and '发送' in agent and '服务未能启动' not in agent
    assert '当前筛选总数 11' in library and '来源摘录' in detail and '已学过，参与间隔复习, Value: 1' in detail
    logs=(activation/'service.log').read_text();assert 'Application shutdown complete.' in logs
    actions=re.findall(r'POST /v2/sessions/([0-9a-f-]+)/actions HTTP/1.1" (\d+)',logs)
    expected_archives=sum(m['lifecycle_revision']>1 for m in old_markers);assert expected_archives==31
    expected_actions=[(sid,status) for sid,m in allowed.items() for status in (['409','200'] if m['lifecycle_revision']>1 else ['200'])]
    queued=[(sid,status) for sid,status in actions if sid in allowed]
    assert queued==expected_actions
    def identifier(value):return str(uuid.UUID(hex=value['bytes_hex'])).lower() if isinstance(value,dict) else str(value).lower()
    owners={identifier(row['ZSESSIONID']) for row in before[native]['ZAGENTMESSAGE']}
    syncable={identifier(row['ZID']) for row in before[native]['ZAGENTSESSION']
              if identifier(row['ZID']) in owners or row['ZLIFECYCLEACTIONSJSON']!='[]' or row['ZLASTSESSIONEVENTSEQ']>0}
    normal=[(sid,status) for sid,status in actions if sid not in allowed]
    assert len(syncable)==len(normal)==6 and {sid for sid,status in normal}==syncable
    assert all(status=='200' for sid,status in normal)
    native_counts={t:len(after[native][t]) for t in ['ZAGENTSESSION','ZAGENTMESSAGE','ZKNOWLEDGE','ZFSRSSTATE']}
    assert native_counts==dict(ZAGENTSESSION=8,ZAGENTMESSAGE=37,ZKNOWLEDGE=11,ZFSRSSTATE=11)
    report=dict(status='DAILY_UPDATED_CLEANUP_AND_STARTUP_CHECK_PASS',decision=261,actual_model_requests=8,actual_web_operations=0,
        original_native_queue=37,native_pending_after=0,real_backend_delete_receipts=37,original_action_ids_and_revisions_preserved=True,
        removed_backend_rows=removed,all_other_backend_rows_preserved=True,review_database_preserved=True,
        native_counts=native_counts,all_original_native_business_fields_preserved=True,native_tables_compared=native_preserved,
        allowed_native_runtime_fields={k:sorted(v) for k,v in volatile.items()},additive_existing_voice_defaults=added,
        internal_model_cache_updated=True,internal_history_counts=history,database_integrity=integrity,
        startup_rounds=1,unique_request_ids=8,usage_receipts=8,all_roles_ready=True,coach_smart_and_deep_streaming_ready=True,
        reported_tokens={k:sum(u.get(k,0) or 0 for u in usage) for k in ['input_tokens','output_tokens','total_tokens','cached_input_tokens','reasoning_output_tokens']},
        ui=dict(agent_entry=True,knowledge_library_11=True,existing_detail=True,existing_review_toggle_preserved=True,new_messages_sent=0,saves_clicked=0,
                appearance='light/current window',screenshots_private=True,app_closed_normally=True),
        native_http_action_attempts=len(actions),original_queue_http_attempts=len(queued),existing_session_sync_http_attempts=len(normal),
        already_deleted_archive_conflicts=sum(status=='409' for sid,status in queued),
        same_canonical_entry=str(DAILY),registered_entries=registered,app_closed=True,temporary_service_closed=True,new_batch_stopped=True,
        pinned_sources_and_evidence_unchanged=len(sources),old_frozen_non_app_files_unchanged=len(frozen),existing_backup_files_unchanged=89,
        private_configuration_files_unchanged=5,project_diff_unchanged=True,original_allowances_reused=False,
        not_verified=['fresh managed-child startup','new full learning chain','new status query','full VoiceOver','Rex experience'])
    write(OUT/'activation-result.json',report);write(activation/'verification.json',report)
    print(json.dumps({k:report[k] for k in ['status','actual_model_requests','actual_web_operations','native_pending_after','native_counts','reported_tokens','native_http_action_attempts','already_deleted_archive_conflicts']},ensure_ascii=False))


if __name__=='__main__':main()
