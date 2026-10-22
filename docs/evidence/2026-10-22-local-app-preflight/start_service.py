"""Start a bounded temporary service for daily-App verification after approval."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'agent-service'))
from bootstrap import install

install(ROOT/'output/local-app-preflight-2026-10-22/activation', ROOT)
from agent_service.main import run

run()
