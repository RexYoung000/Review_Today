#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 - <<'PY'
import pathlib, plistlib, shutil, subprocess, tempfile
folder=pathlib.Path(tempfile.mkdtemp(prefix='review-web-feedback-', dir='/tmp'))
app=folder/'WebFeedbackQA.app'
contents=app/'Contents'; binary=contents/'MacOS'/'WebFeedbackQA'; resources=contents/'Resources'
binary.parent.mkdir(parents=True); resources.mkdir()
sources=[str(p) for p in pathlib.Path('Review_Today').glob('*.swift') if p.name!='Review_TodayApp.swift']
with (folder/'build.log').open('w') as log:
    result=subprocess.run(['xcrun','swiftc','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor','-enable-upcoming-feature','MemberImportVisibility',*sources,'tests/mac/WebFeedbackPreview.swift','-o',str(binary)],stdout=log,stderr=subprocess.STDOUT)
if result.returncode:
    print((folder/'build.log').read_text()); raise SystemExit(result.returncode)
for resource in pathlib.Path('Review_Today').glob('*.html'): shutil.copy2(resource,resources/resource.name)
(contents/'Info.plist').write_bytes(plistlib.dumps(dict(CFBundleIdentifier='Rex.Review-Today.WebFeedbackQA',CFBundleExecutable=binary.name,CFBundleName='WebFeedbackQA',CFBundlePackageType='APPL',NSHighResolutionCapable=True)))
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
print(app,flush=True)
subprocess.run(['open',str(app)],check=True)
PY
