"""Verify the signed build, archive it, and remove its discoverable application."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

from prepare import ROOT, OUT, PRIVATE, ARCHIVE, DAILY, app_files, sha, stopped, write

BUILD = Path.home()/'Library/Developer/ReviewTodayBuilds.noindex/daily-sync-2026-10-22'
APP = BUILD/'Build/Products/Debug/Review_Today.app'
LS = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'


def main():
    assert '** BUILD SUCCEEDED **' in (PRIVATE/'build.log').read_text()
    assert not (OUT/'candidate.json').exists()
    stopped()
    spec = importlib.util.spec_from_file_location('old_preflight',ROOT/'docs/evidence/2026-10-22-local-app-preflight/prepare.py')
    old = importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    signature = old.signature(APP);contents = app_files(APP)
    pins = json.loads((OUT/'source-pins.json').read_text())
    assert all(sha(ROOT/p)==h for p,h in pins.items())
    before = json.loads((PRIVATE/'source-protection.json').read_text())
    assert app_files(DAILY)==before['app_files']
    unregister = subprocess.run([LS,'-u',str(APP)],capture_output=True,text=True)
    archive = ARCHIVE/'ReviewToday-candidate.zip'
    assert not archive.exists()
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(APP),str(archive)],check=True)
    check = ARCHIVE/'candidate-restore.noindex';check.mkdir()
    subprocess.run(['ditto','-x','-k',str(archive),str(check)],check=True)
    assert app_files(check/'Review_Today.app')==contents
    assert old.signature(check/'Review_Today.app')==signature
    shutil.rmtree(check);shutil.rmtree(APP)
    dump = subprocess.check_output([LS,'-dump'],text=True)
    import re
    identifiers = re.findall(r'^identifier:\s*(.*)$',dump,re.M)
    assert sum(bool(re.search(r'review[-_]?today',i,re.I)) for i in identifiers)==1
    assert app_files(DAILY)==before['app_files']
    write(OUT/'candidate.json',dict(status='SIGNED_ARCHIVE_READY_NOT_INSTALLED',zip=str(archive),zip_sha256=sha(archive),
        signature=signature,inventory=contents,restored_files_and_permissions_match=True,raw_candidate_removed=True,
        construction_path_unregistered=True,unregister_exit_code=unregister.returncode,related_app_entry_count=1,
        app_code_changed_files=['Review_Today/SessionDeletion.swift'],actual_model_requests=0,actual_web_operations=0,daily_app_updated=False))
    print('Signed candidate archived and verified; one registered daily entry remains.',flush=True)


if __name__=='__main__':main()
