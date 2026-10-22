"""Local preparation helpers; importing this file opens no database or service."""
import hashlib, importlib.util, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
PRIVATE=ROOT/'output/navigation-save-preflight-2026-10-22'
PRIOR=ROOT/'docs/evidence/2026-10-22-fullflow-preflight'
REAL=ROOT/'output/fullflow-real-2026-10-22'
ARCHIVE=Path.home()/'Library/Developer/ReviewTodayAppArchives.noindex/2026-10-22-navigation-save'
spec=importlib.util.spec_from_file_location('old_preparation_helpers',PRIOR/'prepare.py')
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)
sha=helpers.sha;files=helpers.files;app_files=helpers.app_files;stopped=helpers.stopped
DAILY=helpers.DAILY;SUPPORT=helpers.SUPPORT;LS=helpers.LS
def read(p):return json.loads(Path(p).read_text())
def write(p,value):Path(p).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def check_protection(state):
    assert files(SUPPORT)==state['daily_files'],'Daily files changed'
    assert app_files(DAILY)==state['daily_app_inventory'],'Daily App changed'
    for key in ['old_frozen_files','previous_batch_files','original_module_files','original_support_files']:
        assert all(sha(Path(p))==h for p,h in state[key].items()),key
    assert all(sha(ROOT/p)==h for p,h in state['protected_fingerprints'].items()),'Source/config changed'
    assert sha(ROOT/'Review_Today.xcodeproj/project.pbxproj')==state['project_file_sha256']
    stopped()
