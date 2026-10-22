"""Check already observed details, exact save-result query and learning progress."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
PRIVATE=ROOT/'output/navigation-save-real-2026-10-22/gates'
def read(p):return json.loads(p.read_text())
def main():
    before=read(PRIVATE/'04-save-snapshot.json');native=read(PRIVATE/'06-status-snapshot.json')
    old=json.loads(before['checkpoint_json'])['checkpoint'];data=json.loads(native['checkpoint_json'])['checkpoint']
    offer=next(iter(data['capture_offers'].values()));task=data['tasks'][offer['resume_task_id']]
    assert data['capture_offers']==old['capture_offers']
    assert task['context']['learning_plan']==old['tasks'][task['task_id']]['context']['learning_plan']
    assert {v['id']:v for v in native['knowledge']}=={v['id']:v for v in before['knowledge']}
    assert native['sources']==before['sources'] and all(not v['review'] for v in native['knowledge'])
    new=[r for k,r in data['runs'].items() if k not in old['runs']];assert len(new)==1 and new[0]['status']=='completed'
    operation=new[0]['intent']['knowledge_save_operation'];assert operation['task_id']==offer['save_task_id'] and operation['version']==3
    reply=data['messages'][-1]['content'];titles={v['title'] for v in native['knowledge']}
    assert f'写入 {len(titles)} 张知识卡' in reply and {s.strip() for s in re.findall(r'^\d+\.\s+(.+)$',reply,re.M)}==titles
    runtime=Path(read(OUT/'setup.json')['directory']);events=[json.loads(l) for l in (runtime/'native-recheck-events.jsonl').read_text().splitlines()]
    viewed={e['selected_knowledge'].lower() for e in events if e.get('show_library') and e.get('selected_knowledge')}
    assert viewed==set(offer['knowledge_ids']) and len([e for e in events if e['phase']=='durable_receipt'])==1
    for index in range(1,len(titles)+1):
        ax=(PRIVATE/f'05-detail-{index}.txt').read_text();assert '来源摘录' in ax and 'Value: 0' in ax and '主问题' in ax and '详解' in ax
    q=read(PRIVATE/'06-status-quota.json');result=dict(gate='details_status_progress',status='PASS',models=q['model_requests'],web=q['web_operations'],
        all_actual_details_and_source_excerpts_opened=len(titles),save_query_matches_operation_version_and_real_receipt=True,
        exact_actual_names_and_count=True,learning_plan_unchanged=True,review_disabled=True,saved_cards_and_sources_unchanged=True,reply=reply)
    gates=read(OUT/'gates.json');assert not any(g['gate']==result['gate'] for g in gates);gates.append(result)
    (OUT/'gates.json').write_text(json.dumps(gates,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
