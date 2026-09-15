#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
qa_dir="$(mktemp -d /tmp/review-today-topic-qa.XXXXXX)"
python3 - "$qa_dir" <<'PY'
import pathlib, subprocess, plistlib, shutil, sys
root=pathlib.Path.cwd(); app=pathlib.Path(sys.argv[1])/'TopicCaptureQA.app'; contents=app/'Contents'; binary=contents/'MacOS/TopicCaptureQA'; binary.parent.mkdir(parents=True)
sources=[str(p) for p in (root/'Review_Today').glob('*.swift') if p.name!='Review_TodayApp.swift']+[str(root/'tests/mac/TopicCaptureNativeQA.swift'),str(root/'tests/mac/KnowledgeIngestionFixture.swift')]
subprocess.run(['xcrun','swiftc','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor','-enable-upcoming-feature','MemberImportVisibility',*sources,'-o',str(binary)],check=True)
r=contents/'Resources'; r.mkdir()
for p in (root/'Review_Today').glob('*.html'): shutil.copy(p,r/p.name)
for p in (root/'Review_Today/Fonts').glob('*'):
 if p.is_file(): shutil.copy(p,r/p.name)
with (contents/'Info.plist').open('wb') as f: plistlib.dump(dict(CFBundleIdentifier='Rex.Review-Today.TopicCapture.NativeQA',CFBundleName='TopicCaptureQA',CFBundleExecutable='TopicCaptureQA',CFBundlePackageType='APPL',QAProjectRoot=str(root)),f)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
print(app,flush=True)
PY
"$qa_dir/TopicCaptureQA.app/Contents/MacOS/TopicCaptureQA"
