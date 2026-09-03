import os
from pathlib import Path

from dotenv import load_dotenv

from agent_service.certs import install_trust_store

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
CA_BUNDLE = install_trust_store()

HOST = "127.0.0.1"
PORT = 8742
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o").strip() or "gpt-4o"
ROUTER_MODEL = os.getenv("OPENAI_ROUTER_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"
COACH_MODEL = os.getenv("OPENAI_COACH_MODEL", "gpt-5.6-terra").strip() or "gpt-5.6-terra"
RISK_MODEL = os.getenv("OPENAI_RISK_MODEL", "gpt-5.6-sol").strip() or "gpt-5.6-sol"
BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip()
MODEL_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "90"))
MODEL_PROBE_TIMEOUT_SECONDS = float(os.getenv("OPENAI_PROBE_TIMEOUT_SECONDS", "45"))
HARNESS_DB = os.getenv(
    "REVIEW_TODAY_HARNESS_DB",
    str(Path.home() / "Library" / "Application Support" / "Review Today" / "agent-harness.sqlite3"),
).strip()


def openai_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()
