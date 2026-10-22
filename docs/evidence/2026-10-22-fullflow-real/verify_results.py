"""Check retained real outputs and disk identities without network or models."""
import collections,importlib.util,json,sqlite3,sys
from copy import deepcopy
from contextlib import closing
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent;P=ROOT/'output/fullflow-real-2026-10-22';R=Path('/private/tmp/review-today-fullflow-i9njdmrd.noindex')
def read(p):return json.loads(p.read_text())
def forbidden(event,args):
    if event=='socket.connect':raise AssertionError('No network in final verification')
sys.addaudithook(forbidden)
q=read(P/'quota.json');stop=read(P/'STOP');disk=read(P/'native-disk-read.json');snap=read(P/'gates/10-failed-return-final-snapshot.json');cp=json.loads(snap['checkpoint_json'])['checkpoint']
events=[json.loads(l) for l in (P/'live-events.jsonl').read_text().splitlines()]
starts=[d for d in events if d['type']=='semantic_start'];outputs=[d for d in events if d['type']=='semantic_output'];wire=[d for d in events if d['type']=='sdk_wire_request'];responses=[d for d in events if d['type']=='sdk_wire_response']
assert len(starts)==len(outputs)==len(wire)==len(responses)==q['model_requests']==25
assert {d['call_id'] for d in starts}=={d['call_id'] for d in outputs}=={d['call_id'] for d in wire}=={d['call_id'] for d in responses}
assert all(d['status']==200 for d in responses)
assert q['web_operations']==0 and not any(d['type'].startswith('web_') for d in events)
assert all(e['dispatched'] and e['outcome']=='returned' and len(e['usage'])==1 for e in q['entries'])
u=[e['usage'][0] for e in q['entries']];assert len({e['program_id'] for e in q['entries']})==len({x['request_id'] for x in u})==25
assert {e['program_id'] for e in q['entries']}=={x['request_id'] for x in u}
with closing(sqlite3.connect((P/'disk-final/checkpoint.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
    stored=read_payload=json.loads(db.execute('select payload from agent_sessions_v2').fetchone()[0]);task=json.loads(db.execute('select payload from harness_tasks').fetchone()[0])
assert len(disk['messages'])==len(stored['messages'])==len(snap['messages'])==12
assert len(disk['runs'])==len(stored['runs'])==6 and len(disk['sessions'])==1
native={m['id'].lower():(m['role'],m['text'],m['run_id'].lower()) for m in disk['messages']}
backend={m['message_id']:({'coach':'assistant'}.get(m['role'],m['role']),m['content'],m['run_id']) for m in stored['messages']}
assert native==backend
assert {x['id'].lower():x['status'] for x in disk['runs']}=={k:v['status'] for k,v in stored['runs'].items()}
assert all(m['response_state']=='complete' for m in disk['messages']) and all(v['status']=='completed' for v in stored['runs'].values())
assert disk['knowledge_count']==disk['source_count']==disk['fsrs_count']==0
assert not stored['pending'] and not stored['draft'] and stored['capture_offers']==cp['capture_offers']
assert disk['sessions'][0]['cursor']==stored['last_acked_seq']
assert sum(c['transport_requests'] for r in stored['runs'].values() for c in r['model_calls'])==17
assert len([s for s in starts if s['schema']=='Probe'])==8
pre=read(P/'gates/08-independent-question-snapshot.json');before=json.loads(pre['checkpoint_json'])['checkpoint'];old=next(iter(before['tasks'].values()));now=task
assert old['context']['learning_plan']['current_step_id']!=now['context']['learning_plan']['current_step_id']
assert now['context']['learning_plan']['current_step_id']==now['context']['learning_plan']['steps'][1]['id']
assert now['context']['learning_plan']['steps'][1]['state']=='explained'
intent=[d for d in outputs if d['schema']=='IntentDecision'][-1]['output'];assert intent['intents']==['continue'] and '不进入下一节' in intent['rationale']
spec=importlib.util.spec_from_file_location('learning_progress',ROOT/'agent-service/agent_service/learning_progress.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
copy=deepcopy(old);finished=module.advance(copy)
assert not finished and copy['context']['learning_plan']['current_step_id']==now['context']['learning_plan']['current_step_id']
assert old==next(iter(before['tasks'].values())) # replay only copied in-memory task
assert (R/'quota.json').read_bytes()==(P/'quota.json').read_bytes() and (R/'STOP').read_bytes()==(P/'STOP').read_bytes()
report=dict(status='EVIDENCE_VERIFIED_FAILED_GATE',model_requests=25,web_operations=0,reported_input_tokens=sum(x['input_tokens'] for x in u),reported_output_tokens=sum(x['output_tokens'] for x in u),reported_total_tokens=sum(x['total_tokens'] for x in u),unique_requests_and_usage=25,sdk_wire_200=25,logical_outputs=25,startup_requests=8,learning_requests=17,network_free_replay=True,native_messages=12,native_runs=6,native_sessions=1,native_cards=0,native_sources=0,native_fsrs=0,native_service_identity_text_and_run_status_match=True,cursor_ack_match=True,actual_return_intent='continue',old_step=old['context']['learning_plan']['steps'][0]['title'],new_step=now['context']['learning_plan']['steps'][1]['title'],advance_branch_reproduced_from_real_task=True,knowledge_offer_version_before_return=2,knowledge_offer_version_after_return=3,remaining_models_frozen=15,remaining_web_frozen=16,save_details_status_progress_not_run=True)
(OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
