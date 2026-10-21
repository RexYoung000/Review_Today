"""Isolated, explicitly paid voice comparison; never opens a microphone/player.

Run from agent-service with .venv/bin/python -m tests.voice_provider_poc.
Default prepares identical synthetic fixtures only. --live --provider selects
one vendor. Existing reports/ledger are preserved; failed stages never retry.
"""
from __future__ import annotations

import argparse
import array
import asyncio
import base64
import contextlib
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import unicodedata
from uuid import uuid4
import wave
from zoneinfo import ZoneInfo

import httpx
from dotenv import dotenv_values
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / 'output/voxtral-voice-poc-20261021'
MISTRAL_ORIGIN = 'https://api.mistral.ai'
ASR_MODEL = 'voxtral-mini-transcribe-realtime-3-0'
TTS_MODEL = 'voxtral-mini-tts-3-0'
FRAME_BYTES = 3200  # 100 ms, PCM16 mono / 16 kHz
TAIL_SECONDS = 1.65  # current native AgentVoiceActivity.pause
STREAM_DELAY_MS = 480
CASES = [
    ('plain', ['植物利用光能，把二氧化碳和水转化为有机物，并释放氧气。']),
    ('terms', ['请解释 RAG 和 API 的区别，再说明向量数据库的作用。']),
    ('numbers', ['复习时间是明天下午三点半，正确率是百分之八十五，一共十二张卡。']),
    ('negation', ['先不要保存这张知识卡，也不要把它加入复习。']),
    ('correction', ['保存到明天，不对，是后天下午，只保存当前这一张。']),
    ('pause', ['我还没有说完，', 1.1, '先不要保存，等我确认。']),
]
READOUTS = [
    ('plain', '光合作用把光能转化为化学能，植物用二氧化碳和水制造有机物，并释放氧气。'),
    ('terms_numbers', 'RAG 是检索增强生成。API 是应用程序接口。明天下午三点半复习十二张卡，正确率百分之八十五。'),
    ('negation', '好的，先不保存，也不加入复习。你可以继续提问，确认后再操作。'),
]
INTERRUPT_TEXT = ('我们先解释这个概念，再看一个例子。现在只讨论知识内容，不保存知识卡，也不调整复习安排。' * 3)
RECOVERY_TEXT = '已停止。我们继续。'


def dump(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def cer(reference, actual):
    reference, actual = normalized(reference), normalized(actual)
    row = list(range(len(actual) + 1))
    for i, expected in enumerate(reference, 1):
        new = [i]
        for j, observed in enumerate(actual, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (expected != observed)))
        row = new
    return round(row[-1] / max(1, len(reference)), 4)


def safe_failure(error):
    # Never log exception strings, HTTP bodies, URLs with credentials or headers.
    result = {'type': type(error).__name__}
    if isinstance(error, httpx.HTTPStatusError):
        result['http_status'] = error.response.status_code
    elif type(getattr(getattr(error, 'response', None), 'status_code', None)) is int:
        result['http_status'] = error.response.status_code
    if isinstance(error, PocFailure):
        result['code'] = error.code
    return result


class PocFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class Ledger:
    """Charge BEFORE every vendor operation, including failed/cancelled ones."""
    def __init__(self, path):
        self.path = Path(path)
        self.entries = json.loads(self.path.read_text()) if self.path.exists() else []

    def charge(self, vendor, operation, *, seconds=0, chars=0):
        prior = [e for e in self.entries if e['vendor'] == vendor]
        if len(prior) >= 16 or sum(e['input_seconds'] for e in prior) + seconds > 150 or sum(e['characters'] for e in prior) + chars > 1200:
            raise PocFailure('POC_BUDGET_EXHAUSTED')
        item = dict(vendor=vendor, operation=operation, input_seconds=round(seconds, 4),
                    characters=chars, status='started', timestamp=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat())
        self.entries.append(item)
        dump(self.path, self.entries)
        return item

    def finish(self, item, status):
        item['status'] = status
        dump(self.path, self.entries)


def protected_hashes():
    paths = [ROOT / p for p in (
        'agent-service/.env', 'agent-service/providers/asr/.env',
        'agent-service/agent_service/agent_voice.py', 'agent-service/agent_service/review_voice.py',
        'Review_Today/AgentVoiceAudio.swift', 'Review_Today/AgentVoiceConversation.swift',
        'Review_Today.xcodeproj/project.pbxproj')]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def write_wav(path, pcm, rate):
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(pcm)


def voiced_end_ms(pcm):
    end = 0
    for offset in range(0, len(pcm), 640):
        values = array.array('h', pcm[offset:offset + 640])
        if values and math.sqrt(sum(v * v for v in values) / len(values)) / 32768 >= .009:
            end = offset + len(values) * 2
    return end / 32


def prepare(output):
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / 'fixtures.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for item in manifest:
            if hashlib.sha256((output / item['file']).read_bytes()).hexdigest() != item['sha256']:
                raise PocFailure('POC_FIXTURE_CHANGED')
        return manifest
    manifest = []
    with tempfile.TemporaryDirectory(prefix='review-today-voice-synthesis-') as scratch:
        for name, parts in CASES:
            pcm = b''
            for part in parts:
                if isinstance(part, (float, int)):
                    pcm += b'\0' * (int(part * 16000) * 2)
                    continue
                path = Path(scratch) / 'segment.wav'
                subprocess.run(['/usr/bin/say', '-v', 'Tingting', '-r', '175', '-o', str(path),
                                '--file-format=WAVE', '--data-format=LEI16@16000', part],
                               check=True, capture_output=True)
                with wave.open(str(path)) as audio:
                    if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
                        raise PocFailure('POC_INPUT_FORMAT')
                    raw = audio.readframes(audio.getnframes())
                # Remove trailing synthesizer silence, keep a small natural gap.
                raw = raw[:min(len(raw), int((voiced_end_ms(raw) + 100) * 32))]
                pcm += raw
            path = output / f'input-{name}.wav'
            write_wav(path, pcm, 16000)
            manifest.append(dict(name=name, reference=''.join(p for p in parts if isinstance(p, str)),
                                 file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                 input_seconds=len(pcm) / 32000, last_voice_ms=voiced_end_ms(pcm),
                                 inserted_pause_seconds=sum(p for p in parts if isinstance(p, (float, int)))))
    dump(manifest_path, manifest)
    return manifest


class PlaybackSink:
    """Wall-clock PCM queue only; no device, no claim of acoustic validation."""
    def __init__(self):
        self.active = True
        self.pending = 0.0
        self.first = asyncio.Event()
        self.first_at = None
        self.updated_at = time.monotonic()
        self.accepted_bytes = self.late_discarded_bytes = 0
        self.pcm = bytearray()

    def tick(self):
        now = time.monotonic()
        self.pending = max(0, self.pending - (now - self.updated_at) * 48000)
        self.updated_at = now

    def feed(self, chunk):
        if len(chunk) % 2:
            raise PocFailure('POC_ODD_PCM')
        if not self.active:
            self.late_discarded_bytes += len(chunk)
            return
        self.tick()
        if self.accepted_bytes + len(chunk) > 6_000_000:
            raise PocFailure('POC_OUTPUT_LIMIT')
        if chunk and self.first_at is None:
            self.first_at = time.monotonic()
            self.first.set()
        self.pending += len(chunk)
        self.accepted_bytes += len(chunk)
        self.pcm.extend(chunk)

    def stop(self):
        self.tick()
        old_pending = int(self.pending)
        self.active = False
        self.pending = 0
        return old_pending


class WaveStream:
    """Parse the actual WAV header before treating streamed bytes as PCM."""
    def __init__(self):
        self.buffer = bytearray()
        self.ready = False
        self.remaining = None

    def feed(self, chunk):
        self.buffer.extend(chunk)
        if not self.ready:
            if len(self.buffer) < 12:
                return b''
            if self.buffer[:4] != b'RIFF' or self.buffer[8:12] != b'WAVE':
                raise PocFailure('POC_TTS_NOT_WAV')
            offset, fmt = 12, None
            while len(self.buffer) >= offset + 8:
                kind, size = bytes(self.buffer[offset:offset + 4]), struct.unpack_from('<I', self.buffer, offset + 4)[0]
                if kind == b'data':
                    if fmt != (1, 1, 24000, 16):
                        raise PocFailure('POC_TTS_FORMAT_UNSUPPORTED')
                    self.buffer = self.buffer[offset + 8:]
                    self.remaining = size if size not in (0, 0xFFFFFFFF, 0x7FFFFFFF) else None
                    self.ready = True
                    break
                if len(self.buffer) < offset + 8 + size:
                    return b''
                if kind == b'fmt ' and size >= 16:
                    format_id, channels, rate, _, _, bits = struct.unpack_from('<HHIIHH', self.buffer, offset + 8)
                    fmt = (format_id, channels, rate, bits)
                offset += 8 + size + size % 2
            if not self.ready:
                return b''
        count = len(self.buffer) if self.remaining is None else min(len(self.buffer), self.remaining)
        count -= count % 2
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        if self.remaining is not None:
            self.remaining -= count
        return result


async def paced_audio(pcm, send):
    started = time.monotonic()
    for offset in range(0, len(pcm), FRAME_BYTES):
        # Send a frame after its capture time, rather than uploading a file fast.
        chunk = pcm[offset:offset + FRAME_BYTES]
        await asyncio.sleep(max(0, started + (offset + len(chunk)) / 32000 - time.monotonic()))
        await send(chunk)
    return started


class Qwen:
    def __init__(self, ws, observation=None):
        self.ws = ws
        self.observation = observation
        self.transcripts = asyncio.Queue()
        self.speeches = {}
        self.revoked = set()
        self.old_after_interrupt_bytes = 0
        self.failure = None
        self.reader = asyncio.create_task(self.read())

    async def send(self, kind, **values):
        await self.ws.send(json.dumps(dict(type=kind, **values), ensure_ascii=False))

    async def read(self):
        try:
            async for raw in self.ws:
                event = json.loads(raw)
                kind = event['type']
                if kind == 'error':
                    raise PocFailure(event.get('code', 'QWEN_BRIDGE_ERROR'))
                if kind == 'transcript':
                    self.transcripts.put_nowait(event)
                sid = event.get('speech_id')
                if sid in self.revoked:
                    if kind == 'audio':
                        self.old_after_interrupt_bytes += len(base64.b64decode(event['audio'], validate=True))
                    continue
                if sid in self.speeches:
                    self.speeches[sid].put_nowait(event)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failure = error
            for queue in [self.transcripts, *self.speeches.values()]:
                queue.put_nowait(error)

    async def transcribe(self, pcm, item):
        uid = str(uuid4())
        started = await paced_audio(pcm + b'\0' * int(TAIL_SECONDS * 32000),
                                    lambda chunk: self.send('audio', audio=base64.b64encode(chunk).decode()))
        committed = time.monotonic()
        await self.send('commit_audio', utterance_id=uid, generation=1)
        event = await asyncio.wait_for(self.transcripts.get(), 50)
        if isinstance(event, Exception):
            raise event
        if event['utterance_id'] != uid:
            raise PocFailure('POC_TRANSCRIPT_BINDING')
        finished = time.monotonic()
        return dict(transcript=event['text'], after_commit_ms=round((finished - committed) * 1000),
                    after_last_voice_ms=round((finished - started) * 1000 - item['last_voice_ms']),
                    boundary_mode='controlled manual commit after current 1.65 s pause; native VAD not executed')

    async def speak(self, text, sink, sid):
        if self.failure:
            raise self.failure
        if self.observation:
            self.observation['started'].clear()
            self.observation['completed'].clear()
        queue = self.speeches[sid] = asyncio.Queue()
        await self.send('speak', text=text, speech_id=sid)
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), 50)
                if isinstance(event, Exception):
                    raise event
                if event['type'] == 'speech_blocked':
                    raise PocFailure('QWEN_AUTHORIZED_TEXT_MISMATCH')
                if event['type'] == 'audio':
                    sink.feed(base64.b64decode(event['audio'], validate=True))
                elif event['type'] == 'speech_done':
                    return {'sample_rate': 24000, 'voice_id': 'Tina', 'streaming_audio_released_after_text_verification': True}
        finally:
            self.speeches.pop(sid, None)

    async def interrupt(self, sid, task):
        self.revoked.add(sid)
        await self.send('interrupt')
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def close(self):
        await self.send('close')
        self.reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.reader


class Voxtral:
    def __init__(self, key, context, voice_id=None):
        self.key, self.context, self.voice_id = key, context, voice_id
        self.http = httpx.AsyncClient(base_url=MISTRAL_ORIGIN, headers={'Authorization': 'Bearer ' + key},
                                     verify=context, timeout=httpx.Timeout(50, connect=12))

    async def catalog(self):
        response = await self.http.get('/v2/audio/voices', params={'type': 'preset', 'language': 'zh', 'page_size': 100})
        response.raise_for_status()
        data = response.json()
        voices = [{k: v.get(k) for k in ('id', 'slug', 'name', 'languages', 'type')} for v in data.get('data', [])]
        chinese = [v for v in voices if v.get('type') == 'preset' and any(
            str(lang).lower().startswith(('zh', 'cmn', 'chinese', 'mandarin')) for lang in v.get('languages') or [])]
        if self.voice_id:
            chosen = next((v for v in chinese if self.voice_id in (v['id'], v['slug'])), None)
        else:
            chosen = chinese[0] if chinese else None
        self.voice_id = (chosen['slug'] or chosen['id']) if chosen else None
        return dict(voices=voices, selected_voice=chosen, next_page_present=bool(data.get('next_page_token')))

    async def transcribe(self, pcm, item):
        opened = time.monotonic()
        url = 'wss://api.mistral.ai/v1/audio/transcriptions/realtime?model=' + ASR_MODEL
        async with connect(url, additional_headers={'Authorization': 'Bearer ' + self.key}, ssl=self.context,
                           open_timeout=12, close_timeout=2, max_size=4_000_000) as ws:
            initial = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if initial.get('type') != 'session.created':
                raise PocFailure('VOXTRAL_SESSION_NOT_CREATED')
            await ws.send(json.dumps({'type': 'session.update', 'session': {
                'audio_format': {'encoding': 'pcm_s16le', 'sample_rate': 16000},
                'target_streaming_delay_ms': STREAM_DELAY_MS, 'language': 'zh', 'turn_detection': {}}}))
            setup = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if setup.get('type') != 'session.updated':
                raise PocFailure('VOXTRAL_SESSION_NOT_CONFIGURED')
            connected_ms = round((time.monotonic() - opened) * 1000)
            started = time.monotonic()
            text, turns, delayed = [], [], []
            first_text_ms, committed = None, None

            async def snapshot(turn):
                await asyncio.sleep(STREAM_DELAY_MS / 1000)
                turn['text_after_streaming_delay'] = ''.join(text)
                turn['text_snapshot_ms'] = round((time.monotonic() - started) * 1000)

            async def send():
                nonlocal committed
                await paced_audio(pcm + b'\0' * int(TAIL_SECONDS * 32000), lambda chunk: ws.send(json.dumps(
                    {'type': 'input_audio.append', 'audio': base64.b64encode(chunk).decode()})))
                committed = time.monotonic()
                await ws.send(json.dumps({'type': 'input_audio.end'}))

            sender = asyncio.create_task(send())
            try:
                async with asyncio.timeout(len(pcm) / 32000 + 55):
                    async for raw in ws:
                        event = json.loads(raw)
                        kind = event.get('type')
                        elapsed = round((time.monotonic() - started) * 1000)
                        if kind == 'error':
                            raise PocFailure('VOXTRAL_TRANSCRIPTION_ERROR')
                        if kind == 'transcription.text.delta':
                            text.append(event['text'])
                            first_text_ms = elapsed if first_text_ms is None else first_text_ms
                        if kind in {'turn.start', 'turn.eager_end', 'turn.resume', 'turn.end'}:
                            turn = dict(type=kind, received_ms=elapsed, audio_time_s=event.get('time_s'),
                                        end_reason=event.get('end_reason'), text_at_event=''.join(text))
                            turns.append(turn)
                            if kind == 'turn.end':
                                delayed.append(asyncio.create_task(snapshot(turn)))
                        if kind == 'transcription.done':
                            finished = time.monotonic()
                            await sender
                            await asyncio.gather(*delayed)
                            return dict(transcript=event.get('text', ''.join(text)), connection_ms=connected_ms,
                                        first_text_ms=first_text_ms, after_commit_ms=round((finished - committed) * 1000),
                                        after_last_voice_ms=round((finished - started) * 1000 - item['last_voice_ms']),
                                        turn_events=turns, usage=event.get('usage'), configured_session=setup.get('session'))
            finally:
                sender.cancel()
                for task in delayed:
                    task.cancel()
                await asyncio.gather(sender, *delayed, return_exceptions=True)
        raise PocFailure('VOXTRAL_NO_FINAL_TRANSCRIPT')

    async def speak(self, text, sink, sid):
        if not self.voice_id:
            raise PocFailure('VOXTRAL_CHINESE_PRESET_UNAVAILABLE')
        decoder = WaveStream()
        async with self.http.stream('POST', '/v1/audio/speech', json=dict(
            model=TTS_MODEL, input=text, voice_id=self.voice_id, response_format='wav', stream=True)) as response:
            response.raise_for_status()
            event_name, data = '', []
            async for line in response.aiter_lines():
                if line.startswith('event:'):
                    event_name = line[6:].strip()
                elif line.startswith('data:'):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    payload = json.loads('\n'.join(data))
                    kind = payload.get('type', event_name)
                    if kind == 'speech.audio.delta':
                        chunk = decoder.feed(base64.b64decode(payload['audio_data'], validate=True))
                        if chunk:
                            sink.feed(chunk)
                    elif kind == 'speech.audio.done':
                        return dict(sample_rate=24000, voice_id=self.voice_id, usage=payload.get('usage'),
                                    streaming_audio_released_after_text_verification=False)
                    elif kind == 'error':
                        raise PocFailure('VOXTRAL_TTS_ERROR')
                    data, event_name = [], ''
        raise PocFailure('VOXTRAL_TTS_NO_DONE_EVENT')

    async def interrupt(self, sid, task):
        if not task.done():
            task.cancel()  # closes HTTP stream; remote cancellation ACK is unknown
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def close(self):
        await self.http.aclose()


async def compare(adapter, vendor, manifest, output, report, ledger, report_path, *, generation_only=False):
    async def stage(name, operation, call, *, seconds=0, chars=0):
        if name in report['stages']:
            return
        charge = ledger.charge(vendor, operation, seconds=seconds, chars=chars)
        stage_started = time.monotonic()
        try:
            result = await call()
            report['stages'][name] = dict(status='observed', **result)
            ledger.finish(charge, 'completed')
        except Exception as error:
            report['stages'][name] = dict(status='failed', error=safe_failure(error))
            ledger.finish(charge, 'failed')
        report['stages'][name]['stage_elapsed_ms'] = round((time.monotonic() - stage_started) * 1000)
        dump(report_path, report)
        print(json.dumps(dict(provider=vendor, stage=name, **report['stages'][name]), ensure_ascii=False), flush=True)

    for item in ([] if generation_only else manifest):
        async def transcribe(item=item):
            with wave.open(str(output / item['file'])) as audio:
                pcm = audio.readframes(audio.getnframes())
            result = await adapter.transcribe(pcm, item)
            return dict(reference=item['reference'], input_sha256=item['sha256'], **result,
                        normalized_cer=cer(item['reference'], result['transcript']), semantic_review='pending')
        await stage('asr_' + item['name'], 'transcribe', transcribe,
                    seconds=item['input_seconds'] + TAIL_SECONDS)
        if adapter.__class__ is Qwen and adapter.failure:
            break
        failure = report['stages']['asr_' + item['name']].get('error', {})
        if failure.get('http_status') in (401, 403, 404) or failure.get('code') in {
                'VOXTRAL_SESSION_NOT_CREATED', 'VOXTRAL_SESSION_NOT_CONFIGURED'}:
            report['asr_remaining_blocked'] = 'Model authorization/configuration failed; other corpus cases were not retried.'
            break
    if vendor == 'voxtral' and not adapter.voice_id:
        report['tts_blocked'] = 'No verified Chinese preset available in current API catalog; no English/clone fallback.'
        dump(report_path, report)
        return
    for name, text in ([] if generation_only else READOUTS):
        async def speak(name=name, text=text):
            sink, sid = PlaybackSink(), str(uuid4())
            started = time.monotonic()
            result = await adapter.speak(text, sink, sid)
            finished = time.monotonic()
            if not sink.pcm:
                raise PocFailure('POC_EMPTY_TTS')
            path = output / f'{vendor}-tts-{name}.wav'
            write_wav(path, sink.pcm, 24000)
            return dict(text=text, **result, first_playable_audio_ms=round((sink.first_at - started) * 1000),
                        completed_ms=round((finished - started) * 1000), output_seconds=len(sink.pcm) / 48000,
                        audio_file=path.name, audio_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        acoustic_and_naturalness_review='pending; no speaker was opened')
        await stage('tts_' + name, 'speak', speak, chars=len(text))

    async def interruption():
        sink, sid = PlaybackSink(), str(uuid4())
        started = time.monotonic()
        task = asyncio.create_task(adapter.speak(INTERRUPT_TEXT, sink, sid))
        first = asyncio.create_task(sink.first.wait())
        try:
            done, _ = await asyncio.wait((first, task), timeout=50, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise PocFailure('POC_NO_AUDIO_TO_INTERRUPT')
            if task.done():
                await task  # surface mismatch/transport errors before waiting
            await asyncio.wait_for(first, 50)
            await asyncio.sleep(.6)
            triggered = time.monotonic()
            queued = sink.stop()
            accepted = sink.accepted_bytes
            if queued <= 0:
                raise PocFailure('POC_INTERRUPTION_NOT_DURING_PLAYBACK')
            await adapter.interrupt(sid, task)
            cancelled = time.monotonic()
            await asyncio.sleep(.5)
            if sink.pending or sink.accepted_bytes != accepted:
                raise PocFailure('POC_STALE_PLAYBACK_ESCAPED')
            return dict(trigger='600 ms after first playable audio; simulated local queue',
                        first_playable_audio_ms=round((sink.first_at - started) * 1000),
                        triggered_ms=round((triggered - started) * 1000), cleared_queued_ms=round(queued / 48),
                        cancel_task_settled_ms=round((cancelled - triggered) * 1000),
                        old_late_pcm_discarded_bytes=sink.late_discarded_bytes,
                        old_pcm_accepted_after_interrupt=0, remote_cancel_ack='not measured',
                        provider_generation_already_finished=task.done() and not task.cancelled())
        finally:
            first.cancel()
            if not task.done():
                await adapter.interrupt(sid, task)
            await asyncio.gather(first, task, return_exceptions=True)
    if not generation_only:
        await stage('interrupt_playback', 'interrupt_speech', interruption, chars=len(INTERRUPT_TEXT))

    async def recover(*, suffix='after-interrupt'):
        sink = PlaybackSink()
        started = time.monotonic()
        result = await adapter.speak(RECOVERY_TEXT, sink, str(uuid4()))
        if not sink.pcm:
            raise PocFailure('POC_RECOVERY_EMPTY')
        path = output / f'{vendor}-{suffix}.wav'
        if path.exists():
            raise PocFailure('POC_AUDIO_ARTIFACT_ALREADY_EXISTS')
        write_wav(path, sink.pcm, 24000)
        return dict(**result, text=RECOVERY_TEXT, first_playable_audio_ms=round((sink.first_at - started) * 1000),
                    audio_file=path.name, audio_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    old_late_transport_bytes_discarded=getattr(adapter, 'old_after_interrupt_bytes', None))
    if not generation_only:
        await stage('after_interrupt', 'recovery_speech', recover, chars=len(RECOVERY_TEXT))

    async def generation_interrupt():
        sink, sid = PlaybackSink(), str(uuid4())
        task = asyncio.create_task(adapter.speak(INTERRUPT_TEXT, sink, sid))
        started = time.monotonic()
        try:
            deadline = started + 40
            while True:
                if task.done():
                    await task
                    raise PocFailure('POC_GENERATION_FINISHED_BEFORE_CANCEL_PROBE')
                if isinstance(adapter, Qwen):
                    observed = adapter.observation['started'].is_set() and not adapter.observation['completed'].is_set()
                else:
                    observed = sink.first.is_set()
                if observed:
                    break
                if time.monotonic() > deadline:
                    raise PocFailure('POC_NO_GENERATION_PROGRESS')
                await asyncio.sleep(.005)
            triggered = time.monotonic()
            playable_before = sink.accepted_bytes
            queued = sink.stop()
            await adapter.interrupt(sid, task)
            settled = time.monotonic()
            await asyncio.sleep(.5)
            return dict(trigger='observed upstream PCM before text verification' if isinstance(adapter, Qwen)
                        else 'first playable PCM while HTTP stream task is active; remote generation state unknown',
                        observed_progress_ms=round((triggered - started) * 1000),
                        playable_bytes_before_cancel=playable_before, cleared_queued_ms=round(queued / 48),
                        cancel_task_settled_ms=round((settled - triggered) * 1000),
                        old_pcm_accepted_after_interrupt=sink.accepted_bytes - playable_before,
                        local_task_cancelled=task.cancelled(), remote_cancel_ack='not measured')
        finally:
            if not task.done():
                await adapter.interrupt(sid, task)
            await asyncio.gather(task, return_exceptions=True)
    await stage('interrupt_generation', 'cancel_active_generation', generation_interrupt, chars=len(INTERRUPT_TEXT))
    await stage('after_generation_interrupt', 'recovery_after_generation_cancel',
                lambda: recover(suffix='after-generation-interrupt'), chars=len(RECOVERY_TEXT))


async def live(args, manifest):
    output, vendor = args.output, args.provider
    report_path = output / f'{vendor}-report.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else dict(
        provider=vendor, started_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        microphone_used=False, speaker_used=False, text_agent_calls=0, daily_database_opened=False,
        stage_results_are_not_product_acceptance=True, protected_before=protected_hashes(), stages={})
    ledger = Ledger(output / 'ledger.json')
    if report.get('finished_at') and (not args.generation_only or 'interrupt_generation' in report['stages']):
        print(json.dumps(dict(provider=vendor, status='preserved completed or blocked report; use a new authorized batch to retry')), flush=True)
        return
    if args.generation_only:
        report['generation_probe_started_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    from agent_service.certs import ssl_context
    context = ssl_context()
    try:
        if vendor == 'voxtral':
            values = dotenv_values(ROOT / 'agent-service/providers/voxtral/.env')
            key = os.getenv('MISTRAL_API_KEY') or values.get('MISTRAL_API_KEY') or ''
            if not key.strip():
                report['blocked'] = 'MISTRAL_API_KEY_NOT_CONFIGURED'
                dump(report_path, report)
                return
            report.pop('blocked', None)
            adapter = Voxtral(key.strip(), context, values.get('MISTRAL_VOICE_ID'))
            charge = ledger.charge(vendor, 'list_chinese_preset_voices')
            try:
                report['voice_catalog'] = await adapter.catalog()
                ledger.finish(charge, 'completed')
                report.pop('blocked', None)
                await compare(adapter, vendor, manifest, output, report, ledger, report_path, generation_only=args.generation_only)
            finally:
                await adapter.close()
        else:
            # Isolation MUST precede the first production-module import.
            with tempfile.TemporaryDirectory(prefix='review-today-voice-poc-') as scratch:
                os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(scratch) / 'harness.sqlite3')
                os.environ['REVIEW_TODAY_REVIEW_DB'] = str(Path(scratch) / 'review.sqlite3')
                os.environ['REVIEW_TODAY_JEV_TEST'] = '0'
                import uvicorn
                from fastapi import FastAPI
                from agent_service import agent_voice as voice
                if Path(voice.conversation_store.tasks.path).resolve() != (Path(scratch) / 'harness.sqlite3').resolve():
                    raise PocFailure('POC_DATABASE_ISOLATION')
                from agent_service import review_sessions
                if Path(review_sessions.store.path).resolve() != (Path(scratch) / 'review.sqlite3').resolve():
                    raise PocFailure('POC_REVIEW_DATABASE_ISOLATION')
                observation = dict(started=threading.Event(), completed=threading.Event(), readouts=[])
                original_buffer = voice.SpeechBuffer
                class ObservedSpeechBuffer(original_buffer):
                    # Read-only observation in this isolated process; the actual
                    # production match/release decision is always delegated.
                    def append_audio(self, encoded):
                        super().append_audio(encoded)
                        observation['started'].set()

                    def matches(self):
                        matched = super().matches()
                        observation['readouts'].append(dict(expected=self.expected, provider_text=self.text, matched=matched))
                        observation['completed'].set()
                        return matched
                voice.SpeechBuffer = ObservedSpeechBuffer
                report['isolated_harness_path'] = os.environ['REVIEW_TODAY_HARNESS_DB']
                report['model'] = voice.MODEL
                app = FastAPI()
                app.include_router(voice.router)
                sock = socket.socket()
                sock.bind(('127.0.0.1', 0))
                report['isolated_port'] = sock.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
                thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
                thread.start()
                try:
                    deadline = time.monotonic() + 8
                    while not server.started:
                        if time.monotonic() > deadline:
                            raise PocFailure('POC_LOCAL_SERVER_NOT_READY')
                        await asyncio.sleep(.02)
                    charge = ledger.charge(vendor, 'open_provider_connection')
                    started = time.monotonic()
                    async with connect(f'ws://127.0.0.1:{report["isolated_port"]}/v2/agent/voice/{uuid4()}/audio', proxy=None) as ws:
                        ready = json.loads(await asyncio.wait_for(ws.recv(), 20))
                        if ready.get('type') != 'ready':
                            raise PocFailure(ready.get('code', 'QWEN_NOT_READY'))
                        ledger.finish(charge, 'completed')
                        report['connection_ms'] = round((time.monotonic() - started) * 1000)
                        adapter = Qwen(ws, observation)
                        try:
                            await compare(adapter, vendor, manifest, output, report, ledger, report_path, generation_only=args.generation_only)
                        finally:
                            await adapter.close()
                finally:
                    server.should_exit = True
                    await asyncio.to_thread(thread.join, 8)
                    if thread.is_alive():
                        raise PocFailure('POC_LOCAL_SERVER_NOT_STOPPED')
                with voice.conversation_store.tasks._connection() as db:
                    report.setdefault('voice_usage', []).extend([dict(model=r[0], duration_ms=r[1], calls=r[2], input_bytes=r[3],
                                                 output_bytes=r[4], usage=json.loads(r[5]))
                                             for r in db.execute('SELECT * FROM agent_voice_usage')])
                report.setdefault('provider_readout_checks', []).extend(observation['readouts'])
    except Exception as error:
        report['error'] = safe_failure(error)
        if 'charge' in locals() and charge['status'] == 'started':
            ledger.finish(charge, 'failed')
    finally:
        report['protected_after'] = protected_hashes()
        report['protected_unchanged'] = report['protected_before'] == report['protected_after']
        report['operations_charged'] = sum(e['vendor'] == vendor for e in ledger.entries)
        if report.get('blocked') != 'MISTRAL_API_KEY_NOT_CONFIGURED':
            report['finished_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        dump(report_path, report)
        print(json.dumps(dict(provider=vendor, stages=len(report['stages']), blocked=report.get('blocked'),
                              error=report.get('error'), protected_unchanged=report['protected_unchanged'],
                              report=str(report_path)), ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--provider', choices=('qwen', 'voxtral'))
    parser.add_argument('--generation-only', action='store_true', help='Append one not-yet-run generation cancellation probe, preserving the original stages and shared budget')
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not args.output.is_relative_to((ROOT / 'output').resolve()):
        parser.error('POC artifacts must stay inside this repository output/ directory')
    if args.live != bool(args.provider):
        parser.error('--live and --provider must be specified together')
    if args.generation_only and not args.live:
        parser.error('--generation-only requires an explicit live provider')
    manifest = prepare(args.output)
    print(json.dumps(dict(fixtures=len(manifest), input_seconds=round(sum(x['input_seconds'] for x in manifest), 3),
                          output=str(args.output), microphone_used=False, speaker_used=False), ensure_ascii=False), flush=True)
    if args.live:
        asyncio.run(live(args, manifest))


if __name__ == '__main__':
    main()
