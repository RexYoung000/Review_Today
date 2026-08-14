import os
from pathlib import Path

from dotenv import load_dotenv

from agent_service.certs import install_trust_store

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
CA_BUNDLE = install_trust_store()

HOST = "127.0.0.1"
PORT = 8742
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o").strip() or "gpt-4o"
BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip()


def openai_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()
