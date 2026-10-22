"""Replay the retained real routing decision on an isolated production harness.

The reply is controlled; this is not a new model-quality or native-UI acceptance.
"""
import atexit,copy,json,os,shutil,socket,sys,tempfile
from urllib.parse import urlsplit,unquote
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
REAL=ROOT/'output/fullflow-real-2026-10-22';PRIVATE=ROOT/'output/learning-recap-repair-2026-10-22'
def blocked(*args,**kwargs):raise AssertionError('Networking forbidden in controlled replay')
def read(path):return json.loads(path.read_text())
def main():
    scratch=Path(tempfile.mkdtemp(prefix='review-today-recap-replay-',suffix='.noindex'))
    os.environ['REVIEW_TODAY_HARNESS_DB']=str(scratch/'import.sqlite3')
    os.environ['REVIEW_TODAY_REVIEW_DB']=str(scratch/'review.sqlite3')
    atexit.register(lambda:shutil.rmtree(scratch,ignore_errors=True))
    def audit(event,args):
        if event=='sqlite3.connect':
            value=str(args[0]);path=Path(unquote(urlsplit(value).path) if value.startswith('file:') else value).expanduser().resolve()
            if path.is_relative_to(Path.home()/'Library/Application Support/Review Today'):raise AssertionError('Daily SQLite forbidden in replay')
    sys.addaudithook(audit)
    with patch.object(socket.socket,'connect',side_effect=blocked),patch.object(socket,'create_connection',side_effect=blocked):
        from agent_service.schemas import ConversationOutput,IntentDecision
        from agent_service.learning_progress import current_step
        from tests.test_conversation_v2 import ConversationTests
        baseline=json.loads(read(REAL/'gates/08-independent-question-snapshot.json')['checkpoint_json'])['checkpoint']
        events=[json.loads(l) for l in (REAL/'live-events.jsonl').read_text().splitlines()]
        entries=[d for d in events if d.get('schema')=='IntentDecision']
        start=[d for d in entries if d['type']=='semantic_start'][-1]
        raw=[d for d in entries if d['type']=='semantic_output'][-1]['output']
        request=start['input']['current_inputs'][-1]
        assert raw['intents']==['continue'] and '不进入下一节' in request
        f=ConversationTests();f.setUp()
        try:
            f.sid=baseline['session_id']
            with f.store.transaction(f.sid) as state:state.update(copy.deepcopy(baseline))
            before=f.state();task=before['tasks'][before['active_task_id']]
            f.decision=IntentDecision.model_validate(raw)
            base=f.model
            def model(system,user,schema,**kwargs):
                if schema is ConversationOutput:
                    f.calls.append((schema,json.loads(user)))
                    return ConversationOutput(message='资料准确也不代表回答忠实：原文写“仅限专业版用户”，回答写成“所有用户”，是生成时漏掉条件。应分别核对资料是否可信、回答是否忠实以及条件是否适用于当前时间、版本和场景。')
                return base(system,user,schema,**kwargs)
            with patch('agent_service.conversation.parse_model',side_effect=model):accepted=f.send(request,mode=before['mode'])
            after=f.state();new=after['tasks'][task['task_id']]
            assert after['runs'][accepted.run_id]['status']=='completed'
            assert after['runs'][accepted.run_id]['intent']['intents']==['followup']
            for key in ['learning_plan','check_question','check_binding','last_lesson','sources','understanding','lesson_index','practice']:
                assert new['context'][key]==task['context'][key],key
            assert after['capture_offers']==before['capture_offers'] and after['pending']==before['pending'] and after['draft']==before['draft']
            assert set(after['tasks'])==set(before['tasks']) and after['messages'][:len(before['messages'])]==before['messages']
            for key in ['task_id','session_id','client_message_id','mode','content']:
                assert new[key]==task[key],key
            for key in ['goal_ownership','memory_references','origin_run_id','lifecycle_revision']:
                assert new['context'].get(key)==task['context'].get(key),key
            assert current_step(new)['id']==current_step(task)['id']
            schemas=[s.__name__ for s,_ in f.calls];assert schemas==['IntentDecision','TeachingPreparation','ConversationOutput'],schemas
            f.capture.assert_not_called()
            PRIVATE.mkdir(parents=True,exist_ok=True)
            (PRIVATE/'after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
            report=dict(status='PASS_CONTROLLED_REPLAY',retained_real_intent_reused=True,original_intents=raw['intents'],normalized_intents=after['runs'][accepted.run_id]['intent']['intents'],request=request,current_step_unchanged=True,plan_check_sources_practice_understanding_unchanged=True,entire_v2_invitation_unchanged=True,history_and_task_ownership_unchanged=True,save_not_called=True,controlled_reply=True,model_schemas=schemas,real_model_requests=0,real_web_operations=0,network_blocked=True,native_ui_not_run=True,new_model_navigation_quality_not_verified=True)
            (OUT/'replay-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(report,ensure_ascii=False))
        finally:f.tearDown()
if __name__=='__main__':main()
