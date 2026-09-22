"""Review-only real-provider QA server; never starts the Harness or uses its data."""
import os
assert os.environ.get('REVIEW_TODAY_REVIEW_DB','').startswith('/tmp/review-today-')
from fastapi import FastAPI
from agent_service.review_sessions import router
from agent_service.review_voice import router as voice
app=FastAPI();app.include_router(router);app.include_router(voice)
