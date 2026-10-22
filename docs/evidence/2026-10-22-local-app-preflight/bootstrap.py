"""Activation-only bootstrap, pending/HOLD refuses before production imports."""
import hashlib
import json
import os
from pathlib import Path
import sys


def install(directory, root):
    directory, root = Path(directory).resolve(), Path(root).resolve()
    out = Path(__file__).resolve().parent
    spec = json.loads((directory/'authorization.json').read_text())
    assert spec['actual_model_request_limit'] == 8 and spec['provider_web_operation_limit'] == 0
    expected = Path.home()/'Library/Application Support/Review Today/agent-harness.sqlite3'
    assert Path(spec['database_path']).resolve() == expected.resolve()
    import quota_activation
    quota_activation.Quota(directory)  # Pending/HOLD fails before imports or ledger creation.
    pins = json.loads((out/'source-pins.json').read_text())
    assert all(hashlib.sha256((root/name).read_bytes()).hexdigest() == checksum for name, checksum in pins.items())
    os.environ['REVIEW_TODAY_HARNESS_DB'] = str(expected)
    # Match the two normal AgentServiceMonitor launch flags, without editing .env.
    os.environ['REVIEW_TODAY_JEV_TEST'] = '0'
    os.environ['REVIEW_TODAY_BROWSER_FALLBACK'] = '1'
    assert 'agent_service.main' not in sys.modules and 'agent_service.model_capabilities' not in sys.modules
    quota = quota_activation.install(directory)
    quota_activation.probes_only(quota)
    from agent_service import config
    assert Path(config.HARNESS_DB).resolve() == expected.resolve()
    (directory/'bootstrap-ready.json').write_text(json.dumps(dict(pid=os.getpid(), model_limit=8, web_limit=0,
        daily_database=True, probes_only=True))+'\n')
