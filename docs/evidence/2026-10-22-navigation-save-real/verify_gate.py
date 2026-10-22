"""Assert captured real states only; no model, network or runtime mutations."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
PRIVATE=ROOT/'output/navigation-save-real-2026-10-22/gates'
def read(p):return json.loads(p.read_text())
def main():
    name=sys.argv[1];native=read(PRIVATE/(name+'-snapshot.json'));data=json.loads(native['checkpoint_json'])['checkpoint'];q=read(PRIVATE/(name+'-quota.json'))
    if name=='02-independent':before=read(ROOT/'output/navigation-save-preflight-2026-10-22/starting-state.json')
    elif name=='03-review':before=json.loads(read(PRIVATE/'02-independent-snapshot.json')['checkpoint_json'])['checkpoint']
    else:raise ValueError('Only the two fixed invariant gates are supported')
    old=before['tasks'][before['active_task_id']];task=data['tasks'][data['active_task_id']]
    assert task['task_id']==old['task_id'] and data['active_task_id']==before['active_task_id']
    for key in ['learning_plan','check_question','check_binding','last_lesson','sources','understanding','lesson_index','practice','goal_ownership','memory_references']:
        assert task['context'].get(key)==old['context'].get(key),key
    assert data['capture_offers']==before['capture_offers'],'Entire invitation changed'
    assert data['pending'] is None and data['draft'] is None and native['knowledge_count']==0
    assert set(data['tasks'])==set(before['tasks']) and data['messages'][:len(before['messages'])]==before['messages']
    assert len(data['messages'])==len(before['messages'])+2 and len(data['runs'])==len(before['runs'])+1
    new_runs=[r for k,r in data['runs'].items() if k not in before['runs']];assert len(new_runs)==1 and new_runs[0]['status']=='completed'
    if name=='03-review':
        intent=new_runs[0]['intent'];assert 'continue' not in intent['intents']
        assert task['context']['learning_plan']['current_step_id']=='aa861650-0d14-43b6-9aa2-b427786f370e'
    result=dict(gate='independent_question' if name=='02-independent' else 'return_review',status='PASS',models=q['model_requests'],web=q['web_operations'],
        task_step_check_sources_and_understanding_unchanged=True,entire_v3_invitation_unchanged=True,history_preserved=True,no_save=True,new_run_id=new_runs[0]['run_id'])
    gates=read(OUT/'gates.json');assert not any(r['gate']==result['gate'] for r in gates),'Do not overwrite a gate result'
    gates.append(result);(OUT/'gates.json').write_text(json.dumps(gates,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
