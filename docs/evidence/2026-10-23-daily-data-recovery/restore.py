"""Restore only the verified formal snapshot after approval. Never launches an App."""
import argparse
import ctypes
import os
import shutil
import uuid
from prepare import *


def rename_exclusive(source,target):
    # macOS SDK usr/include/sys/stdio.h: RENAME_EXCL = 0x00000004.
    function=ctypes.CDLL(None,use_errno=True).renamex_np
    function.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint]
    function.restype=ctypes.c_int
    if function(os.fsencode(source),os.fsencode(target),4)!=0:
        error=ctypes.get_errno();raise OSError(error,os.strerror(error),str(target))


def check():
    spec=read(OUT/'verification.json');source=Path(spec['staged_support'])
    assert spec['status']=='FORMAL_DATA_RECOVERY_PREPARED_PENDING'
    assert spec['source_is_formal_daily_data'] and spec['test_cards_not_promoted']
    assert spec['target']==str(SUPPORT) and not os.path.lexists(SUPPORT),'Target exists; refuse to replace any data'
    assert subprocess.run(['pgrep','-x','Review_Today'],capture_output=True).returncode==1
    assert not subprocess.run(['lsof','-nP','-iTCP:8742','-sTCP:LISTEN'],capture_output=True).stdout
    actual={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()}
    assert actual==spec['staged_files'] and not any(p.is_symlink() for p in source.rglob('*'))
    assert sha(Path(spec['source_archive']))==spec['source_archive_sha256']
    assert sha(Path(spec['verified_stage_zip']))==spec['verified_stage_zip_sha256']
    return spec


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    spec=check()
    if not args.apply:
        print('READY: exact five-file formal snapshot; target absent, App/service stopped. Nothing written.');return
    approval=read(OUT/'authorization.json')
    assert approval['status']=='approved' and approval['target']==str(SUPPORT)
    assert approval['verification_sha256']==sha(OUT/'verification.json')
    assert approval['start_app'] is False and approval['actual_model_limit']==approval['actual_web_limit']==0
    parent=SUPPORT.parent
    stage=parent/('ReviewToday-recovery-'+str(uuid.uuid4())+'.noindex')
    assert not stage.exists();shutil.copytree(spec['staged_support'],stage);stage.chmod(0o700)
    for p in stage.rglob('*'):p.chmod(0o700 if p.is_dir() else 0o600)
    assert {str(p.relative_to(stage)):sha(p) for p in stage.rglob('*') if p.is_file()}==spec['staged_files']
    check()  # Stop if the user/App recreated the target while staging.
    rename_exclusive(stage,SUPPORT)  # Atomically refuses any existing target, including an empty directory.
    assert {str(p.relative_to(SUPPORT)):sha(p) for p in SUPPORT.rglob('*') if p.is_file()}==spec['staged_files']
    assert subprocess.run(['pgrep','-x','Review_Today'],capture_output=True).returncode==1
    result=dict(status='FORMAL_SNAPSHOT_RESTORED_APP_CLOSED',target=str(SUPPORT),restored_files=spec['staged_files'],
        verification_sha256=sha(OUT/'verification.json'),native_counts=spec['native_counts'],
        app_started=False,actual_model_requests=0,actual_web_operations=0,
        source_archive_preserved=True,target_was_not_overwritten=True,old_96_file_baseline_not_rewritten=True,
        historical_Backups_89_not_restored=True,native_window_and_post_restore_startup_not_checked=True)
    write(OUT/'restoration.json',result);write(DURABLE/'restoration.json',result)
    print('Formal snapshot restored; 8 sessions / 37 messages / 11 cards, original review data; App closed, calls 0/0.')


if __name__=='__main__':main()
