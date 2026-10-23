"""Side-effect-free packaging helpers; no service imports or database opens."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIVATE = ROOT / 'output/daily-update-preflight-2026-10-23'
ARCHIVE = Path.home() / 'Library/Developer/ReviewTodayAppArchives.noindex/2026-10-23-daily-update-preflight'
BUILD = Path.home() / 'Library/Developer/ReviewTodayBuilds.noindex/daily-update-2026-10-23'
DAILY = Path('/Applications/Review Today.app')
SUPPORT = Path.home() / 'Library/Application Support/Review Today'
LS = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
DBS = {'Data/ReviewToday.store': 'app.store', 'agent-harness.sqlite3': 'checkpoint.sqlite3', 'agent-harness.review.sqlite3': 'review.sqlite3'}


def read(path): return json.loads(path.read_text())
def write(path, value): path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()
def files(directory): return {str(p.resolve()): sha(p) for p in directory.rglob('*') if p.is_file()}
def inventory(directory):
    result = {}
    for parent, directories, names in os.walk(directory):
        for name in directories + names:
            p = Path(parent) / name
            mode = stat.S_IMODE(p.lstat().st_mode)
            if p.is_symlink(): row = dict(type='link', mode=mode, target=os.readlink(p))
            elif p.is_dir(): row = dict(type='dir', mode=mode)
            else: row = dict(type='file', mode=mode, size=p.stat().st_size, sha256=sha(p))
            result[str(p.relative_to(directory))] = row
    return result
def stopped():
    if subprocess.run(['pgrep', '-x', 'Review_Today'], capture_output=True).returncode != 1:
        raise PermissionError('Daily App is active')
    if subprocess.run(['lsof', '-nP', '-iTCP:8742', '-sTCP:LISTEN'], capture_output=True).stdout:
        raise PermissionError('Daily service is active')
def prior_helpers():
    path = ROOT / 'docs/evidence/2026-10-22-local-app-preflight/prepare.py'
    spec = importlib.util.spec_from_file_location('previous_packaging_helpers', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module
def pin_files():
    paths = set(read(ROOT / 'docs/evidence/2026-10-22-navigation-save-preflight/setup.json')['protected_fingerprints'])
    paths.update(str(p.relative_to(ROOT)) for p in OUT.glob('*.py'))
    paths.update(str((OUT / name).relative_to(ROOT)) for name in ['plan.json', 'candidate.json', 'backup.json'])
    paths.update(['docs/evidence/2026-10-22-local-app-preflight/quota_activation.py',
                  'docs/evidence/2026-10-22-local-app-preflight/source-pins.json',
                  'docs/evidence/2026-10-21-learning-save-preflight/quota.py',
                  'docs/evidence/2026-10-22-local-app-preflight/probe_checks.py'])
    return {p: sha(ROOT / p) for p in sorted(paths)}
def unchanged():
    before = read(PRIVATE / 'source-protection.json')
    assert files(SUPPORT) == before['daily_files']
    assert inventory(DAILY) == before['daily_app_inventory']
    assert hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)).hexdigest() == before['project_diff_sha256']
    assert all(sha(ROOT / p) == h for p, h in before['source_config_pins'].items())
    stopped()
