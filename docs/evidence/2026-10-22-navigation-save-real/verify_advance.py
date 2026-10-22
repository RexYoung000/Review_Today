"""Verify the captured explicit next-step decision without invoking anything."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent;PRIVATE=ROOT/'output/navigation-save-real-2026-10-22/gates'
def read(p):return json.loads(p.read_text())
def main():
    native=read(PRIVATE/'07-advance-snapshot.json');prior=read(PRIVATE/'06-status-snapshot.json')
    data=json.loads(native['checkpoint_json'])['checkpoint'];before=json.loads(prior['checkpoint_json'])['checkpoint']
    task=data['tasks'][before['active_task_id']];old=before['tasks'][task['task_id']]
    plan=task['context']['learning_plan'];original=old['context']['learning_plan']
    assert plan['id']==original['id'] and plan['version']==original['version']==1
    assert original['current_step_id']==original['steps'][1]['id'] and plan['current_step_id']==original['steps'][2]['id']
    assert [v['id'] for v in plan['steps']]==[v['id'] for v in original['steps']]
    for index in [0,1,3]:assert plan['steps'][index]==original['steps'][index],index
    assert plan['steps'][2]['state']=='explained' and plan['steps'][2]['understanding']=='unknown' and len(plan['steps'][2]['message_ids'])==1
    assert data['capture_offers']==before['capture_offers'] and native['sources']==prior['sources']
    assert {v['id']:v for v in native['knowledge']}=={v['id']:v for v in prior['knowledge']}
    assert data['messages'][:len(before['messages'])]==before['messages'] and len(data['messages'])==len(before['messages'])+2
    new=[r for k,r in data['runs'].items() if k not in before['runs']];assert len(new)==1 and new[0]['status']=='completed'
    run=new[0];intent=run['intent'];navigation=intent['learning_navigation'];selected=run['learning_navigation_applied']
    assert intent['intents']==['continue'] and navigation['action']=='advance' and navigation['step_id']==original['current_step_id']
    assert navigation['evidence'] in data['messages'][-2]['content']
    assert selected['original_step_id']==original['current_step_id'] and selected['selected_step_id']==plan['current_step_id'] and selected['input_ids']==run['input_ids']
    binding=task['context']['check_binding'];assert binding['step_id']==plan['current_step_id'] and binding['step_title']==plan['steps'][2]['title']
    assert task['context']['check_question']!=old['context']['check_question'] and binding['question']==task['context']['check_question']
    q=read(PRIVATE/'07-advance-quota.json');result=dict(gate='explicit_advance',status='PASS',models=q['model_requests'],web=q['web_operations'],
        advanced_from_step2_to_step3_once=True,same_input_navigation_binding_verified=True,correct_third_step_lesson_and_check=True,
        no_extra_understanding_certified=True,saved_cards_sources_and_offer_unchanged=True,new_run_id=run['run_id'])
    gates=read(OUT/'gates.json');assert not any(g['gate']==result['gate'] for g in gates);gates.append(result)
    (OUT/'gates.json').write_text(json.dumps(gates,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
