"""Explicit paid smoke test on a supplied non-sensitive PCM16 mono 16k WAV.
Run from agent-service: .venv/bin/python tests/dictation_real_smoke.py /path/sample.wav
Only call when raw provider credentials are configured; no microphone capture.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_service.dictation import validate_audio, transcribe
from fastapi import HTTPException

if __name__ == '__main__':
    audio = Path(sys.argv[1]).read_bytes()
    validate_audio(audio)
    started = time.monotonic()
    try:
        text = transcribe(audio)
        print(json.dumps({'model': 'fun-asr-flash-2026-06-15', 'region': 'Beijing', 'elapsed_seconds': round(time.monotonic()-started, 2), 'transcript': text}, ensure_ascii=False))
    except HTTPException as error:
        print(json.dumps({'error': error.detail, 'status': error.status_code}))
        raise SystemExit(1)
