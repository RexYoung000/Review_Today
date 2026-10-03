"""Explicit paid smoke using synthetic speech, an isolated DB and private port.

    .venv/bin/python -m tests.agent_voice_live --live --output /tmp/new-report.json

Never opens a microphone or audio output. Temporary synthesized WAV files are
removed immediately after loading; reports retain text, timings and usage only.
Actual response semantics and conversational naturalness require human review.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading
import time
from uuid import uuid4
import wave


INPUTS = [
    '接下来只讨论光合作用，请先用一句话说明它做什么。',
    '那它的原料和能量分别是什么？',
    '请用一句话把我们刚才讨论的过程串起来。',
]


def synthesize(text, scratch):
    path = Path(scratch) / (str(uuid4()) + '.wav')
    try:
        subprocess.run(['/usr/bin/say', '-v', 'Tingting', '-o', str(path),
                        '--file-format=WAVE', '--data-format=LEI16@16000', text],
                       check=True, capture_output=True)
        with wave.open(str(path)) as audio:
            assert audio.getnchannels() == 1 and audio.getframerate() == 16000 and audio.getsampwidth() == 2
            return audio.readframes(audio.getnframes())
    finally:
        path.unlink(missing_ok=True)


async def exercise(port, scratch, report, dialogue_report):
    from websockets.asyncio.client import connect
    from agent_service import agent_voice as voice
    from agent_service.conversation import ConversationHarness
    from agent_service.schemas import SessionMessageRequest
    from tests.case_library.recording import RunReport

    sid = str(uuid4())
    report['owner_id'] = sid
    harness = ConversationHarness(voice.conversation_store)
    started = time.monotonic()
    with RunReport(dialogue_report, layer='live_generated_flow', planned=['turn1', 'turn2', 'turn3'],
                   fixture=dict(initial_input=INPUTS[0], input_channel='voice', synthetic=True,
                                purpose='Three voice turns on one Agent Session; no microphone or playback',
                                semantic_review='pending; inspect raw transcripts, model context and replies')) as records:
        async with connect(f'ws://127.0.0.1:{port}/v2/agent/voice/{sid}/audio', proxy=None) as ws:
            async def send(kind, **fields):
                await ws.send(json.dumps(dict(type=kind, **fields), ensure_ascii=False))

            async def receive():
                event = json.loads(await asyncio.wait_for(ws.recv(), 60))
                if event['type'] in {'error', 'speech_blocked'}:
                    raise RuntimeError(event['code'])
                return event

            ready = await receive()
            assert ready['type'] == 'ready'
            report['ready_ms'] = round((time.monotonic() - started) * 1000)
            assert harness.store.get(sid) is None
            report['opening_does_not_create_session'] = True

            async def play(text, *, forbidden=None):
                speech = str(uuid4())
                await send('speak', text=text, speech_id=speech)
                clock = time.monotonic()
                result = dict(text=text, speech_id=speech, bytes=0)
                while True:
                    event = await receive()
                    if forbidden:
                        assert event.get('speech_id') not in forbidden, 'interrupted speech escaped its binding'
                    if event['type'] == 'audio':
                        assert event['speech_id'] == speech
                        if not result['bytes']:
                            result['first_audio_ms'] = round((time.monotonic() - clock) * 1000)
                        result['bytes'] += len(base64.b64decode(event['audio'], validate=True))
                    elif event['type'] == 'speech_done':
                        assert event['speech_id'] == speech and result['bytes'] > 0
                        result['completed_ms'] = round((time.monotonic() - clock) * 1000)
                        result['audio_seconds'] = result['bytes'] / 48_000
                        return result

            report['turns'] = []
            for index, synthetic in enumerate(INPUTS, 1):
                item = dict(index=index, synthetic_input=synthetic)
                report['turns'].append(item)
                pcm = await asyncio.to_thread(synthesize, synthetic, scratch)
                item['input_seconds'] = len(pcm) / 32_000
                uid = str(uuid4())
                for offset in range(0, len(pcm), 3200):
                    await send('audio', audio=base64.b64encode(pcm[offset:offset + 3200]).decode())
                    await asyncio.sleep(.01)
                clock = time.monotonic()
                await send('commit_audio', utterance_id=uid, generation=index)
                if index == 1:
                    # Muting after the commit must preserve that submitted input.
                    await send('clear', cancel_transcripts=False)
                while True:
                    event = await receive()
                    if event['type'] == 'transcript':
                        assert event['utterance_id'] == uid and event['generation'] == index
                        item['transcript'] = event['text']
                        item['transcription_ms'] = round((time.monotonic() - clock) * 1000)
                        assert event['text'].strip(), 'synthetic spoken input returned no transcript'
                        break
                body = SessionMessageRequest(client_message_id=uid, content=item['transcript'], input_channel='voice')
                clock = time.monotonic()
                record = await asyncio.to_thread(records.turn, harness, sid, body)
                item['agent_ms'] = round((time.monotonic() - clock) * 1000)
                item['run_status'] = record['run']['status']
                item['replies'] = record['replies']
                checks = dict(same_session=record['after']['session_id'] == sid,
                    voice_channel=record['run'].get('input_channel') == 'voice',
                    exact_transcript=any(m['message_id'] == uid and m['content'] == item['transcript']
                                         for m in record['after']['messages']),
                    prior_messages_retained=len([m for m in record['after']['messages'] if m['role'] == 'user']) == index)
                records.add('turn' + str(index), record, checks)
                assert record['run']['status'] == 'completed' and record['replies'], 'Agent did not complete this turn'
                item['spoken_sentences'] = []
                # Use actual Agent prose and preserve it in the evidence. This
                # smoke exercises transport, not the Mac sentence splitter.
                prose = '\n'.join(record['replies'])
                sentences = [s.strip() for s in re.findall(r'[^。！？!?\n]+[。！？!?]?', prose) if s.strip()]
                for sentence in sentences[:2]:
                    for offset in range(0, len(sentence), 120):
                        item['spoken_sentences'].append(await play(sentence[offset:offset + 120]))
                print(json.dumps(dict(turn=index, transcript=item['transcript'], replies=item['replies'],
                                      transcription_ms=item['transcription_ms'], agent_ms=item['agent_ms'],
                                      speech_first_ms=[s['first_audio_ms'] for s in item['spoken_sentences']]), ensure_ascii=False), flush=True)

            old, queued = str(uuid4()), str(uuid4())
            await send('speak', text='这是一段用于验证停止播报的合成句子。' * 8, speech_id=old)
            await send('speak', text='这句排队内容应该被一起清除。', speech_id=queued)
            await asyncio.sleep(.25)
            await send('interrupt')
            report['after_interrupt'] = await play('现在继续。', forbidden={old, queued})
            await send('close')
    report['agent_structural_pass'] = records.passed
    async with connect(f'ws://127.0.0.1:{port}/v2/agent/voice/{sid}/audio', proxy=None) as ws:
        event = json.loads(await asyncio.wait_for(ws.recv(), 20))
        assert event['type'] == 'ready'
        report['reconnect_ready'] = True
        await ws.send(json.dumps({'type': 'close'}))
    report['synthetic_messages'] = len([m for m in harness.store.get(sid)['messages'] if m['role'] == 'user'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    detail = args.output.with_suffix('.agent.jsonl')
    if args.output.exists() or detail.exists():
        parser.error('use new output and companion .agent.jsonl paths')
    report = dict(synthetic=True, audio_retained=False, microphone_used=False, audio_played=False,
                  semantic_review='pending; no keyword-based semantic pass',
                  limitations=['No real microphone, echo, speaker or conversational-pause measurement',
                               'Only provider-reported numeric token usage is retained; no pricing estimate'])
    with tempfile.TemporaryDirectory(prefix='review-today-agent-voice-live-') as scratch:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(scratch) / 'synthetic.sqlite3')
        os.environ['REVIEW_TODAY_JEV_TEST'] = '0'
        # Imports after isolation: module-level stores never see the daily DB.
        import uvicorn
        from fastapi import FastAPI
        from agent_service import agent_voice as voice
        app = FastAPI()
        app.include_router(voice.router)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError('isolated server did not start')
            time.sleep(.02)
        report['model'] = voice.MODEL
        report['started_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        try:
            asyncio.run(exercise(port, scratch, report, detail))
            report['passed'] = bool(report['agent_structural_pass'])
        except Exception as error:
            report['passed'] = False
            # No upstream response/credentials are exposed by an exception dump.
            report['error_type'] = type(error).__name__
            safe = str(error)
            if re.fullmatch(r'RT\.[A-Z_.]+', safe):
                report['error_code'] = safe
        finally:
            server.should_exit = True
            thread.join(timeout=8)
            with voice.conversation_store.tasks._connection() as db:
                table = db.execute("SELECT 1 FROM sqlite_master WHERE name='agent_voice_usage'").fetchone()
                report['voice_usage'] = [dict(model=r[0], duration_ms=r[1], calls=r[2], input_bytes=r[3], output_bytes=r[4], usage=json.loads(r[5]))
                                         for r in db.execute('SELECT * FROM agent_voice_usage')] if table else []
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x') as output:
                json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps(dict(passed=report['passed'], report=str(args.output), dialogue_report=str(detail),
                          error_type=report.get('error_type'), error_code=report.get('error_code')), ensure_ascii=False), flush=True)
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
