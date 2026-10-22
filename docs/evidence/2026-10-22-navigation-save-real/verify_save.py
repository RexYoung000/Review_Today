"""Verify the observed native durable receipt and its matching saved offer."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
PRIVATE=ROOT/'output/navigation-save-real-2026-10-22/gates'
def read(p):return json.loads(p.read_text())
def main():
    native=read(PRIVATE/'04-save-snapshot.json');data=json.loads(native['checkpoint_json'])['checkpoint']
    before=json.loads(read(PRIVATE/'03-review-snapshot.json')['checkpoint_json'])['checkpoint']
    offer=next(iter(data['capture_offers'].values()));old=before['capture_offers'][offer['id']]
    assert offer['status']=='saved' and offer['version']==offer['preview_version']==old['version']==3
    for key in ['title','scope_summary','preview_points','preview_summary','source_key']:
        assert offer[key]==old[key],key
    cards=native['knowledge'];ids={v['id'].lower() for v in cards};assert len(cards)==len(ids)>0 and ids==set(offer['knowledge_ids'])
    assert all(not v['review'] and v['origin_session'].lower()==data['session_id'] and v['origin_task'].lower()==offer['save_task_id'] for v in cards)
    assert all(any(v['evidence'] in source['raw_text'] for source in native['sources']) for v in cards)
    assert all('Python' not in v['explanation']+v['evidence'] for v in cards)
    task=data['tasks'][offer['resume_task_id']];original=before['tasks'][task['task_id']]
    for key in ['learning_plan','check_question','check_binding','last_lesson','sources','understanding','lesson_index','practice']:
        assert task['context'].get(key)==original['context'].get(key),key
    assert data['tasks'][offer['save_task_id']]['status']=='completed'
    runtime=Path(read(OUT/'setup.json')['directory']);events=[json.loads(l) for l in (runtime/'native-recheck-events.jsonl').read_text().splitlines()]
    receipts=[e for e in events if e['phase']=='durable_receipt'];assert len(receipts)==1
    ack=receipts[0];assert ack['receipt_already_durable'] and ack['receipt_task'].lower()==offer['save_task_id'] and {v.lower() for v in ack['receipt_card_ids']}==ids
    q=read(PRIVATE/'04-save-quota.json');result=dict(gate='native_save',status='PASS',models=q['model_requests'],web=q['web_operations'],saved_cards=len(cards),
        exact_click_version=3,single_matching_native_durable_receipt=True,all_card_evidence_in_native_source=True,review_disabled=True,learning_progress_unchanged=True,
        actual_titles=[v['title'] for v in cards],save_task_id=offer['save_task_id'])
    gates=read(OUT/'gates.json');assert not any(g['gate']=='native_save' for g in gates);gates.append(result)
    (OUT/'gates.json').write_text(json.dumps(gates,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
