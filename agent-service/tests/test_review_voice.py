import base64
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from agent_service import review_voice as v, review_sessions as r

class VoiceGuardTests(unittest.TestCase):
    def test_readout_is_checked_before_audio_release(self):
        pcm=base64.b64encode(b'\0'*320).decode()
        gate=v.SpeechBuffer('光合作用利用什么能量？')
        gate.append_audio(pcm);gate.text='植物利用光能。'
        self.assertFalse(gate.matches())
        gate.text='光合作用利用什么能量?'
        self.assertTrue(gate.matches())
        gate.text='光合作用利用什么能量？已保存，下次明天复习。'
        self.assertFalse(gate.matches())

    def test_empty_and_excess_audio_are_rejected(self):
        gate=v.SpeechBuffer('你好');gate.text='你好';self.assertFalse(gate.matches())
        with self.assertRaises(ValueError):gate.append_audio(base64.b64encode(b'\0'*3_000_002).decode())

    def test_missing_config_uses_a_distinct_technical_failure(self):
        with patch.dict('os.environ',{'DASHSCOPE_API_KEY':''}):
            self.assertFalse(v.capability()['configured'])
            with self.assertRaises(ValueError):v.configuration()

    def test_unknown_paused_and_foreign_origins_cannot_start_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=r.ReviewStore(tmp+'/review.sqlite3');sid=uuid4()
            store.upsert(r.SessionInput(session_id=sid,revision=1,paused=True))
            app=FastAPI();app.include_router(v.router)
            with patch.object(v,'store',store),TestClient(app) as client:
                for id,headers in [(uuid4(),{}),(sid,{}),(sid,{'origin':'https://example.com'})]:
                    with self.assertRaises(WebSocketDisconnect):
                        with client.websocket_connect(f'/v2/review/sessions/{id}/audio',headers=headers):pass

if __name__=='__main__':unittest.main()
