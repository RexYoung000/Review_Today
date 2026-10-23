"""Preserve this closed component run, then remove only its own registered App."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIVATE = ROOT / 'output/title-fallback-repair-2026-10-23'
ARCHIVE = Path.home() / 'Library/Developer/ReviewTodayEvidence.noindex/2026-10-23-title-fallback'
LS = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'


def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    setup = json.loads((OUT / 'setup.json').read_text())
    app = Path(setup['app']); directory = Path(setup['directory']); support = Path(setup['support'])
    assert subprocess.run(['pgrep', '-x', 'TitleDisplayQA'], capture_output=True).returncode == 1
    assert not ARCHIVE.exists()
    assert (PRIVATE / 'native-cards-before-ui.json').read_bytes() == (PRIVATE / 'native-cards-after-ui.json').read_bytes()
    subprocess.run(['codesign', '--verify', '--strict', str(app)], check=True)
    ARCHIVE.mkdir(parents=True, mode=0o700)
    paths = {}
    for root, prefix in [(directory, 'runtime'), (PRIVATE, 'evidence')]:
        for p in root.rglob('*'):
            if p.is_file(): paths[prefix + '/' + str(p.relative_to(root))] = p
    for name in ['libReviewTodayContractSupport.dylib', 'ReviewTodayContractSupport.swiftmodule',
                 'ReviewTodayContractSupport.swiftdoc', 'ReviewTodayContractSupport.swiftsourceinfo',
                 'libFSRS.dylib', 'FSRS.swiftmodule', 'FSRS.swiftdoc', 'FSRS.swiftsourceinfo']:
        paths['support/' + name] = support / name
    fingerprints = {member: sha(p) for member, p in paths.items()}
    bundle = ARCHIVE / 'component-evidence.zip'
    with zipfile.ZipFile(bundle, 'x', compression=zipfile.ZIP_DEFLATED) as stream:
        for member, p in paths.items(): stream.write(p, member)
    bundle.chmod(0o600)
    with zipfile.ZipFile(bundle) as stream:
        assert set(stream.namelist()) == set(fingerprints)
        for member, h in fingerprints.items():
            assert hashlib.sha256(stream.read(member)).hexdigest() == h
    (ARCHIVE / 'manifest.json').write_text(json.dumps(dict(files=fingerprints, archive_sha256=sha(bundle),
        original_app=str(app), original_support=str(support), byte_members_read_and_verified=True,
        restore_requires_isolated_paths=True), ensure_ascii=False, indent=2) + '\n')
    (ARCHIVE / 'manifest.json').chmod(0o600)
    assert all(sha(p) == fingerprints[member] for member, p in paths.items())
    result = subprocess.run([LS, '-u', str(app)], capture_output=True, text=True)
    assert result.returncode in [0, 1]
    # Only remove this newly created QA bundle; its actual bytes are verified above.
    shutil.rmtree(app)
    text = subprocess.check_output([LS, '-dump'], text=True)
    (PRIVATE / 'launchservices-final.txt').write_text(text)
    ids = re.findall(r'^identifier:\s*(.*)$', text, re.M)
    registered = sum(bool(re.search(r'review[-_]?today', value, re.I)) for value in ids)
    spotlight = subprocess.check_output(['mdfind', "kMDItemContentType == 'com.apple.application-bundle' && kMDItemCFBundleIdentifier == 'Rex.Review-Today'"], text=True).splitlines()
    assert registered == 1 and spotlight == ['/Applications/Review Today.app']
    report = dict(raw_qa_app_removed=not app.exists(), related_registered_entries=registered,
                  spotlight_paths=spotlight, archive=str(bundle), archive_sha256=sha(bundle),
                  archive_members_actually_verified=len(fingerprints), exact_bundle_unregistered=True,
                  service_started=False, daily_app_updated=False)
    (OUT / 'cleanup.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
