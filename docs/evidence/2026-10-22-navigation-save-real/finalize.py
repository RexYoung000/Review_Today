"""Archive this closed real run and verify data/usage/protection. Never launch UI."""
from contextlib import closing
import json,re,shutil,sqlite3,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent;PRIVATE=ROOT/'output/navigation-save-real-2026-10-22'
sys.path.insert(0,str(ROOT/'docs/evidence/2026-10-22-navigation-save-preflight'))
import common as prep
def read(p):return json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def check_protection(state):
    # Preserve the original 240-file baseline; a missing file never becomes PASS.
    missing=[];changed=[];matched=0
    for name,expected in state['old_frozen_files'].items():
        path=Path(name)
        if not path.is_file():missing.append(name)
        elif prep.sha(path)!=expected:changed.append(name)
        else:matched+=1
    first=read(PRIVATE/'frozen-deviation.json')
    assert set(missing)=={v['path'] for v in first if v['status']=='missing'} and not changed
    other=dict(daily_files_unchanged=prep.files(prep.SUPPORT)==state['daily_files'],daily_app_unchanged=prep.app_files(prep.DAILY)==state['daily_app_inventory'],
        previous_batch_unchanged=all(prep.sha(Path(p))==h for p,h in state['previous_batch_files'].items()),
        source_config_unchanged=all(prep.sha(ROOT/p)==h for p,h in state['protected_fingerprints'].items()),
        user_project_unchanged=prep.sha(ROOT/'Review_Today.xcodeproj/project.pbxproj')==state['project_file_sha256'])
    for key in ['original_module_files','original_support_files','owned_support_files']:
        other[key+'_unchanged']=all(prep.sha(Path(p))==h for p,h in state[key].items())
    assert all(other.values()),other
    prep.stopped()
    report=dict(status='INCOMPLETE_OLD_TEMP_FILES_MISSING',complete=False,expected_old_files=240,matched_old_files=matched,missing_old_files=missing,changed_old_files=changed,
        original_baseline_preserved=True,missing_files_not_recreated=True,cause_not_established=True,other_protection_checks=other)
    assert matched==229 and len(missing)==11
    write(OUT/'protection.json',report)
    return report
def main():
    state=read(prep.OUT/'setup.json');runtime=Path(state['directory']);app=Path(state['native_app'])
    assert (runtime/'STOP').exists() and not (runtime/'HOLD').exists()
    assert subprocess.run(['pgrep','-x','NavigationSaveQA'],capture_output=True).returncode==1
    assert not subprocess.run(['lsof','-nP','-iTCP:'+str(state['port']),'-sTCP:LISTEN'],capture_output=True).stdout
    quota=read(runtime/'quota.json');assert (quota['model_requests'],quota['web_operations'])==(23,0)
    protection=check_protection(state)
    assert prep.sha(Path(state['native_zip']))==state['native_zip_sha256']
    if app.exists():
        assert prep.app_files(app)==state['native_bundle_inventory']
        subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
        unreg=subprocess.run([prep.LS,'-u',str(app)],capture_output=True,text=True);assert unreg.returncode in [0,1]
        write(PRIVATE/'targeted-unregister.json',dict(path=str(app),returncode=unreg.returncode,output=unreg.stdout+unreg.stderr,exact_signed_inventory_matched=True))
        # Recovery already exists as the exact same signed ZIP, verified above.
        shutil.rmtree(app)
    else:
        # Resume collection after a collector assertion; do not restore/relaunch.
        unregister=read(PRIVATE/'targeted-unregister.json');assert unregister['path']==str(app) and unregister['returncode'] in [0,1]
    for name in ['authorization.json','quota.json','STOP','live-events.jsonl','native-recheck-events.jsonl','native-disk-read.json']:
        if (PRIVATE/name).exists():assert (PRIVATE/name).read_bytes()==(runtime/name).read_bytes(),name
        else:shutil.copy2(runtime/name,PRIVATE/name)
    shadow=PRIVATE/'disk-final'
    if not shadow.exists():
        shadow.mkdir()
        for pattern in ['app.store*','checkpoint.sqlite3*','review.sqlite3*']:
            for path in runtime.glob(pattern):
                if path.is_file():shutil.copy2(path,shadow/path.name)
    else:
        # Existing immutable main DB copies are reused, never overwritten.
        for name in ['app.store','checkpoint.sqlite3']:assert prep.sha(shadow/name)==prep.sha(runtime/name),name
    with closing(sqlite3.connect((shadow/'checkpoint.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        assert db.execute('pragma quick_check').fetchall()==[('ok',)]
        stored=read_payload=json.loads(db.execute('select payload from agent_sessions_v2 where session_id=?',(state['session_id'],)).fetchone()[0])
        tasks={row[0]:json.loads(row[1]) for row in db.execute('select task_id,payload from harness_tasks where session_id=?',(state['session_id'],))}
        capability=[json.loads(p) for p, in db.execute('select payload from agent_capability_batches')]
    with closing(sqlite3.connect((shadow/'app.store').as_uri()+'?mode=ro',uri=True)) as db:
        assert db.execute('pragma quick_check').fetchall()==[('ok',)]
        counts={t:db.execute('select count(*) from '+t).fetchone()[0] for t in ['ZKNOWLEDGE','ZSOURCE','ZAGENTMESSAGE','ZLEARNINGTASK','ZAGENTRUN','ZAGENTSESSION','ZFSRSSTATE']}
    disk=read(PRIVATE/'native-disk-read.json');snap=read(PRIVATE/'gates/07-advance-snapshot.json');checkpoint=json.loads(snap['checkpoint_json'])['checkpoint']
    assert len(disk['messages'])==len(stored['messages'])==len(snap['messages'])==21
    assert len(disk['runs'])==len(stored['runs'])==11 and len(disk['sessions'])==1 and len(tasks)==2
    assert (disk['knowledge_count'],disk['source_count'],disk['fsrs_count'])==(5,1,5)
    assert counts==dict(ZKNOWLEDGE=5,ZSOURCE=1,ZAGENTMESSAGE=21,ZLEARNINGTASK=2,ZAGENTRUN=11,ZAGENTSESSION=1,ZFSRSSTATE=5)
    native={m['id'].lower():(m['role'],m['text'],m['run_id'].lower()) for m in disk['messages']}
    service={m['message_id']:({'coach':'assistant'}.get(m['role'],m['role']),m['content'],m['run_id']) for m in stored['messages']};assert native==service
    assert {r['id'].lower():r['status'] for r in disk['runs']}=={k:v['status'] for k,v in stored['runs'].items()}
    assert all(r['status']=='completed' for r in stored['runs'].values()) and all(m['response_state']=='complete' for m in disk['messages'])
    assert disk['sessions'][0]['cursor']==stored['last_acked_seq'] and stored['capture_offers']==checkpoint['capture_offers']
    bookkeeping=[]
    assert set(tasks)==set(checkpoint['tasks'])
    for identity,task_row in tasks.items():
        observed=checkpoint['tasks'][identity]
        if task_row==observed:continue
        assert identity==next(iter(stored['capture_offers'].values()))['resume_task_id']
        assert {k for k in task_row if task_row[k]!=observed[k]}=={'last_acked_seq','updated_at'}
        assert task_row['last_acked_seq']==observed['last_acked_seq']+1 and task_row['updated_at']>=observed['updated_at']
        bookkeeping.append(dict(task_id=identity,last_acked_seq_before=observed['last_acked_seq'],last_acked_seq_after=task_row['last_acked_seq'],
            updated_at_before=observed['updated_at'],updated_at_after=task_row['updated_at'],reason='Final native acknowledgement arrived after manual snapshot; all other task fields identical'))
    write(OUT/'bookkeeping-differences.json',bookkeeping)
    cards={v['id'].lower():v for v in disk['cards']};saved={v['id'].lower():v for v in snap['knowledge']};assert set(cards)==set(saved)
    for identity,card in cards.items():
        for key in ['title','explanation','evidence','review','origin_task','origin_session']:
            assert card[key].lower()==saved[identity][key].lower() if isinstance(card[key],str) else card[key]==saved[identity][key],(identity,key)
        assert not card['review']
    offer=next(iter(stored['capture_offers'].values()));assert offer['status']=='saved' and offer['version']==3 and set(offer['knowledge_ids'])==set(cards)
    task=tasks[offer['resume_task_id']];plan=task['context']['learning_plan'];assert plan['current_step_id']==state['next_step_id']
    assert plan['steps'][1]['understanding']==plan['steps'][2]['understanding']=='unknown'
    events=[json.loads(l) for l in (PRIVATE/'live-events.jsonl').read_text().splitlines()]
    wires=[e for e in events if e['type']=='sdk_wire_request'];responses=[e for e in events if e['type']=='sdk_wire_response']
    starts=[e for e in events if e['type']=='semantic_start'];outputs=[e for e in events if e['type']=='semantic_output'];errors=[e for e in events if e['type']=='semantic_error']
    assert len(wires)==len(responses)==len(starts)==23 and len(outputs)==22 and len(errors)==1 and errors[0]['error_code']=='RT.MODEL.SCHEMA'
    assert all(e['status']==200 for e in responses) and not any(e['type'].startswith('web_') for e in events)
    assert len(quota['entries'])==23 and all(e['dispatched'] and len(e['usage'])==1 for e in quota['entries'])
    assert sum(e['outcome']=='returned' for e in quota['entries'])==22 and sum(e['outcome']=='failed_or_cancelled' for e in quota['entries'])==1
    usages=[e['usage'][0] for e in quota['entries']];identities={e['program_id'] for e in quota['entries']}
    assert len(identities)==23 and identities=={u['request_id'] for u in usages}
    fresh=[b for b in capability if b['batch_id'] not in state['old_capability_batch_ids']];assert len(fresh)==1
    base=read(ROOT/'output/navigation-save-preflight-2026-10-22/starting-state.json')
    new_runs=[r for k,r in stored['runs'].items() if k not in base['runs']]
    tracked=[c for b in fresh for c in b['calls']]+[c for r in new_runs for c in r.get('model_calls',[])]
    assert sum(c['transport_requests'] for c in tracked)==23
    assert {v for c in tracked for v in c['request_ids']}==identities
    native_events=[json.loads(l) for l in (PRIVATE/'native-recheck-events.jsonl').read_text().splitlines()]
    receipts=[e for e in native_events if e['phase']=='durable_receipt'];assert len(receipts)==1 and receipts[0]['receipt_already_durable']
    assert {v.lower() for v in receipts[0]['receipt_card_ids']}==set(cards) and receipts[0]['receipt_task'].lower()==offer['save_task_id']
    viewed={e['selected_knowledge'].lower() for e in native_events if e.get('show_library') and e.get('selected_knowledge')};assert viewed==set(cards)
    protection=check_protection(state)
    identifiers=re.findall(r'^identifier:\s*(.*)$',subprocess.check_output([prep.LS,'-dump'],text=True),re.M)
    registered=sum(bool(re.search(r'review[-_]?today',v,re.I)) for v in identifiers);assert registered==1
    spotlight=subprocess.check_output(['mdfind',"kMDItemContentType == 'com.apple.application-bundle' && kMDItemCFBundleIdentifier == 'Rex.Review-Today'"],text=True).splitlines();assert spotlight==[str(prep.DAILY)]
    assert (runtime/'quota.json').read_bytes()==(PRIVATE/'quota.json').read_bytes()
    gates=read(OUT/'gates.json');assert len(gates)==6 and all(g['status']=='PASS' for g in gates)
    gates.append(dict(gate='disk_readback',status='PASS',models=23,web=0,native_messages=21,native_runs=11,native_tasks=2,native_cards=5,native_sources=1,native_fsrs=5,cursor_ack_match=True))
    gates.append(dict(gate='final_protection',status='INCOMPLETE',reason='11 historical tmp files missing; 229 matched; original baseline retained',models=23,web=0));write(OUT/'gates.json',gates)
    result=dict(status='DIRECTED_FLOW_VERIFIED_PROTECTION_INCOMPLETE_STOP',decision=264,model_requests=23,web_operations=0,
        reported_input_tokens=sum(u['input_tokens'] for u in usages),reported_output_tokens=sum(u['output_tokens'] for u in usages),reported_total_tokens=sum(u['total_tokens'] for u in usages),
        sdk_wire_200=23,logical_outputs=22,one_schema_error_and_existing_automatic_repair=True,unique_requests_and_usage=23,startup_requests=8,new_learning_save_status_requests=15,
        functional_gates_passed=7,final_protection_complete=False,native_messages=21,native_runs=11,native_tasks=2,native_sessions=1,native_cards=5,native_sources=1,native_fsrs=5,
        native_service_identity_content_status_match=True,cursor_ack_match=True,current_step_index=3,prior_step_not_certified=True,review_disabled=True,
        saved_offer_version=3,single_matching_native_durable_receipt=True,all_five_details_opened=True,
        remaining_models_frozen=9,remaining_web_frozen=16,old_frozen_files_expected=240,old_frozen_files_matched=229,old_frozen_files_missing=11,previous_batch_files_unchanged=len(state['previous_batch_files']),
        daily_files_unchanged=len(state['daily_files']),source_config_execution_pins_unchanged=len(state['protected_fingerprints']),daily_app_unchanged=True,original_modules_unchanged=True,user_project_diff_unchanged=True,
        qa_and_service_closed=True,qa_raw_app_removed=True,same_verified_signed_archive_reused=True,registered_entries=registered,spotlight_paths=spotlight,
        new_memory_selection_observed=True,web_verification_branch_not_exercised=True,uninterrupted_empty_start_acceptance=False,daily_app_not_loaded_with_263=True,m1_and_rex_experience_open=True)
    write(OUT/'verification.json',result)
    setup=read(OUT/'setup.json');setup.update(status='DIRECTED_FLOW_VERIFIED_PROTECTION_INCOMPLETE_STOP',actual_model_requests=23,actual_web_operations=0,qa_closed=True,service_closed=True);write(OUT/'setup.json',setup)
    write(OUT/'cleanup.json',dict(raw_qa_removed=True,archive=state['native_zip'],archive_sha256=state['native_zip_sha256'],running_bundle_matched_prepared_signed_archive=True,service_closed=True,registered_entries=registered,spotlight_paths=spotlight))
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
