#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
node tools/mascot-motion/src/build-mr-b-preview.mjs
python3 - <<'PY'
import pathlib,plistlib,shutil,subprocess,os
root=pathlib.Path.cwd();folder=root/'output/mr-b-preview';app=folder/(os.environ.get('MR_B_PREVIEW_APP','MrBPreview')+'.app');contents=app/'Contents';binary=contents/'MacOS/MrBPreview';resources=contents/'Resources'
binary.parent.mkdir(parents=True,exist_ok=True);resources.mkdir(parents=True,exist_ok=True)
sources=['Review_Today/MrBPresentation.swift']+sorted(str(p) for p in pathlib.Path('tools/mascot-motion/native').glob('*.swift'))
with (folder/'build.log').open('w') as log:
 r=subprocess.run(['xcrun','swiftc','-parse-as-library','-swift-version','5','-default-isolation','MainActor','-target','arm64-apple-macos26.5',*sources,'-o',str(binary.with_suffix('.building'))],stdout=log,stderr=subprocess.STDOUT)
if r.returncode:print((folder/'build.log').read_text());raise SystemExit(r.returncode)
binary.with_suffix('.building').replace(binary)
shutil.copy2(folder/'MrBMotion.html',resources/'MrBMotion.html')
with (contents/'Info.plist').open('wb') as f:plistlib.dump(dict(CFBundleIdentifier=os.environ.get('MR_B_PREVIEW_BUNDLE','Rex.Review-Today.MrBPreview'),CFBundleDisplayName=('Mr. B 接触短样' if os.environ.get('MR_B_PREVIEW_APP') else 'Mr. B 原生试演'),CFBundleName=os.environ.get('MR_B_PREVIEW_APP','MrBPreview'),CFBundleExecutable='MrBPreview',CFBundlePackageType='APPL',LSMinimumSystemVersion='26.5',NSHighResolutionCapable=True,PreviewProjectRoot=str(root)),f)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
print(app)
PY
