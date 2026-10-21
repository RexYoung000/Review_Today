"""Offline safeguards for a benchmark whose measurements drive a product choice."""
import asyncio
import io
import json
import wave

import pytest

from tests.voice_provider_poc import ASR_MODEL, TTS_MODEL, Ledger, PlaybackSink, PocFailure, Voxtral, WaveStream, cer, paced_audio


def test_budget_persists_and_counts_failed_attempts_before_another_request(tmp_path):
    path = tmp_path / 'ledger.json'
    ledger = Ledger(path)
    for i in range(16):
        item = ledger.charge('voxtral', 'attempt_' + str(i), seconds=1, chars=1)
        ledger.finish(item, 'failed' if i % 2 else 'cancelled')
    with pytest.raises(PocFailure, match='POC_BUDGET_EXHAUSTED'):
        Ledger(path).charge('voxtral', 'unauthorized_retry')
    assert len(json.loads(path.read_text())) == 16
    # Other experiments/vendors cannot consume or silently reset this ledger.
    assert Ledger(path).charge('qwen', 'first')['vendor'] == 'qwen'


@pytest.mark.parametrize('first,second', [({'seconds': 149}, {'seconds': 2}), ({'chars': 1199}, {'chars': 2})])
def test_audio_and_text_caps_reject_before_charge(tmp_path, first, second):
    ledger = Ledger(tmp_path / 'ledger.json')
    ledger.charge('qwen', 'first', **first)
    with pytest.raises(PocFailure, match='POC_BUDGET_EXHAUSTED'):
        ledger.charge('qwen', 'overflow', **second)
    assert len(ledger.entries) == 1


def test_speech_bytes_are_not_playable_until_a_valid_complete_wav_header():
    pcm = b'\x01\0\x02\0' * 100
    file = io.BytesIO()
    with wave.open(file, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(pcm)
    encoded = file.getvalue()
    decoder = WaveStream()
    observed = b''
    for i, byte in enumerate(encoded):
        chunk = decoder.feed(bytes([byte]))
        if i < 44:
            assert not chunk
        observed += chunk
    assert observed == pcm
    with pytest.raises(PocFailure, match='POC_TTS_NOT_WAV'):
        WaveStream().feed(b'HTTP ERROR PAGE')


def test_interrupt_discards_an_entire_queued_old_clip_and_late_chunks():
    async def exercise():
        sink = PlaybackSink()
        sink.feed(b'\0' * 48000)
        assert sink.first.is_set()
        assert sink.stop() > 0
        accepted = sink.accepted_bytes
        sink.feed(b'\0' * 48000)
        assert sink.pending == 0
        assert sink.accepted_bytes == accepted
        assert sink.late_discarded_bytes == 48000
    asyncio.run(exercise())


def test_audio_is_sent_at_capture_pace_instead_of_accelerated_file_upload():
    async def exercise():
        import time
        times = []
        async def collect(chunk):
            times.append(time.monotonic())
        started = await paced_audio(b'\0' * 6400, collect)
        assert len(times) == 2
        assert times[0] - started >= .09
        assert times[1] - started >= .19
    asyncio.run(exercise())


def test_error_rate_keeps_negation_and_normalizes_punctuation_only():
    assert cer('先不要保存。', '先不要保存！') == 0
    assert cer('先不要保存。', '先要保存。') > 0
    assert cer('API', 'api') == 0


def test_voxtral_uses_a_catalog_verified_chinese_preset_and_real_sse_wav_bytes():
    async def exercise():
        import base64
        import httpx
        import ssl
        pcm = b'\1\0' * 2400
        file = io.BytesIO()
        with wave.open(file, 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(pcm)
        encoded = file.getvalue()
        requests = []
        def respond(request):
            requests.append(request)
            assert request.url.host == 'api.mistral.ai'
            assert request.headers['authorization'] == 'Bearer fake-offline-key'
            if request.method == 'GET':
                return httpx.Response(200, json={'data': [
                    {'id': 'en-1', 'slug': 'en_voice', 'languages': ['en'], 'type': 'preset'},
                    {'id': 'zh-1', 'slug': 'zh_voice', 'languages': ['zh_cn'], 'type': 'preset'},
                ], 'next_page_token': None})
            body = json.loads(request.content)
            assert body['model'] == TTS_MODEL and body['voice_id'] == 'zh_voice'
            assert body['stream'] is True and body['response_format'] == 'wav'
            events = []
            for chunk in (encoded[:27], encoded[27:63], encoded[63:]):
                events.append('event: speech.audio.delta\ndata: ' + json.dumps({'audio_data': base64.b64encode(chunk).decode()}) + '\n\n')
            events.append('event: speech.audio.done\ndata: {"usage":{"characters":3}}\n\n')
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=''.join(events))
        adapter = Voxtral('fake-offline-key', ssl.create_default_context())
        await adapter.http.aclose()
        adapter.http = httpx.AsyncClient(base_url='https://api.mistral.ai',
            headers={'Authorization': 'Bearer fake-offline-key'}, transport=httpx.MockTransport(respond))
        try:
            catalog = await adapter.catalog()
            assert catalog['selected_voice']['id'] == 'zh-1'
            sink = PlaybackSink()
            result = await adapter.speak('你好。', sink, 'synthetic-id')
            assert sink.pcm == pcm and result['usage']['characters'] == 3
            assert len(requests) == 2
        finally:
            await adapter.close()
    asyncio.run(exercise())


def test_english_only_catalog_blocks_chinese_tts_without_a_paid_generation():
    async def exercise():
        import httpx
        import ssl
        calls = []
        def respond(request):
            calls.append(request.method)
            return httpx.Response(200, json={'data': [{'id': 'en', 'slug': 'en', 'type': 'preset', 'languages': ['en']}], 'next_page_token': None})
        adapter = Voxtral('fake-offline-key', ssl.create_default_context())
        await adapter.http.aclose()
        adapter.http = httpx.AsyncClient(base_url='https://api.mistral.ai', transport=httpx.MockTransport(respond))
        try:
            await adapter.catalog()
            assert adapter.voice_id is None
            with pytest.raises(PocFailure, match='VOXTRAL_CHINESE_PRESET_UNAVAILABLE'):
                await adapter.speak('你好。', PlaybackSink(), 'id')
            assert calls == ['GET']
        finally:
            await adapter.close()
    asyncio.run(exercise())
