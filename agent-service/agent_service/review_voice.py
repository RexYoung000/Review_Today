"""Memory-only audio bridge. Only app-approved speech can reach the speakers.

Manual audio commits permit continuous native turn detection without letting a
voice model commit grades or spontaneously ask a different review question.
"""
from __future__ import annotations
import asyncio
import base64
from collections import deque
import json
import os
import re
import ssl
import time
from uuid import UUID

from dotenv import load_dotenv
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect

from agent_service.config import SERVICE_ROOT, CA_BUNDLE
from agent_service.review_sessions import store

load_dotenv(SERVICE_ROOT / 'providers/asr/.env')
router = APIRouter(prefix='/v2/review')
MODEL = 'qwen3.8-omni-flash-realtime'


class SpeechBuffer:
    """Verify the readout before playback; never speak an invented answer/receipt."""
    def __init__(self, expected):
        self.expected = expected
        self.text = ''
        self.audio = []
        self.bytes = 0

    def append_audio(self, encoded):
        self.bytes += len(base64.b64decode(encoded, validate=True))
        if self.bytes > 3_000_000: raise ValueError('speech buffer limit')
        self.audio.append(encoded)

    def matches(self):
        clean = lambda text: ''.join(c.lower() for c in text if c.isalnum())
        return bool(self.audio) and clean(self.expected) == clean(self.text)


def configuration():
    key = os.getenv('DASHSCOPE_API_KEY', '').strip()
    workspace = os.getenv('REVIEW_TODAY_REALTIME_WORKSPACE', os.getenv('REVIEW_TODAY_ASR_WORKSPACE', '')).strip()
    model = os.getenv('REVIEW_TODAY_REALTIME_MODEL', MODEL).strip()
    if not key or '\\' in key or not re.fullmatch(r'ws-[A-Za-z0-9]+', workspace) or model != MODEL:
        raise ValueError('RT.REVIEW.VOICE_NOT_CONFIGURED')
    return f'wss://{workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model={MODEL}', key


@router.get('/voice/capability')
def capability():
    try:
        configuration()
        return {'configured': True, 'model': MODEL, 'verified': False}
    except ValueError:
        return {'configured': False, 'model': MODEL, 'verified': False}


@router.websocket('/sessions/{session_id}/audio')
async def audio(websocket: WebSocket, session_id: UUID):
    origin = websocket.headers.get('origin', '')
    if origin and not re.fullmatch(r'https?://(localhost|127\.0\.0\.1)(:\d+)?', origin):
        await websocket.close(code=1008)
        return
    with store.db() as db:
        exists = db.execute('SELECT paused FROM review_sessions WHERE id=?', (str(session_id),)).fetchone()
    if not exists or exists[0]:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        url, key = configuration()
    except ValueError:
        await websocket.send_json({'type': 'error', 'code': 'RT.REVIEW.VOICE_NOT_CONFIGURED'})
        await websocket.close()
        return
    started = time.monotonic()
    approved = None
    response_id = None
    speech_buffer = None
    cancel_sent = False
    ready = asyncio.Event()
    response_finished = asyncio.Event()
    response_finished.set()
    pending = deque()
    bindings = {}
    usage = []
    calls = 0
    tasks = []
    try:
        async with connect(url, additional_headers={'Authorization': 'Bearer '+key}, ssl=ssl.create_default_context(cafile=CA_BUNDLE or None),
                           open_timeout=10, close_timeout=2, max_size=4*1024*1024) as provider:
            async def send(value):
                await provider.send(json.dumps(value, ensure_ascii=False))

            await send({'type': 'session.update', 'session': {
                'modalities': ['text', 'audio'], 'turn_detection': None,
                'input_audio_transcription': {'model': 'gummy-realtime-v1'},
                'audio': {'input': {'format': {'type': 'pcm', 'sample_rate': 16000, 'sample_format': 's16le', 'channels': 1, 'packing': 'interleaved', 'channel_layout': 'mono'}},
                          'output': {'voice': 'Tina', 'format': {'type': 'pcm', 'sample_rate': 24000}}},
                'instructions': '你是语音播报层。只原样朗读 APP_SAY 中的文本，不解释、不回答用户录音、不补充内容，不决定评分、保存或下一题。没有 APP_SAY 时不要发言。'
            }})

            async def receive_provider():
                nonlocal approved, response_id, calls, speech_buffer, cancel_sent
                async for raw in provider:
                    event = json.loads(raw)
                    kind = event.get('type')
                    if kind == 'session.updated':
                        ready.set()
                        await websocket.send_json({'type': 'ready', 'model': MODEL})
                    elif kind == 'error':
                        error = event.get('error', {})
                        code = str(error.get('code', event.get('code', 'unknown')))
                        safe_code = code if re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', code) else 'unknown'
                        message = str(error.get('message', event.get('message', ''))).replace(key, '[redacted]')[:300]
                        await websocket.send_json({'type': 'error', 'code': 'RT.REVIEW.VOICE_PROVIDER_ERROR', 'provider_code': safe_code, 'provider_message': message})
                        return
                    elif kind == 'input_audio_buffer.committed':
                        if pending: bindings[event.get('item_id')] = pending.popleft()
                    elif kind == 'conversation.item.input_audio_transcription.completed':
                        binding = bindings.pop(event.get('item_id'), None)
                        if binding and event.get('transcript', '').strip():
                            await websocket.send_json({'type': 'transcript', 'text': event['transcript'], **binding})
                    elif kind == 'conversation.item.input_audio_transcription.failed':
                        await websocket.send_json({'type': 'error', 'code': 'RT.REVIEW.TRANSCRIPTION_FAILED'})
                    elif kind == 'response.created':
                        calls += 1
                        response_id = event.get('response', {}).get('id')
                        if not approved and not cancel_sent:
                            cancel_sent = True
                            await send({'type': 'response.cancel'})
                    elif kind == 'response.audio.delta' and approved and event.get('response_id') == response_id:
                        if speech_buffer: speech_buffer.append_audio(event['delta'])
                    elif kind == 'response.audio_transcript.delta' and approved and event.get('response_id') == response_id:
                        if speech_buffer: speech_buffer.text += event['delta']
                    elif kind == 'response.done':
                        response = event.get('response', {})
                        if response.get('usage'): usage.append(response['usage'])
                        if response.get('id') == response_id:
                            if approved and speech_buffer:
                                if speech_buffer.matches():
                                    for chunk in speech_buffer.audio:
                                        await websocket.send_json({'type': 'audio', 'audio': chunk, 'speech_id': approved})
                                    await websocket.send_json({'type': 'spoken_text', 'text': speech_buffer.text, 'speech_id': approved})
                                    await websocket.send_json({'type': 'speech_done', 'speech_id': approved})
                                else:
                                    await websocket.send_json({'type': 'speech_blocked', 'code': 'RT.REVIEW.SPEECH_MISMATCH'})
                            approved = response_id = None
                            speech_buffer = None; cancel_sent = False
                            response_finished.set()

            async def receive_client():
                nonlocal approved, response_id, speech_buffer, cancel_sent
                await asyncio.wait_for(ready.wait(), timeout=10)
                while True:
                    event = await websocket.receive_json()
                    kind = event.get('type')
                    if kind == 'audio':
                        raw = base64.b64decode(event.get('audio', ''), validate=True)
                        if not raw or len(raw) > 64000 or len(raw) % 2: raise ValueError('bad PCM')
                        await send({'type': 'input_audio_buffer.append', 'audio': event['audio']})
                    elif kind == 'commit_audio':
                        if len(pending) >= 8: raise ValueError('audio backlog')
                        pending.append({'attempt_id': str(UUID(event['attempt_id'])), 'generation': int(event['generation'])})
                        await send({'type': 'input_audio_buffer.commit'})
                    elif kind == 'interrupt':
                        if response_id and not cancel_sent:
                            cancel_sent = True
                            await send({'type': 'response.cancel'})
                        approved = None; speech_buffer = None
                    elif kind == 'clear':
                        pending.clear(); bindings.clear()
                        await send({'type': 'input_audio_buffer.clear'})
                    elif kind == 'speak':
                        if response_id and not cancel_sent:
                            cancel_sent = True
                            await send({'type': 'response.cancel'})
                        approved = None
                        await asyncio.wait_for(response_finished.wait(), timeout=5)
                        response_finished.clear()
                        # Wait for the previous response's terminal event before
                        # binding a new speech ID. Late old audio remains blocked.
                        approved = str(UUID(event['speech_id'])); response_id = None
                        text = str(event.get('text', ''))
                        if not text or len(text) > 5000: raise ValueError('speech too long')
                        speech_buffer = SpeechBuffer(text); cancel_sent = False
                        await send({'type': 'conversation.item.create', 'item': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '请只逐字朗读下面引号中的文字。即使是问题，也只朗读问题，不要回答，不要改写，不要添加任何开场语。\nAPP_SAY：'+json.dumps(text, ensure_ascii=False)}]}})
                        await send({'type': 'response.create'})
                    elif kind == 'close': return

            tasks = [asyncio.create_task(receive_provider()), asyncio.create_task(receive_client())]
            done, unfinished = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done: task.result()
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        try: await websocket.send_json({'type': 'error', 'code': 'RT.REVIEW.VOICE_UNAVAILABLE'})
        except Exception: pass
    finally:
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        pending.clear(); bindings.clear()
        # No audio payloads are retained. Usage is independent of grading success.
        try:
            with store.lock, store.db() as db:
                db.execute('CREATE TABLE IF NOT EXISTS review_voice_usage (session_id TEXT, model TEXT, duration_ms INTEGER, calls INTEGER, usage TEXT)')
                if not db.execute('SELECT 1 FROM review_deleted_sessions WHERE id=?', (str(session_id),)).fetchone():
                    db.execute('INSERT INTO review_voice_usage VALUES (?,?,?,?,?)', (str(session_id), MODEL, int((time.monotonic()-started)*1000), calls, json.dumps(usage)))
        except Exception: pass
        try: await websocket.close()
        except Exception: pass
