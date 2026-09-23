#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
qa_dir="$(mktemp -d /tmp/review-today-integration-qa.XXXXXX)"
python3 - "$qa_dir" <<'PY'
import pathlib, subprocess, plistlib, shutil, sys
root=pathlib.Path.cwd(); app=pathlib.Path(sys.argv[1])/'TodayReviewQA.app'; contents=app/'Contents'; binary=contents/'MacOS/TodayReviewQA'; binary.parent.mkdir(parents=True)
sources=[str(p) for p in (root/'Review_Today').glob('*.swift') if p.name!='Review_TodayApp.swift']+[str(root/'tests/mac/TodayReviewIntegrationQA.swift')]
subprocess.run(['tests/mac/swift-with-fsrs.py','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor','-enable-upcoming-feature','MemberImportVisibility',*sources,'-o',str(binary)],check=True)
r=contents/'Resources';r.mkdir()
for p in list((root/'Review_Today/Fonts').glob('*'))+list((root/'Review_Today').rglob('*.html')):
 if p.is_file(): shutil.copy(p,r/p.name)
with (contents/'Info.plist').open('wb') as f:plistlib.dump(dict(CFBundleIdentifier='Rex.Review-Today.UIIntegrationQA',CFBundleName='TodayReviewQA',CFBundleExecutable='TodayReviewQA',CFBundlePackageType='APPL',QAEvidence=str(root/'docs/evidence/2026-09-23-today-review-integration')),f)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
print(app,flush=True)
PY
