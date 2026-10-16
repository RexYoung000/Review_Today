"""Run controlled tests with blank keys, isolated storage and no public sockets."""
import ipaddress
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


def main():
    arguments = sys.argv[1:]
    provider = "deepseek" if "--deepseek" in arguments else "openai_compatible"
    arguments = [arg for arg in arguments if arg != "--deepseek"]
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "TYPESAFE_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY"):
        os.environ[name] = ""
    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def permitted(sock, address):
        if sock.family == socket.AF_UNIX:
            return True
        try:
            return ipaddress.ip_address(address[0]).is_loopback
        except (ValueError, TypeError):
            return False

    def connect(sock, address):
        if not permitted(sock, address):
            raise AssertionError("Public network forbidden in controlled KT-03 tests")
        return original_connect(sock, address)

    def connect_ex(sock, address):
        if not permitted(sock, address):
            raise AssertionError("Public network forbidden in controlled KT-03 tests")
        return original_connect_ex(sock, address)

    with tempfile.TemporaryDirectory(prefix="review-today-preview-deferral-tests-", dir="/tmp") as directory:
        os.environ.update(REVIEW_TODAY_HARNESS_DB=str(Path(directory) / "checkpoint.sqlite3"),
            REVIEW_TODAY_LLM_PROVIDER=provider, REVIEW_TODAY_JEV_TEST="0", REVIEW_TODAY_SEARCH_PROVIDER="none",
            REVIEW_TODAY_CONTEXT_PROVIDER="none", REVIEW_TODAY_BROWSER_FALLBACK="0")
        sys.path.insert(0, str(ROOT / "agent-service"))
        import pytest
        with patch.object(socket.socket, "connect", connect), patch.object(socket.socket, "connect_ex", connect_ex):
            result = pytest.main(arguments)
    raise SystemExit(result)


if __name__ == "__main__":
    main()
