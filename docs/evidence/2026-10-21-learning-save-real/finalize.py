"""Verify stopped real batch, including the intended preservation assertions."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
def read(p): return json.loads(Path(p).read_text())
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def files(p): return {str(f.relative_to(p)):digest(f) for f in Path(p).rglob('*') if f.is_file()}


def main():
    setup=read(OUT/'setup.json'); directory=Path(setup['directory'])
    data=read(OUT/'after-status-query.json'); baseline=read(OUT/'before-input.json'); native=read(OUT/'native-disk-read.json')
    quota=read(directory/'quota.json'); entries=quota['entries']; rows=[json.loads(x) for x in (directory/'live-events.jsonl').read_text().splitlines()]
    assert (directory/'STOP').exists() and quota['model_requests']==22 and quota['web_operations']==0
    assert len(entries)==22 and all(e['kind']=='model' and e['dispatched'] and len(e['usage'])==1 for e in entries)
    ids={e['program_id'] for e in entries}; assert len(ids)==22
    assert all(e['usage'][0]['request_id']==e['program_id'] for e in entries)
    assert len([r for r in rows if r['type']=='sdk_wire_request'])==22
    assert len([r for r in rows if r['type']=='sdk_wire_response'])==22
    assert all(r['status']==200 for r in rows if r['type']=='sdk_wire_response')
    batches=read(OUT/'capability-ledger.json')
    fresh=[b for b in batches if any(set(c['request_ids']) & ids for c in b['calls'])]
    assert len(fresh)==1 and fresh[0]['status']=='finished' and fresh[0]['rounds']==1 and len(fresh[0]['calls'])==8
    probe_ids={i for c in fresh[0]['calls'] for i in c['request_ids']}; assert len(probe_ids)==8
    new_runs={k:r for k,r in data['runs'].items() if k not in baseline['runs']}
    assert len(new_runs)==4 and all(r['status']=='completed' for r in new_runs.values())
    calls=[c for r in new_runs.values() for c in r['model_calls']]
    run_ids={i for c in calls for i in c['request_ids']}
    assert len(run_ids)==14 and not run_ids & probe_ids and run_ids|probe_ids==ids
    assert sum(c['transport_requests'] for c in calls)==14
    assert all(c['usage_state']=='reported' for c in calls)
    totals={k:sum(e['usage'][0].get(k,0) or 0 for e in entries) for k in ('input_tokens','output_tokens','total_tokens')}
    assert totals['total_tokens']==totals['input_tokens']+totals['output_tokens']
    assert native['knowledge_count']==5 and native['source_count']==1 and native['fsrs_count']==5
    assert len(native['messages'])==17 and len(native['runs'])==9 and all(c['review'] is False for c in native['cards'])
    offer=next(iter(data['capture_offers'].values())); assert offer['status']=='saved' and offer['version']==4
    task=data['tasks'][offer['save_task_id']]
    assert task['status']=='completed' and any(e['node']=='mac_ack' for e in task['events'])
    assert {c['id'] for c in native['cards']}==set(offer['knowledge_ids'])=={c['id'] for c in task['memory_package']['knowledge']}
    assert {c['id']:c['title'] for c in native['cards']}=={c['id']:c['title'] for c in task['memory_package']['knowledge']}
    assert all(c['origin_task']==task['task_id'] and c['origin_session']==setup['session_id'] for c in native['cards'])
    messages={m['id']:m for m in native['messages']}
    assert {r['id']:r['status'] for r in native['runs']}=={rid:r['status'] for rid,r in data['runs'].items()}
    for m in data['messages']:
        assert messages[m['message_id']]['text']==m['content'] and messages[m['message_id']]['run_id']==m['run_id']
    assert len(data['messages'])==16
    tid=baseline['active_task_id']; before_return=read(OUT/'after-return-rag.json')
    assert data['active_task_id']==tid and data['tasks'][tid]==before_return['tasks'][tid]
    assert data['tasks'][tid]['context']['learning_plan']==baseline['tasks'][tid]['context']['learning_plan']
    assert data['tasks'][tid]['context']['understanding_by_lesson']==baseline['tasks'][tid]['context']['understanding_by_lesson']
    assert data['tasks'][tid]['context']['sources']==baseline['tasks'][tid]['context']['sources']
    for rid,r in baseline['runs'].items(): assert data['runs'][rid]==r
    for m in baseline['messages']: assert next(n for n in data['messages'] if n['message_id']==m['message_id'])==m
    diagnosis=read(OUT/'status-diagnosis.json'); assert diagnosis['actual_stage']=='scope_unconfirmed'
    assert data['messages'][-1]['content']==diagnosis['actual_reply'] and '5' not in diagnosis['actual_reply']
    assert all((OUT/f'native-detail-{i}.txt').exists() for i in range(1,6))
    for i in range(1,6): assert '已学过，参与间隔复习, Value: 0' in (OUT/f'native-detail-{i}.txt').read_text()
    protected={}
    for group in ('protected_fingerprints','protected_archives'):
        for name,sha in setup[group].items(): assert digest(ROOT/name)==sha,name
        protected[group]=len(setup[group])
    assert files(Path(setup['pending_directory']))==setup['pending_files_before']
    old=Path(setup['old_EVAL03_directory'])
    for name,sha in setup['old_EVAL03_sha256'].items(): assert digest(old/name)==sha
    assert hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest()==setup['project_diff_sha256']
    assert files(Path(setup['native_app']))==setup['prior_app_files']
    assert read(OUT/'cleanup.json')['prior_qa_app_restored']
    for name in ('authorization.json','quota.json','STOP','live-events.jsonl','native-recheck-events.jsonl'):
        shutil.copy2(directory/name,OUT/name)
    result=dict(outcome='STOPPED_ON_SAVED_STATUS_QUERY_FAILURE',decision=249,actual_model_requests=22,
        model_limit=24,unused_model_allowance_frozen=2,actual_provider_web_operations=0,web_limit=16,
        stop=True,reported_usage_requests=22,unknown_usage_requests=0,reported_tokens=totals,
        startup_probes=8,startup_rounds=1,new_run_requests=[4,3,6,1],sdk_wire_attempts=22,
        generic_schema_failures_repaired=2,extraction_semantic_repair=1,
        model_outputs_substituted=False,old_capability_state_reused=False,
        independent_question_gate='PASS',original_source_return_gate='PASS_WITH_PREVIEW_REFRESH_OBSERVATION',
        native_save_gate='PASS',detail_gate='PASS_FIVE_CARDS',saved_cards=5,source_count=1,
        status_query_gate='FAIL_SCOPE_UNCONFIRMED_DESPITE_MATCHING_RECEIPT',learning_progress_preserved=True,
        review_disabled_all_cards=True,fsrs_rows=5,fsrs_rows_do_not_imply_enrollment=True,
        frozen_save_version=4,conditional_web_verification_exercised=False,
        native_messages=17,service_messages=16,runs=9,fresh_process_disk_read=True,
        old_failed_run_and_history_preserved=True,protected=protected,old_EVAL03_stop_and_count_preserved=True,
        pending_preparation_files_unchanged=12,user_project_difference_preserved=True,
        native_and_service_closed=True,prior_qa_app_restored=True,daily_app_replaced=False,
        production_modified=False,full_uninterrupted_eight_step_acceptance=False,user_experience_accepted=False,
        next_step='Align a narrow query-object binding repair; first verify offline using this retained real data. No more live calls authorized by this completed batch.')
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
