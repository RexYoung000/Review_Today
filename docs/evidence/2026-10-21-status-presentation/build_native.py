"""Build a service-free native component QA on a copy of actual saved cards."""
import json
from pathlib import Path
import plistlib
import shutil
import sqlite3
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SUPPORT = Path((OUT / 'native-contracts.log').read_text().splitlines()[0].split(': ', 1)[1])


def main():
    directory = Path(tempfile.mkdtemp(prefix='review-today-status-presentation-', dir='/tmp'))
    source = Path('/tmp/review-today-preview-save-pending-a9aqb_be/app.store')
    with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as old, sqlite3.connect(directory / 'app.store') as new:
        old.backup(new)
        assert new.execute('pragma quick_check').fetchone()[0] == 'ok'
    # Keep the existing migration marker with this already-migrated store,
    # as the preceding native continuation preparation does.
    shutil.copy2(source.with_suffix('.store.review-v2-backup'), directory / 'app.store.review-v2-backup')
    shutil.copy2(OUT / 'corrected-reply.txt', directory / 'corrected-reply.txt')
    app = directory / 'StatusPresentationQA.app'
    mac = app / 'Contents/MacOS'
    mac.mkdir(parents=True)
    info = dict(CFBundleIdentifier='local.review-today.status-presentation.NativeQA',
        CFBundleName='StatusPresentationQA', CFBundleExecutable='StatusPresentationQA',
        CFBundlePackageType='APPL', QAStorePath=str(directory), NSHighResolutionCapable=True)
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    flags = ['xcrun', 'swiftc', '-parse-as-library', '-D', 'DEBUG', '-swift-version', '5',
        '-default-isolation', 'MainActor', '-enable-upcoming-feature', 'MemberImportVisibility',
        '-I', str(SUPPORT), '-L', str(SUPPORT), '-lReviewTodayContractSupport', '-lFSRS',
        '-Xlinker', '-rpath', '-Xlinker', str(SUPPORT)]
    with (OUT / 'native-build.log').open('w') as log:
        subprocess.run(flags + [str(OUT / 'NativePresentationQA.swift'), '-o', str(mac / 'StatusPresentationQA')],
            stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['codesign', '--force', '--sign', '-', str(app)], stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['codesign', '--verify', '--strict', str(app)], stdout=log, stderr=subprocess.STDOUT, check=True)
    setup = json.loads((OUT / 'setup.json').read_text())
    setup.update(native_directory=str(directory), native_app=str(app), support_dir=str(SUPPORT),
        native_service_free=True, native_data_source='decision255 native SQLite backup copy')
    (OUT / 'setup.json').write_text(json.dumps(setup, ensure_ascii=False, indent=2) + '\n')
    print(app)


if __name__ == '__main__':
    main()
