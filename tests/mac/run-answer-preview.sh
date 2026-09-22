#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
preview_dir="$(mktemp -d /tmp/review-today-answer-preview.XXXXXX)"
python3 - "$preview_dir" <<'PY'
import pathlib, subprocess, sys, plistlib
folder=pathlib.Path(sys.argv[1])
app=folder/'AnswerReadingQA.app'
contents=app/'Contents'
binary=contents/'MacOS'/'AnswerReadingQA'
binary.parent.mkdir(parents=True)
sources=[str(p) for p in pathlib.Path('Review_Today').glob('*.swift') if p.name!='Review_TodayApp.swift']
with (folder/'build.log').open('w') as log:
    result=subprocess.run(['tests/mac/swift-with-fsrs.py','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor',*sources,
                          'tests/mac/AnswerRenderingPreview.swift','-o',str(binary)],stdout=log,stderr=subprocess.STDOUT)
if result.returncode:
    print((folder/'build.log').read_text())
    raise SystemExit(result.returncode)
with (contents/'Info.plist').open('wb') as f:
    plistlib.dump(dict(CFBundleIdentifier='Rex.Review-Today.AnswerReadingQA',CFBundleName='AnswerReadingQA',
                      CFBundleExecutable=binary.name,CFBundlePackageType='APPL'),f)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
print(app)
PY
if [[ "${1:-}" == "--interactive" ]]; then
  "$preview_dir/AnswerReadingQA.app/Contents/MacOS/AnswerReadingQA"
else
  "$preview_dir/AnswerReadingQA.app/Contents/MacOS/AnswerReadingQA" "${1:-$preview_dir/renders}"
fi
