"""Build a service-free isolated native detail check; never opens the source DB."""
from pathlib import Path
import hashlib
import json
import plistlib
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIVATE = ROOT / 'output/title-fallback-repair-2026-10-23'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    log = (OUT / 'native-contracts.log').read_text()
    assert 'All selected contracts complete:' in log
    support = Path(log.splitlines()[0].split(': ', 1)[1])
    directory = Path(tempfile.mkdtemp(prefix='review-today-title-', suffix='.noindex', dir='/private/tmp'))
    source = ROOT / 'output/navigation-save-real-2026-10-22/disk-final'
    original = {str(p): digest(p) for p in source.iterdir() if p.is_file()}
    for path in source.glob('app.store*'):
        shutil.copy2(path, directory / path.name)
    app = directory / 'TitleDisplayQA.app'
    mac = app / 'Contents/MacOS'
    mac.mkdir(parents=True)
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(dict(
        CFBundleIdentifier='local.review-today.title-display.NativeQA', CFBundleName='TitleDisplayQA',
        CFBundleExecutable='TitleDisplayQA', CFBundlePackageType='APPL', NSHighResolutionCapable=True,
        QAStorePath=str(directory))))
    flags = ['xcrun', 'swiftc', '-parse-as-library', '-D', 'DEBUG', '-swift-version', '5',
             '-default-isolation', 'MainActor', '-enable-upcoming-feature', 'MemberImportVisibility',
             '-I', str(support), '-L', str(support), '-lReviewTodayContractSupport', '-lFSRS',
             '-Xlinker', '-rpath', '-Xlinker', str(support)]
    with (OUT / 'native-build.log').open('w') as stream:
        subprocess.run(flags + [str(OUT / 'NativeTitleQA.swift'), '-o', str(mac / 'TitleDisplayQA')],
                       check=True, stdout=stream, stderr=subprocess.STDOUT)
        subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True, stdout=stream, stderr=subprocess.STDOUT)
        subprocess.run(['codesign', '--verify', '--strict', str(app)], check=True, stdout=stream, stderr=subprocess.STDOUT)
        subprocess.run([str(mac / 'TitleDisplayQA'), '--check'], check=True, stdout=stream, stderr=subprocess.STDOUT)
    assert original == {str(p): digest(p) for p in source.iterdir() if p.is_file()}
    state = dict(directory=str(directory), app=str(app), support=str(support), source_files=original,
                 service_free=True, actual_new_model_requests=0, actual_new_web_operations=0)
    (OUT / 'setup.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    shutil.copy2(directory / 'native-cards.json', PRIVATE / 'native-cards-before-ui.json')
    print(app)


if __name__ == '__main__':
    main()
