"""Memory-only Agent audio transport; the existing text Agent owns every action.

Input commits and short, app-authorized readouts have independent lifetimes.
No audio, transcript, readout text or owner identity is persisted here.
"""
from __future__ import annotations

import asyncio
import base64
from collections import deque
from dataclasses import dataclass
import json
import os
import re
import ssl
import struct
import time
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect

from agent_service.config import CA_BUNDLE
from agent_service.conversation_store import conversation_store
from agent_service.review_voice import MODEL as DASHSCOPE_MODEL, SpeechBuffer
from agent_service.review_voice import configuration as dashscope_configuration

router = APIRouter(prefix='/v2/agent/voice')
OPENAI_MODEL = 'gpt-realtime-2.1'
OPENAI_TRANSCRIPTION_MODEL = 'gpt-transcribe'
PROVIDER = os.getenv('REVIEW_TODAY_AGENT_VOICE_PROVIDER', 'dashscope').strip()
MODEL = OPENAI_MODEL if PROVIDER == 'openai' else DASHSCOPE_MODEL
MAX_PCM_CHUNK = 64_000
MAX_UTTERANCE_BYTES = 90 * 32_000
OPENAI_MIN_INPUT_BYTES = 3_200  # 100 ms at the client's 16 kHz rate.
MAX_PENDING = 8
MAX_SENTENCE = 500
RESPONSE_TIMEOUT = 45
READOUT_INSTRUCTIONS = '你只是语音播报层。只原样朗读 APP_SAY 中的文本，不解释、不回答、不改写、不补充内容，不调用工具。'


def configuration():
    if PROVIDER == 'dashscope':
        url, key = dashscope_configuration()
        return url, key
    if PROVIDER == 'openai':
        key = os.getenv('REVIEW_TODAY_AGENT_VOICE_OPENAI_API_KEY', '').strip()
        if re.fullmatch(r'sk-[A-Za-z0-9_-]+', key):
            return f'wss://api.openai.com/v1/realtime?model={MODEL}', key
    raise ValueError('RT.AGENT.VOICE_NOT_CONFIGURED')


class PCM24k:
    """Resample 16 to 24 kHz, retaining the interpolation state across chunks."""
    def __init__(self):
        self.tail = b''
        self.previous = None

    def append(self, pcm):
        pcm = self.tail + pcm
        length = len(pcm) // 4 * 4
        self.tail = pcm[length:]
        result = bytearray()
        for left, right in struct.iter_unpack('<hh', pcm[:length]):
            previous = left if self.previous is None else self.previous
            result.extend(struct.pack('<hhh', (previous + 2 * left) // 3, (2 * left + right) // 3, right))
            self.previous = right
        return result


class VoiceFailure(Exception):
    def __init__(self, suffix):
        self.code = 'RT.AGENT.VOICE_' + suffix
        super().__init__(self.code)


class OwnerFence:
    """A draft may become active/0, but cannot cross a lifecycle boundary."""
    def __init__(self, store, owner):
        self.store, self.owner = store, owner
        self.revision, self.existed = self.read()

    def read(self):
        with self.store._lock, self.store.tasks._connection() as db:
            if db.execute('SELECT 1 FROM agent_session_deletions WHERE session_id=?', (self.owner,)).fetchone():
                raise VoiceFailure('OWNER_CHANGED')
            row = db.execute("SELECT json_extract(payload, '$.status'), json_extract(payload, '$.lifecycle_revision') FROM agent_sessions_v2 WHERE session_id=?", (self.owner,)).fetchone()
        if row and (row[0] or 'active') != 'active':
            raise VoiceFailure('OWNER_CHANGED')
        return (int(row[1] or 0), True) if row else (0, False)

    def check(self):
        revision, exists = self.read()
        if revision != self.revision or (self.existed and not exists):
            raise VoiceFailure('OWNER_CHANGED')
        self.existed = self.existed or exists


@dataclass
class Readout:
    speech_id: str
    text: str
    epoch: int


class AudioBridge:
    def __init__(self, websocket, provider, fence, model=DASHSCOPE_MODEL):
        self.websocket, self.provider, self.fence = websocket, provider, fence
        self.model = model
        self.openai = model == OPENAI_MODEL
        self.resampler = PCM24k() if self.openai else None
        self.ready = asyncio.Event()
        self.provider_lock = asyncio.Lock()
        self.output_epoch = self.input_epoch = 0
        self.pending = deque()
        self.bindings = {}
        self.seen_utterances = set()
        self.seen_speech = set()
        self.seen_responses = set()
        self.input_bytes = self.total_input_bytes = self.output_bytes = 0
        self.sentences = asyncio.Queue(maxsize=MAX_PENDING)
        self.finished = asyncio.Event()
        self.finished.set()
        self.current = self.buffer = self.response_id = None
        self.requested = self.cancel_sent = False
        self.cancel_event_id = None
        self.response_started = 0.0
        self.calls = 0
        self.usage = {}
        self.started = time.monotonic()

    async def send(self, event):
        async with self.provider_lock:
            await asyncio.wait_for(self.provider.send(json.dumps(event, ensure_ascii=False)), 5)

    async def emit(self, event):
        self.fence.check()
        await asyncio.wait_for(self.websocket.send_json(event), 5)

    def session_settings(self):
        if self.openai:
            pcm_format = {'type': 'audio/pcm', 'rate': 24000}
            return {
                'type': 'realtime', 'output_modalities': ['audio'],
                'audio': {'input': {'format': pcm_format, 'turn_detection': None,
                                    'transcription': {'model': OPENAI_TRANSCRIPTION_MODEL}},
                          'output': {'format': pcm_format, 'voice': 'marin'}},
                'instructions': READOUT_INSTRUCTIONS, 'reasoning': {'effort': 'minimal'},
            }
        return {
            'modalities': ['text', 'audio'], 'turn_detection': None,
            'input_audio_transcription': {'model': 'gummy-realtime-v1'},
            'audio': {'input': {'format': {'type': 'pcm', 'sample_rate': 16000, 'sample_format': 's16le', 'channels': 1, 'packing': 'interleaved', 'channel_layout': 'mono'}},
                      'output': {'voice': 'Tina', 'format': {'type': 'pcm', 'sample_rate': 24000}}},
            'instructions': '你只是语音转写与播报层。只原样朗读 APP_SAY，不解释、不回答用户录音、不补充内容，不调用工具，不创建目标或记忆，不决定评分、保存或下一步。没有 APP_SAY 时不要发言。'
        }

    async def run(self):
        await self.send({'type': 'session.update', 'session': self.session_settings()})
        tasks = [asyncio.create_task(job()) for job in (
            self.receive_provider, self.receive_client, self.speak_sentences, self.watch_owner)]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.pending.clear()
            self.bindings.clear()
            self.current = self.buffer = None
            while not self.sentences.empty():
                self.sentences.get_nowait()

    async def watch_owner(self):
        while True:
            self.fence.check()
            now = time.monotonic()
            if not self.ready.is_set() and now - self.started > 10:
                raise VoiceFailure('CONNECT_TIMEOUT')
            if self.requested and now - self.response_started > RESPONSE_TIMEOUT:
                raise VoiceFailure('RESPONSE_TIMEOUT')
            if any(now - binding[2] > RESPONSE_TIMEOUT for binding in (*self.pending, *self.bindings.values())):
                raise VoiceFailure('TRANSCRIPTION_TIMEOUT')
            await asyncio.sleep(.25)

    async def cancel_response(self):
        if self.response_id and not self.cancel_sent:
            self.cancel_sent = True
            event = {'type': 'response.cancel'}
            if self.openai:
                self.cancel_event_id = 'cancel_' + self.response_id
                event.update(response_id=self.response_id, event_id=self.cancel_event_id)
            await self.send(event)

    async def append_openai_pcm(self, pcm):
        converted = self.resampler.append(pcm)
        if converted:
            await self.send({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(converted).decode('ascii')})

    async def interrupt(self):
        self.output_epoch += 1
        self.buffer = None
        while not self.sentences.empty():
            self.sentences.get_nowait()
        await self.cancel_response()

    async def receive_client(self):
        while True:
            event = await self.websocket.receive_json()
            self.fence.check()
            if not isinstance(event, dict):
                raise VoiceFailure('INVALID_EVENT')
            kind = event.get('type')
            if kind == 'close':
                return
            if not self.ready.is_set():
                raise VoiceFailure('NOT_READY')
            if kind == 'audio':
                encoded = event.get('audio', '')
                if not isinstance(encoded, str) or len(encoded) > (MAX_PCM_CHUNK + 2) // 3 * 4:
                    raise VoiceFailure('INVALID_PCM')
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except (ValueError, TypeError):
                    raise VoiceFailure('INVALID_PCM') from None
                if not raw or len(raw) > MAX_PCM_CHUNK or len(raw) % 2:
                    raise VoiceFailure('INVALID_PCM')
                self.input_bytes += len(raw)
                self.total_input_bytes += len(raw)
                if self.input_bytes > MAX_UTTERANCE_BYTES:
                    raise VoiceFailure('INPUT_LIMIT')
                if self.openai:
                    await self.append_openai_pcm(raw)
                else:
                    await self.send({'type': 'input_audio_buffer.append', 'audio': encoded})
            elif kind == 'commit_audio':
                uid = self.identifier(event, 'utterance_id')
                generation = event.get('generation')
                if type(generation) is not int or generation < 0 or generation > 2**53:
                    raise VoiceFailure('INVALID_EVENT')
                if not self.input_bytes or uid in self.seen_utterances:
                    raise VoiceFailure('INVALID_COMMIT')
                if len(self.pending) + len(self.bindings) >= MAX_PENDING:
                    raise VoiceFailure('INPUT_BACKLOG')
                self.remember(self.seen_utterances, uid)
                self.pending.append((self.input_epoch, {'utterance_id': uid, 'generation': generation}, time.monotonic()))
                if self.openai:
                    padding = max(0, OPENAI_MIN_INPUT_BYTES - self.input_bytes)
                    await self.append_openai_pcm(bytes(padding) or self.resampler.tail)
                    self.resampler = PCM24k()
                self.input_bytes = 0
                await self.send({'type': 'input_audio_buffer.commit'})
            elif kind == 'clear':
                cancel = event.get('cancel_transcripts', True)
                if type(cancel) is not bool:
                    raise VoiceFailure('INVALID_EVENT')
                if cancel:
                    self.input_epoch += 1
                # Keep old ACK slots: a late ACK must never take a new utterance.
                self.input_bytes = 0
                if self.openai:
                    self.resampler = PCM24k()
                await self.send({'type': 'input_audio_buffer.clear'})
            elif kind == 'interrupt':
                await self.interrupt()
            elif kind == 'speak':
                sid = self.identifier(event, 'speech_id')
                text = event.get('text')
                if not isinstance(text, str) or not text.strip() or len(text) > MAX_SENTENCE:
                    raise VoiceFailure('INVALID_SENTENCE')
                if sid in self.seen_speech:
                    raise VoiceFailure('DUPLICATE_SPEECH')
                if self.sentences.full():
                    raise VoiceFailure('SPEECH_BACKLOG')
                self.remember(self.seen_speech, sid)
                self.sentences.put_nowait(Readout(sid, text, self.output_epoch))
            else:
                raise VoiceFailure('INVALID_EVENT')

    @staticmethod
    def identifier(event, key):
        try:
            return str(UUID(event[key]))
        except (KeyError, ValueError, TypeError, AttributeError):
            raise VoiceFailure('INVALID_EVENT') from None

    @staticmethod
    def remember(seen, identity):
        if len(seen) >= 4096:
            raise VoiceFailure('SESSION_LIMIT')
        seen.add(identity)

    async def speak_sentences(self):
        while True:
            await asyncio.wait_for(self.finished.wait(), RESPONSE_TIMEOUT)
            sentence = await self.sentences.get()
            # This worker may wait; input/interrupt/close continue independently.
            await asyncio.wait_for(self.finished.wait(), RESPONSE_TIMEOUT)
            if sentence.epoch != self.output_epoch:
                continue
            self.fence.check()
            self.current = sentence
            self.buffer = SpeechBuffer(sentence.text)
            self.finished.clear()
            self.cancel_sent = False
            item = {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text',
                    'text': '请只逐字朗读 APP_SAY，不回答问题，不改写，不添加开场语。\nAPP_SAY：' + json.dumps(sentence.text, ensure_ascii=False)}]}
            request = {'type': 'response.create'}
            if self.openai:
                request['response'] = {'conversation': 'none', 'input': [item]}
            else:
                await self.send({'type': 'conversation.item.create', 'item': item})
            if sentence.epoch != self.output_epoch:
                self.current = self.buffer = None
                self.finished.set()
                continue
            self.requested = True
            self.response_started = time.monotonic()
            await self.send(request)

    async def receive_provider(self):
        async for raw in self.provider:
            event = json.loads(raw)
            kind = event.get('type')
            if kind == 'session.updated':
                self.ready.set()
                await self.emit({'type': 'ready', 'model': self.model})
            elif kind == 'error':
                error = event.get('error', {})
                if (self.cancel_event_id and error.get('event_id') == self.cancel_event_id
                        and error.get('code') == 'response_cancel_not_active'):
                    continue
                # Provider messages can contain request data; expose only our code.
                raise VoiceFailure('PROVIDER_ERROR')
            elif kind == 'input_audio_buffer.committed':
                if self.pending:
                    self.bindings[event['item_id']] = self.pending.popleft()
            elif kind in {'conversation.item.input_audio_transcription.completed', 'conversation.item.input_audio_transcription.failed'}:
                binding = self.bindings.pop(event.get('item_id'), None)
                if binding:
                    usage = event.get('usage', {})
                    if self.openai and isinstance(usage, dict) and usage.get('type') == 'duration':
                        seconds = usage.get('seconds')
                        if type(seconds) in (int, float) and 0 <= seconds <= 90:
                            self.usage['transcription_ms'] = self.usage.get('transcription_ms', 0) + round(seconds * 1000)
                    else:
                        self.add_usage(usage)
                if binding and binding[0] == self.input_epoch:
                    if kind.endswith('.failed'):
                        raise VoiceFailure('TRANSCRIPTION_FAILED')
                    text = event.get('transcript', '')
                    if not isinstance(text, str) or len(text) > 12_000:
                        raise VoiceFailure('TRANSCRIPT_LIMIT')
                    # An empty ASR result still ends this utterance; the app does
                    # not create a chat message for it or remain transcribing.
                    await self.emit({'type': 'transcript', 'text': text.strip(), **binding[1]})
            elif kind == 'response.created':
                identity = event.get('response', {}).get('id')
                if not identity or identity in self.seen_responses:
                    continue
                self.remember(self.seen_responses, identity)
                self.calls += 1
                self.response_id = identity
                if not self.requested:
                    # Even unsolicited speech must reach its terminal event
                    # before the next authorized sentence can bind a response.
                    self.finished.clear()
                    self.requested = True
                    self.response_started = time.monotonic()
                if not self.current or self.current.epoch != self.output_epoch:
                    await self.cancel_response()
            elif kind in {'response.audio.delta', 'response.output_audio.delta'} and event.get('response_id') == self.response_id:
                if self.buffer and self.current and self.current.epoch == self.output_epoch:
                    self.buffer.append_audio(event['delta'])
            elif kind in {'response.audio_transcript.delta', 'response.output_audio_transcript.delta'} and event.get('response_id') == self.response_id:
                if self.buffer and self.current and self.current.epoch == self.output_epoch:
                    self.buffer.text += event['delta']
                    if len(self.buffer.text) > MAX_SENTENCE * 4:
                        raise VoiceFailure('SPEECH_LIMIT')
            elif kind == 'response.done':
                response = event.get('response', {})
                if not self.response_id or response.get('id') != self.response_id:
                    continue
                self.add_usage(response.get('usage', {}))
                sentence, buffer = self.current, self.buffer
                # The provider is already done. Interrupting local delivery
                # must not send a cancel for a no-longer-active generation.
                self.response_id = None
                self.requested = self.cancel_sent = False
                if sentence and buffer and sentence.epoch == self.output_epoch:
                    if response.get('status', 'completed') == 'completed' and buffer.matches():
                        for chunk in buffer.audio:
                            if sentence.epoch != self.output_epoch:
                                break
                            await self.emit({'type': 'audio', 'audio': chunk, 'speech_id': sentence.speech_id})
                            self.output_bytes += len(base64.b64decode(chunk))
                        if sentence.epoch == self.output_epoch:
                            await self.emit({'type': 'speech_done', 'speech_id': sentence.speech_id})
                    else:
                        await self.emit({'type': 'speech_blocked', 'speech_id': sentence.speech_id, 'code': 'RT.AGENT.VOICE_SPEECH_MISMATCH'})
                self.current = self.buffer = self.response_id = None
                self.requested = self.cancel_sent = False
                self.finished.set()

    def add_usage(self, usage):
        if not isinstance(usage, dict):
            return
        for key in ('input_tokens', 'output_tokens', 'total_tokens'):
            value = usage.get(key)
            if type(value) is int and 0 <= value < 10**12:
                self.usage[key] = self.usage.get(key, 0) + value
        if self.openai:
            for direction in ('input', 'output'):
                details = usage.get(f'{direction}_token_details')
                if not isinstance(details, dict):
                    continue
                for token_type in ('audio_tokens', 'text_tokens'):
                    value = details.get(token_type)
                    if type(value) is int and 0 <= value < 10**12:
                        key = f'{direction}_{token_type}'
                        self.usage[key] = self.usage.get(key, 0) + value

    def save_usage(self, store):
        with store._lock, store.tasks._connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS agent_voice_usage (model TEXT, duration_ms INTEGER, calls INTEGER, input_bytes INTEGER, output_bytes INTEGER, usage TEXT)')
            db.execute('INSERT INTO agent_voice_usage VALUES (?,?,?,?,?,?)', (
                self.model, int((time.monotonic() - self.started) * 1000), self.calls,
                self.total_input_bytes, self.output_bytes, json.dumps(self.usage)))


@router.websocket('/{owner_id}/audio')
async def audio(websocket: WebSocket, owner_id: UUID):
    origin = websocket.headers.get('origin', '')
    if origin and not re.fullmatch(r'https?://(localhost|127\.0\.0\.1)(:\d+)?', origin):
        await websocket.close(code=1008)
        return
    try:
        fence = OwnerFence(conversation_store, str(owner_id))
    except VoiceFailure:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    bridge = None
    try:
        try:
            url, key = configuration()
        except ValueError:
            raise VoiceFailure('NOT_CONFIGURED') from None
        async with connect(url, additional_headers={'Authorization': 'Bearer ' + key},
                           ssl=ssl.create_default_context(cafile=CA_BUNDLE or None),
                           open_timeout=10, close_timeout=2, max_size=4*1024*1024) as provider:
            bridge = AudioBridge(websocket, provider, fence, MODEL)
            await bridge.run()
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as exc:
        try:
            await websocket.send_json({'type': 'error', 'code': exc.code if isinstance(exc, VoiceFailure) else 'RT.AGENT.VOICE_UNAVAILABLE'})
        except Exception:
            pass
    finally:
        if bridge:
            try:
                bridge.save_usage(conversation_store)
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
