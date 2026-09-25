#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
preview_dir="$(mktemp -d /tmp/review-today-settings-preview.XXXXXX)"
python3 - "$preview_dir" <<'PYTHON'
import pathlib, subprocess, sys, plistlib
folder = pathlib.Path(sys.argv[1])
app = folder / 'SettingsQA.app'
contents = app / 'Contents'
binary = contents / 'MacOS' / 'SettingsQA'
binary.parent.mkdir(parents=True)
sources = [str(p) for p in pathlib.Path('Review_Today').glob('*.swift') if p.name != 'Review_TodayApp.swift']
with (folder / 'build.log').open('w') as log:
    result = subprocess.run(['tests/mac/swift-with-fsrs.py', '-parse-as-library', '-D', 'DEBUG', '-swift-version', '5', '-default-isolation', 'MainActor', *sources, 'tests/mac/SettingsPreview.swift', '-o', str(binary)], stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    print((folder / 'build.log').read_text())
    raise SystemExit(result.returncode)
with (contents / 'Info.plist').open('wb') as f:
    plistlib.dump(dict(CFBundleIdentifier='Rex.Review-Today.SettingsQA', CFBundleName='SettingsQA', CFBundleExecutable=binary.name, CFBundlePackageType='APPL'), f)
subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
print(app)
PYTHON
REVIEW_TODAY_M1_UI_FIXTURE=1 "$preview_dir/SettingsQA.app/Contents/MacOS/SettingsQA"
