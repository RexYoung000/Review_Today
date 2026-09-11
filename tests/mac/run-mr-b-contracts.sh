#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
node --test tools/mascot-motion/test/mr-b.test.mjs
node tools/mascot-motion/src/build-mr-b-preview.mjs
python3 - <<'PY'
import pathlib,plistlib,shutil,subprocess
folder=pathlib.Path('output/mr-b-preview');app=folder/'MrBTests.app';contents=app/'Contents';binary=contents/'MacOS/MrBTests';resources=contents/'Resources'
binary.parent.mkdir(parents=True,exist_ok=True);resources.mkdir(parents=True,exist_ok=True)
subprocess.run(['xcrun','swiftc','-parse-as-library','-swift-version','5','-default-isolation','MainActor','Review_Today/MrBPresentation.swift','tools/mascot-motion/native/MrBPreviewModel.swift','tests/mac/MrBPresentationTests.swift','-o',str(binary)],check=True)
shutil.copy2(folder/'MrBMotion.html',resources/'MrBMotion.html')
with (contents/'Info.plist').open('wb') as f:plistlib.dump(dict(CFBundleIdentifier='Rex.Review-Today.MrBTests',CFBundleName='MrBTests',CFBundleExecutable='MrBTests',CFBundlePackageType='APPL'),f)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
subprocess.run([str(binary)],check=True)
PY
