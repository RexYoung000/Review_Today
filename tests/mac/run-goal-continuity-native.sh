#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
qa_dir="$(mktemp -d /tmp/review-today-goal-qa.XXXXXX)"
python3 - "$qa_dir" <<'PY'
import pathlib, subprocess, plistlib, shutil, sys
root=pathlib.Path.cwd(); app=pathlib.Path(sys.argv[1])/'GoalContinuityQA.app'; contents=app/'Contents'; binary=contents/'MacOS/GoalContinuityQA'; binary.parent.mkdir(parents=True)
sources=[str(p) for p in (root/'Review_Today').glob('*.swift') if p.name!='Review_TodayApp.swift']+[str(root/'tests/mac/GoalContinuityNativeQA.swift')]
subprocess.run(['tests/mac/swift-with-fsrs.py','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor','-enable-upcoming-feature','MemberImportVisibility',*sources,'-o',str(binary)],check=True)
r=contents/'Resources'; r.mkdir()
for p in (root/'Review_Today').glob('*.html'): shutil.copy(p,r/p.name)
for p in (root/'Review_Today/Fonts').glob('*'):
 if p.is_file(): shutil.copy(p,r/p.name)
with (contents/'Info.plist').open('wb') as f: plistlib.dump(dict(CFBundleIdentifier='Rex.Review-Today.GoalContinuity.NativeQA',CFBundleName='GoalContinuityQA',CFBundleExecutable='GoalContinuityQA',CFBundlePackageType='APPL',QAProjectRoot=str(root)),f)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
print(app,flush=True)
PY
"$qa_dir/GoalContinuityQA.app/Contents/MacOS/GoalContinuityQA"
