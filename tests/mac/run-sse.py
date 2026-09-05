"""Run the native parser against a single-use loopback fixture, never the Agent."""
import subprocess
import sys
from pathlib import Path

fixture = subprocess.Popen([sys.executable, str(Path(__file__).with_name("stream_fixture.py"))], stdout=subprocess.PIPE, text=True)
try:
    endpoint = fixture.stdout.readline().strip()
    if not endpoint.startswith("http://127.0.0.1:"):
        raise RuntimeError("Fixture did not provide a loopback endpoint")
    subprocess.run([sys.argv[1], endpoint], check=True, timeout=30)
    fixture.wait(timeout=5)
finally:
    if fixture.poll() is None:
        fixture.terminate()
        fixture.wait(timeout=5)
