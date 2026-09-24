#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 - <<'PY'
import pathlib, subprocess, plistlib, shutil
root=pathlib.Path.cwd(); folder=root/'output/today-review-prototype'; app=folder/'TodayReviewPrototype.app'; contents=app/'Contents'; binary=contents/'MacOS/TodayReviewPrototype'; resources=contents/'Resources'
binary.parent.mkdir(parents=True,exist_ok=True); resources.mkdir(parents=True,exist_ok=True)
frameworks=contents/'Frameworks'; frameworks.mkdir(exist_ok=True)
fsrs=sorted(str(p) for p in (root/'Vendor/SwiftFSRS/Sources').rglob('*.swift'))
subprocess.run(['xcrun','swiftc','-parse-as-library','-swift-version','5','-target','arm64-apple-macos26.5','-emit-library','-emit-module','-module-name','FSRS','-emit-module-path',str(folder/'FSRS.swiftmodule'),'-Xlinker','-install_name','-Xlinker','@rpath/libFSRS.dylib',*fsrs,'-o',str(frameworks/'libFSRS.dylib')],check=True)
sources=[str(p) for p in (root/'Review_Today').glob('*.swift') if p.name!='Review_TodayApp.swift']+sorted(str(p) for p in (root/'tools/today-review-prototype').glob('*.swift'))
with (folder/'build.log').open('w') as log:
 result=subprocess.run(['xcrun','swiftc','-I',str(folder),'-L',str(frameworks),'-lFSRS','-Xlinker','-rpath','-Xlinker','@executable_path/../Frameworks','-parse-as-library','-swift-version','5','-default-isolation','MainActor','-target','arm64-apple-macos26.5',*sources,'-o',str(binary.with_suffix('.building'))],stdout=log,stderr=subprocess.STDOUT)
if result.returncode: print((folder/'build.log').read_text()); raise SystemExit(result.returncode)
binary.with_suffix('.building').replace(binary)
for name in ['MrBMotion.html','MascotMotion.html','ExamEntrySpine.html']:
 shutil.copy2(root/'Review_Today'/name,resources/name)
for p in (root/'Review_Today/Fonts').glob('*'):
 if p.is_file(): shutil.copy2(p,resources/p.name)
assets=folder/'PrototypeAssets.xcassets'; assets.mkdir(exist_ok=True)
shutil.copy2(root/'Review_Today/Assets.xcassets/Contents.json', assets/'Contents.json')
shutil.copytree(root/'Review_Today/Assets.xcassets/BrandDefaultLogo.imageset',assets/'BrandDefaultLogo.imageset',dirs_exist_ok=True)
shutil.copytree(root/'Review_Today/Assets.xcassets/TodayExamIcon.imageset',assets/'TodayExamIcon.imageset',dirs_exist_ok=True)
subprocess.run(['xcrun','actool',str(assets),'--compile',str(resources),'--platform','macosx','--minimum-deployment-target','26.5'],check=True,stdout=subprocess.DEVNULL)
with (contents/'Info.plist').open('wb') as f:
 plistlib.dump(dict(CFBundleIdentifier='Rex.Review-Today.TodayReviewPrototype',CFBundleName='TodayReviewPrototype',CFBundleDisplayName='Review Today · 交互原型',CFBundleExecutable='TodayReviewPrototype',CFBundlePackageType='APPL',LSMinimumSystemVersion='26.5',NSHighResolutionCapable=True,PreviewProjectRoot=str(root)),f)
subprocess.run(['codesign','--force','--sign','-',str(frameworks/'libFSRS.dylib')],check=True)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
print(app)
PY
