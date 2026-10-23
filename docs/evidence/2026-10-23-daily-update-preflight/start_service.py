"""Actual startup entry. Pending refuses before service, SDK or DB imports."""
from pathlib import Path
import os
import sys
from common import ROOT, OUT, PRIVATE, SUPPORT, DAILY, read, write, inventory
from approval import require_approved


def main():
    spec = require_approved()
    execution = read(PRIVATE / 'execution.json')
    if execution != dict(phase='installed_not_started', batch_id=spec['batch_id'], daily_app=str(DAILY)):
        raise PermissionError('The prepared installation is not ready for its one startup run')
    if inventory(DAILY) != read(OUT / 'candidate.json')['inventory']:
        raise PermissionError('Installed App differs from the reviewed candidate')
    sys.path.insert(0, str(ROOT / 'agent-service'))
    sys.path.insert(0, str(ROOT / 'docs/evidence/2026-10-22-local-app-preflight'))
    import quota_activation
    directory = PRIVATE / 'activation'
    quota_activation.Quota(directory)
    os.environ['REVIEW_TODAY_HARNESS_DB'] = str(SUPPORT / 'agent-harness.sqlite3')
    os.environ['REVIEW_TODAY_JEV_TEST'] = '0'
    os.environ['REVIEW_TODAY_BROWSER_FALLBACK'] = '1'
    assert 'agent_service.main' not in sys.modules
    quota = quota_activation.install(directory)
    quota_activation.probes_only(quota)
    from agent_service import config
    assert Path(config.HARNESS_DB).resolve() == (SUPPORT / 'agent-harness.sqlite3').resolve()
    write(directory / 'bootstrap-ready.json', dict(pid=os.getpid(), model_limit=8, web_limit=0, probes_only=True))
    write(PRIVATE / 'execution.json', dict(phase='startup_started', batch_id=spec['batch_id'], daily_app=str(DAILY)))
    from agent_service.main import run
    run()


if __name__ == '__main__': main()
