"""Explicit paid smoke: real bridge, synthetic audio only, no microphone.
Run with uv run python -m tests.review_voice_live <new-result.json>.
"""
import asyncio, base64, json, pathlib, socket, subprocess, sys, tempfile, threading, time, wave
from uuid import uuid4
import httpx, uvicorn
from fastapi import FastAPI
from websockets.asyncio.client import connect
from agent_service import review_sessions as r, review_voice as v
from tests.test_review_sessions import binding

async def run(port, scratch, report):
    sid = str(uuid4()); b = binding(); base = f'http://127.0.0.1:{port}'
    async with httpx.AsyncClient(trust_env=False) as client:
        result = await client.post(base+'/v2/review/sessions', json=dict(session_id=sid, revision=0, binding=b.model_dump(mode='json')))
        result.raise_for_status()
    speech = '植物利用光能，把二氧化碳和水转化为有机物，同时释放氧气。'
    wav = pathlib.Path(scratch)/'synthetic.wav'
    subprocess.run(['say','-v','Tingting','-o',str(wav),'--file-format=WAVE','--data-format=LEI16@16000',speech],check=True)
    with wave.open(str(wav)) as f:
        assert f.getnchannels()==1 and f.getframerate()==16000
        pcm=f.readframes(f.getnframes())
    report['synthetic_input'] = speech
    report['input_audio_seconds'] = len(pcm)/32000
    started=time.monotonic()
    async with connect(f'ws://127.0.0.1:{port}/v2/review/sessions/{sid}/audio', proxy=None) as ws:
        async def send(e): await ws.send(json.dumps(e, ensure_ascii=False))
        async def receive():
            e=json.loads(await asyncio.wait_for(ws.recv(),35))
            if e['type'] in {'error','speech_blocked'}: raise RuntimeError(e['code']+': '+e.get('provider_code','')+': '+e.get('provider_message',''))
            return e
        e=await receive(); assert e['type']=='ready', e
        report['ready_ms']=round((time.monotonic()-started)*1000)
        speech_id=str(uuid4()); t=time.monotonic(); size=0; text=[]
        await send(dict(type='speak',text=b.prompt,speech_id=speech_id))
        while True:
            e=await receive()
            if e['type']=='audio':
                assert e['speech_id']==speech_id
                if not size: report['first_audio_ms']=round((time.monotonic()-t)*1000)
                size+=len(base64.b64decode(e['audio']))
            if e['type']=='spoken_text': text.append(e['text'])
            if e['type']=='speech_done': break
        assert size>0
        report['output_audio_seconds']=size/48000; report['spoken_text']=''.join(text)
        for offset in range(0,len(pcm),3200):
            await send(dict(type='audio',audio=base64.b64encode(pcm[offset:offset+3200]).decode()))
            await asyncio.sleep(.01)
        t=time.monotonic()
        await send(dict(type='commit_audio',attempt_id=str(b.attempt_id),generation=7))
        while True:
            e=await receive()
            if e['type']=='transcript':
                assert e['attempt_id']==str(b.attempt_id) and e['generation']==7
                report['transcript']=e['text']; report['transcription_after_commit_ms']=round((time.monotonic()-t)*1000)
                break
        # Cancel a live generated response, then verify a fresh response remains usable.
        old=str(uuid4()); new=str(uuid4())
        await send(dict(type='speak',text='接下来是一段用于验证打断的合成播报。'*10,speech_id=old))
        await asyncio.sleep(.3)
        await send(dict(type='interrupt')); await send(dict(type='clear'))
        await send(dict(type='speak',text='已停止。',speech_id=new))
        received_new=False
        while True:
            e=await receive()
            if e['type']=='audio' and e['speech_id']==new: received_new=True
            if e['type']=='speech_done' and e['speech_id']==new: break
        assert received_new
        report['interrupt_then_new_response']=True
        await send(dict(type='close'))
    await asyncio.sleep(.5)
    # Reconnect without resetting the review cursor / attempt identity.
    async with connect(f'ws://127.0.0.1:{port}/v2/review/sessions/{sid}/audio',proxy=None) as ws:
        e=json.loads(await asyncio.wait_for(ws.recv(),20)); assert e['type']=='ready',e
        report['reconnect_ready']=True
        await ws.send(json.dumps({'type':'close'}))
    await asyncio.sleep(3)
    with r.store.db() as db:
        report['voice_usage']=[dict(model=x[0],duration_ms=x[1],calls=x[2],usage=json.loads(x[3])) for x in db.execute('SELECT model,duration_ms,calls,usage FROM review_voice_usage')]
    report['session_id']=sid


def main():
    target=pathlib.Path(sys.argv[1]); assert not target.exists(), 'Use a new result file'
    report={'model':v.MODEL,'timestamp':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'audio_retained':False}
    with tempfile.TemporaryDirectory(prefix='review-today-live-voice-') as scratch:
        r.store=v.store=r.ReviewStore(scratch+'/review.sqlite3')
        app=FastAPI();app.include_router(r.router);app.include_router(v.router)
        sock=socket.socket(); sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
        thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True); thread.start()
        while not server.started: time.sleep(.05)
        try:
            asyncio.run(run(port,scratch,report)); report['passed']=True
        except Exception as exc:
            report['passed']=False; report['error']=type(exc).__name__+': '+str(exc)[:200]
        finally:
            server.should_exit=True; thread.join(timeout=5)
            target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False),flush=True)
        if not report['passed']: raise SystemExit(1)

if __name__=='__main__': main()
