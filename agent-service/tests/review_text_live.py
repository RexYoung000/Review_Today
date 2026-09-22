"""Explicit real text-model review probe, synthetic data, new files only."""
import concurrent.futures, json, pathlib, sys, tempfile, time
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent_service import review_sessions as r
from tests.test_review_sessions import binding

CASES = [
 ('synonym', '光驱动植物把二氧化碳和水变成糖类，并放出氧气。','utterance','answer','good'),
 ('missing', '植物利用光能。','utterance','answer','again'),
 ('mixed_error', '植物利用光能吸收氧气，消耗水，生产有机物。','utterance','answer','again'),
 ('forgot', '想不起来了。','utterance','forgot','again'),
 ('clarify', '这里的原料和产物指什么？换个问法。','clarify','clarify',None),
 ('hint', '给一点提示。','hint','hint',None),
 ('explain', '我忘了，请直接重新讲解。','explain','explain',None),
 ('understood', '懂了。','utterance','understood',None),
 ('correction', '刚才语音转写错了，我要重新说。','utterance','correction',None),
 ('difficult_correct', '回忆起来很吃力。植物利用光能，把二氧化碳和水转化为有机物，释放氧气。','utterance','answer','hard'),
 ('skip', '这一题先跳过。','utterance','skip',None),
 ('corrected_answer', '植物利用光能，把二氧化碳和水转化为有机物，并释放氧气。','correct','answer','good'),
 ('knowledge_help', '我不知道原料有哪些，你告诉我原料和产物分别是什么？','utterance','question',None),
]

def main():
    target=pathlib.Path(sys.argv[1]); assert not target.exists()
    report={'timestamp':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'model':r.MODEL,'cases':[]}
    with tempfile.TemporaryDirectory(prefix='review-today-real-text-') as tmp:
        r.store=r.ReviewStore(tmp+'/review.sqlite3')
        app=FastAPI();app.include_router(r.router)
        with TestClient(app) as client:
            def one(case):
                name,text,action,expected_intent,expected_grade=case
                b=binding();sid=str(uuid4())
                client.post('/v2/review/sessions',json=dict(session_id=sid,revision=0,binding=b.model_dump(mode='json'))).raise_for_status()
                body=r.TurnInput(event_id=uuid4(),revision=0,binding=b,text=text,action=action,
                    correcting=action=='correct', assistance_used=action=='correct',
                    dialogue=[r.DialogueLine(role='user',text='植物利用光能。'),r.DialogueLine(role='assistant',text='想一想气体原料与液体原料。',kind='hint')] if action=='correct' else [])
                start=time.monotonic()
                response=client.post(f'/v2/review/sessions/{sid}/turns',json=body.model_dump(mode='json'))
                output=response.json()
                return dict(name=name,input=body.model_dump(mode='json'),expected_intent=expected_intent,expected_grade=expected_grade,
                            status=response.status_code,output=output,total_ms=round((time.monotonic()-start)*1000),
                            matches=response.is_success and output.get('intent')==expected_intent and output.get('grade')==expected_grade and (name!='knowledge_help' or output.get('answer_revealed') is True))
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                report['cases']=list(pool.map(one,CASES))
    report['matched']=sum(c['matches'] for c in report['cases'])
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'matched':report['matched'],'total':len(CASES),'model':report['model']},ensure_ascii=False))

if __name__=='__main__':main()
