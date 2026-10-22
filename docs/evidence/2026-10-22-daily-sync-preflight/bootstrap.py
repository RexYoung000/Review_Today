"""Held before imports; startup allowance only covers the two real probe paths."""
import json
import os
from pathlib import Path
import sys
from approval import require_approved
from prepare import ROOT, OUT, PRIVATE, SUPPORT, DAILY, app_files


def install():
    require_approved()
    execution = json.loads((PRIVATE/'execution.json').read_text())
    if execution.get('phase') != 'backend_cleaned_app_installed':
        raise PermissionError('Daily cleanup and installation have not completed')
    candidate = json.loads((OUT/'candidate.json').read_text())
    if app_files(DAILY) != candidate['inventory']:
        raise PermissionError('Installed application differs from the reviewed candidate')
    old = ROOT/'docs/evidence/2026-10-22-local-app-preflight'
    sys.path.insert(0,str(old))
    import quota_activation
    directory = PRIVATE/'activation'
    quota_activation.Quota(directory)
    os.environ['REVIEW_TODAY_HARNESS_DB'] = str(SUPPORT/'agent-harness.sqlite3')
    os.environ['REVIEW_TODAY_JEV_TEST'] = '0'
    os.environ['REVIEW_TODAY_BROWSER_FALLBACK'] = '1'
    if 'agent_service.main' in sys.modules:
        raise RuntimeError('Startup guard must be installed before runtime imports')
    quota = quota_activation.install(directory)
    quota_activation.probes_only(quota)
    from agent_service import config
    if Path(config.HARNESS_DB).resolve() != (SUPPORT/'agent-harness.sqlite3').resolve():
        raise RuntimeError('Unexpected backend database')
    (directory/'bootstrap-ready.json').write_text(json.dumps(dict(pid=os.getpid(),model_limit=8,web_limit=0,probes_only=True))+'\n')
