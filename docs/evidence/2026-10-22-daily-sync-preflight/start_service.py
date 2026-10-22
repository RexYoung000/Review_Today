"""After separate approval, run the bounded temporary service; never launch UI."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'agent-service'))
from bootstrap import install
install()
from agent_service.main import run
run()
