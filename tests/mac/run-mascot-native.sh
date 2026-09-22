#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
node tools/mascot-motion/src/build-native.mjs --check
qa_dir="$(mktemp -d /tmp/review-today-mascot-qa.XXXXXX)"
python3 - "$qa_dir" <<'PY'
import pathlib,subprocess,sys,plistlib,shutil
folder=pathlib.Path(sys.argv[1]);app=folder/'MascotMotionQA.app';contents=app/'Contents';binary=contents/'MacOS'/'MascotMotionQA';binary.parent.mkdir(parents=True)
# RunwayChrome uses the shared interaction definitions; compile the same app
# sources as the other isolated contract runners, excluding the main App.
sources=[str(p) for p in pathlib.Path('Review_Today').glob('*.swift') if p.name!='Review_TodayApp.swift']+['tests/mac/MascotMotionNativeTests.swift']
with (folder/'build.log').open('w') as log:
 result=subprocess.run(['tests/mac/swift-with-fsrs.py','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor',*sources,'-o',str(binary)],stdout=log,stderr=subprocess.STDOUT)
if result.returncode: print((folder/'build.log').read_text());raise SystemExit(result.returncode)
(contents/'Resources').mkdir();shutil.copy('Review_Today/MascotMotion.html',contents/'Resources/MascotMotion.html')
with (contents/'Info.plist').open('wb') as f:plistlib.dump(dict(CFBundleIdentifier='Rex.Review-Today.MascotMotionQA',CFBundleName='MascotMotionQA',CFBundleExecutable=binary.name,CFBundlePackageType='APPL'),f)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
print(app,flush=True)
PY
"$qa_dir/MascotMotionQA.app/Contents/MacOS/MascotMotionQA" "${1:-}"
