"""Replace only the stopped canonical App after separate approval. No DB writes."""
from pathlib import Path
import shutil
import subprocess
import sys
from common import ROOT, OUT, PRIVATE, ARCHIVE, DAILY, LS, read, write, sha, files, inventory, stopped, unchanged, prior_helpers
from approval import require_approved


def main():
    spec = require_approved()  # Must refuse before unpacking or inspecting daily databases.
    if sys.argv[1:] != ['--install-approved']:
        raise PermissionError('The explicit installation entry is required')
    if (PRIVATE / 'execution.json').exists():
        raise PermissionError('An installation was already attempted; inspect its recorded phase')
    unchanged()
    candidate = read(OUT / 'candidate.json')
    backup = read(OUT / 'backup.json')
    assert sha(Path(candidate['zip'])) == candidate['zip_sha256']
    assert sha(Path(backup['daily_app_archive'])) == backup['daily_app_archive_sha256']
    assert all(sha(Path(p)) == h for p, h in read(PRIVATE / 'backup-pins.json').items())
    assert inventory(DAILY) == read(PRIVATE / 'source-protection.json')['daily_app_inventory']
    stage_root = ARCHIVE / 'install-stage.noindex'
    rollback_root = ARCHIVE / 'install-rollback.noindex'
    assert not stage_root.exists() and not rollback_root.exists()
    assert ARCHIVE.stat().st_dev == DAILY.parent.stat().st_dev, 'Atomic same-volume rename is required'
    stage_root.mkdir(); rollback_root.mkdir()
    subprocess.run(['ditto', '-x', '-k', candidate['zip'], str(stage_root)], check=True)
    stage = stage_root / 'Review_Today.app'
    assert inventory(stage) == candidate['inventory']
    helpers = prior_helpers()
    assert helpers.signature(stage) == candidate['signature']
    unchanged()
    before = rollback_root / DAILY.name
    write(PRIVATE / 'execution.json', dict(phase='verified_before_replace', batch_id=spec['batch_id']))
    DAILY.rename(before)
    try:
        stage.rename(DAILY)
        assert inventory(DAILY) == candidate['inventory']
        assert helpers.signature(DAILY) == candidate['signature']
    except BaseException:
        if DAILY.exists(): DAILY.rename(stage)
        before.rename(DAILY)
        write(PRIVATE / 'execution.json', dict(phase='replacement_failed_old_app_restored', batch_id=spec['batch_id']))
        raise
    # Old bytes are already in a read-and-signature-verified persistent ZIP.
    assert inventory(before) == read(PRIVATE / 'source-protection.json')['daily_app_inventory']
    shutil.rmtree(before)
    subprocess.run([LS, '-u', str(stage)], capture_output=True)
    subprocess.run([LS, '-f', str(DAILY)], check=True, capture_output=True)
    stage_root.rmdir(); rollback_root.rmdir()
    write(PRIVATE / 'execution.json', dict(phase='installed_not_started', batch_id=spec['batch_id'], daily_app=str(DAILY)))
    write(OUT / 'installation.json', dict(status='INSTALLED_NOT_STARTED', canonical_app=str(DAILY),
        signed_inventory_matched=True, daily_database_written=False, rollback_zip=backup['daily_app_archive'],
        actual_new_model_requests=0, actual_new_web_operations=0))


if __name__ == '__main__': main()
