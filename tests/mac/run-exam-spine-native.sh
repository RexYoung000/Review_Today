#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
node tools/mascot-motion/src/build-exam-spine.mjs --check
qa_dir="$(mktemp -d /tmp/review-today-exam-spine.XXXXXX)"
python3 - "$qa_dir" <<'PY'
import pathlib,plistlib,shutil,subprocess,sys
folder=pathlib.Path(sys.argv[1]);app=folder/'ExamSpineQA.app';contents=app/'Contents';binary=contents/'MacOS/ExamSpineQA'
binary.parent.mkdir(parents=True);(contents/'Resources').mkdir()
subprocess.run(['xcrun','swiftc','-target','arm64-apple-macos26.5','-parse-as-library','tests/mac/ExamEntrySpineNativeTests.swift','-o',str(binary)],check=True)
shutil.copy2('Review_Today/ExamEntrySpine.html',contents/'Resources/ExamEntrySpine.html')
with (contents/'Info.plist').open('wb') as file:
 plistlib.dump(dict(CFBundleIdentifier='Rex.Review-Today.ExamSpineQA',CFBundleName='ExamSpineQA',CFBundleExecutable=binary.name,CFBundlePackageType='APPL'),file)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
print(app,flush=True)
PY
"$qa_dir/ExamSpineQA.app/Contents/MacOS/ExamSpineQA"
