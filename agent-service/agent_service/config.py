import os
from pathlib import Path

from dotenv import load_dotenv

from agent_service.certs import install_trust_store

SERVICE_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(SERVICE_ROOT / ".env")
PROVIDER = os.getenv("REVIEW_TODAY_LLM_PROVIDER", "openai_compatible").strip() or "openai_compatible"
if PROVIDER not in {"openai_compatible", "deepseek"}:
    raise RuntimeError("RT.CONFIG.PROVIDER_UNSUPPORTED")
if PROVIDER == "deepseek":
    # Isolated namespace: never send either provider's key to the other endpoint.
    load_dotenv(SERVICE_ROOT / "providers" / "deepseek" / ".env")
CA_BUNDLE = install_trust_store()

HOST = "127.0.0.1"
PORT = 8742
if PROVIDER == "deepseek":
    MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash"
    ROUTER_MODEL = os.getenv("DEEPSEEK_ROUTER_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash"
    COACH_MODEL = os.getenv("DEEPSEEK_COACH_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash"
    RISK_MODEL = os.getenv("DEEPSEEK_RISK_MODEL", "deepseek-v4-pro").strip() or "deepseek-v4-pro"
    BASE_URL = "https://api.deepseek.com"
else:
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
    """Compatibility accessor; the selected provider exclusively owns the key."""
    return os.getenv("DEEPSEEK_API_KEY" if PROVIDER == "deepseek" else "OPENAI_API_KEY", "").strip()
