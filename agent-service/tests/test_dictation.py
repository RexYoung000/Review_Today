import io
import wave
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from agent_service import dictation as d


def wav(seconds=.2, amplitude=1000):
    out = io.BytesIO()
    with wave.open(out, 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000)
        f.writeframes(int(amplitude).to_bytes(2, 'little', signed=True)*int(seconds*16000))
    return out.getvalue()


def client():
    app = FastAPI(); app.include_router(d.router)
    return TestClient(app)


def test_valid_audio_and_limits():
    d.validate_audio(wav())
    for data, code in [(wav(amplitude=0), 'DICTATION_SILENCE'), (wav(300.01), 'DICTATION_DURATION'), (b'bad', 'DICTATION_FORMAT')]:
        with pytest.raises(HTTPException) as e: d.validate_audio(data)
        assert e.value.detail == code


def test_idempotency_and_no_capture():
    from uuid import uuid4
    c = client(); identifier = str(uuid4())
    with patch.object(d, 'transcribe', return_value='不是三十秒，是三秒。') as upstream:
        r = c.post('/v2/dictation/transcribe', content=wav(), headers={'X-Dictation-ID': identifier})
        assert r.status_code == 200 and r.json()['text'] == '不是三十秒，是三秒。'
        assert c.post('/v2/dictation/transcribe', content=wav(), headers={'X-Dictation-ID': identifier}).status_code == 409
        assert upstream.call_count == 1


def test_invalid_request_never_calls_provider():
    with patch.object(d, 'transcribe') as upstream:
        assert client().post('/v2/dictation/transcribe', content=wav()).status_code == 400
        upstream.assert_not_called()


def test_clean_failure_retains_original_and_does_not_retranscribe():
    with patch.object(d, 'parse_model', side_effect=RuntimeError('private upstream detail')), patch.object(d, 'transcribe') as upstream:
        r = client().post('/v2/dictation/clean', json={'text': '不要改数字 30。'})
        assert r.json() == {'raw_text': '不要改数字 30。', 'text': '不要改数字 30。', 'cleaned': False}
        upstream.assert_not_called()


@pytest.mark.parametrize('changed', ['改数字 30。', '不要改数字 3。', '好的'])
def test_clean_rejects_negation_numeric_and_summary_drift(changed):
    with patch.object(d, 'parse_model', return_value=d.CleanText(text=changed)):
        result = d.clean('不要改数字 30。')
        assert result['cleaned'] is False


def test_clean_success():
    with patch.object(d, 'parse_model', return_value=d.CleanText(text='用 Spine 接入 SwiftUI。')):
        assert d.clean('用 Spine 接入 SwiftUI')['cleaned']


def test_provider_errors_are_redacted_and_not_retried(monkeypatch):
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-secret')
    with patch.object(d.httpx.Client, 'post', side_effect=d.httpx.ReadTimeout('test-secret')) as call:
        with pytest.raises(HTTPException) as e: d.transcribe(wav())
        assert e.value.detail == 'DICTATION_TIMEOUT'
        assert call.call_count == 1


def test_unconfigured_or_escaped_key_not_sent(monkeypatch):
    for key in ['', 'test\\_secret']:
        monkeypatch.setenv('DASHSCOPE_API_KEY', key)
        with patch.object(d.httpx.Client, 'post') as call:
            with pytest.raises(HTTPException) as e: d.transcribe(wav())
            assert e.value.detail == 'DICTATION_NOT_CONFIGURED'
            call.assert_not_called()
