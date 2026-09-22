#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
node tools/mascot-motion/src/build-native.mjs --check
qa_dir="$(mktemp -d /tmp/review-today-header-qa.XXXXXX)"
python3 - "$qa_dir" <<'PY'
import pathlib,subprocess,plistlib,shutil,sys
root=pathlib.Path.cwd();app=pathlib.Path(sys.argv[1])/'AgentTitleQA.app';contents=app/'Contents';binary=contents/'MacOS/AgentTitleQA';binary.parent.mkdir(parents=True)
sources=[str(p) for p in (root/'Review_Today').glob('*.swift') if p.name!='Review_TodayApp.swift']+[str(root/'tests/mac/AgentTitleMascotNativeTests.swift')]
subprocess.run(['tests/mac/swift-with-fsrs.py','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor','-enable-upcoming-feature','MemberImportVisibility',*sources,'-o',str(binary)],check=True)
(contents/'Resources').mkdir();shutil.copy(root/'Review_Today/MascotMotion.html',contents/'Resources/MascotMotion.html')
with (contents/'Info.plist').open('wb') as f:plistlib.dump(dict(CFBundleIdentifier='Rex.Review-Today.AgentTitleQA',CFBundleName='AgentTitleQA',CFBundleExecutable='AgentTitleQA',CFBundlePackageType='APPL'),f)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
print(app)
PY
"$qa_dir/AgentTitleQA.app/Contents/MacOS/AgentTitleQA" "${1:-}"
