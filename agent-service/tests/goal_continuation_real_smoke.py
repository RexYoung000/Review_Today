"""A007 opt-in live routing/matching/teaching with synthetic persisted progress."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true',required=True);parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='review-continuation-live-') as root:
        os.environ['REVIEW_TODAY_HARNESS_DB']=str(Path(root)/'state.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore, HarnessTaskRecord
        from agent_service.learning_progress import set_plan
        from agent_service.goal_continuation import owns, ownership
        from agent_service.schemas import SessionMessageRequest
        def setup(name,goals):
            h=ConversationHarness(ConversationStore(HarnessStore(str(Path(root)/(name+'.sqlite3')))))
            for goal in goals:
                sid,tid=str(uuid.uuid4()),str(uuid.uuid4())
                t=asdict(HarnessTaskRecord(task_id=tid,session_id=sid,client_message_id=str(uuid.uuid4()),content=goal,content_type='text',primary_language='zh',mode_preset='auto',mode='source_learning',status='awaiting_user',stage='teaching',context={'conversation_managed':True,'understanding':'unknown'}))
                set_plan(t,['资料切分与建立索引','检索与重排','基于证据生成答案'])
                t['context']['learning_plan']['steps'][0]['state']='explained'
                with h.store.transaction(sid) as d:d['tasks'][tid]=t;d['active_task_id']=tid
                h.memory_policy(sid,allowed=True,policy_version=0,content_version=0)
            return h
        def send(h,sid,text):
            a=h.accept(sid,SessionMessageRequest(client_message_id=str(uuid.uuid4()),content=text));h.drain(sid)
            d=h.store.get(sid);run=d['runs'][a.run_id]
            replies=[m['content'] for m in d['messages'] if m['run_id']==a.run_id and m['role']=='coach']
            print(json.dumps(dict(input=text,status=run['status'],intent=run.get('intent'),transfer=run.get('goal_transfer'),reply=replies,tasks=len(d['tasks'])),ensure_ascii=False),flush=True)
            assert run['status']=='completed' and replies,run.get('error_code')
            return d
        h=setup('unique',['理解 RAG 的基本流程']);sid=str(uuid.uuid4())
        d=send(h,sid,'继续上次没学完的 RAG')
        assert len(d['tasks'])==1 and ownership(next(iter(d['tasks'].values())))['version']==2
        assert sum(owns(t) for s in h.store.sessions() for t in h.store.get(s)['tasks'].values())==1
        h=setup('multiple',['理解 RAG 的基本流程','RAG 检索质量评估']);sid=str(uuid.uuid4())
        d=send(h,sid,'继续上次没学完的 RAG');assert not d['tasks'] and d.get('continuation_selection')
        d=send(h,sid,'继续 RAG 的基本流程那个目标');assert len(d['tasks'])==1
        h=setup('unrelated',['理解 RAG 的基本流程']);sid=str(uuid.uuid4())
        d=send(h,sid,'继续上次没学完的光合作用');assert not d['tasks']
        h=setup('none',[]);sid=str(uuid.uuid4())
        d=send(h,sid,'继续上次没学完的 RAG');assert not d['tasks']
        print('PASS: live unique continuation, explicit choice after multiple matches, no invented progress.',flush=True)

if __name__=='__main__':main()
