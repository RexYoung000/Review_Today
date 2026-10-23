"""QA preparation helpers; imports do not open stores or start a service."""
import hashlib
import importlib.util
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
PRIVATE=ROOT/'output/fullflow-preflight-2026-10-23'
DURABLE=Path.home()/'Library/Developer/ReviewTodayEvidence.noindex/2026-10-23-fresh-fullflow'
PRIOR=ROOT/'docs/evidence/2026-10-22-fullflow-preflight'
MODULE=Path('/tmp/review-today-shared-contracts.xlgn66_8')
spec=importlib.util.spec_from_file_location('packaging_helpers',ROOT/'docs/evidence/2026-10-23-daily-update-preflight/common.py')
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)
sha,files,inventory,read,write,stopped=helpers.sha,helpers.files,helpers.inventory,helpers.read,helpers.write,helpers.stopped
DAILY,SUPPORT,LS=helpers.DAILY,helpers.SUPPORT,helpers.LS


def check_protection(state):
    stopped()
    assert files(SUPPORT)==state['daily_files'],'Daily data changed'
    assert inventory(DAILY)==state['daily_app_inventory'],'Daily app changed'
    for key in ['frozen_existing_files','original_module_files']:
        assert all(Path(p).is_file() and sha(Path(p))==h for p,h in state[key].items()),key
    assert all(sha(ROOT/p)==h for p,h in state['protected_fingerprints'].items())
    assert all(not Path(p).exists() for p in state['known_missing_old_paths'])
    diff=hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest()
    assert diff==state['project_diff_sha256'],'User project diff changed'


def no_external_runtime(directory, *, owned_backups=()):
    """Audit only the new owned runtime; never relax the product isolation rule."""
    import sys
    from urllib.parse import urlsplit,unquote
    directory=Path(directory).resolve()
    allowed=(directory,)+tuple(Path(p).resolve() for p in owned_backups)
    def audit(event,args):
        if event=='socket.connect':raise AssertionError('No network in preparation')
        if event=='sqlite3.connect':
            raw=str(args[0])
            if raw==':memory:':return
            path=Path(unquote(urlsplit(raw).path) if raw.startswith('file:') else raw).resolve()
            assert any(path.is_relative_to(p) for p in allowed),'SQLite outside owned QA runtime/backups'
    sys.addaudithook(audit)
