#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 - <<'PY'
import pathlib, plistlib, subprocess, platform
root = pathlib.Path.cwd()
folder = root / 'output/dictation-prototype'
app = folder / 'DictationPrototype.app'
contents = app / 'Contents'
binary = contents / 'MacOS/DictationPrototype'
binary.parent.mkdir(parents=True, exist_ok=True)
sources = sorted(str(p) for p in (root / 'tools/dictation-prototype').glob('*.swift'))
with (folder / 'build.log').open('w') as log:
    result = subprocess.run(['xcrun', 'swiftc', '-parse-as-library', '-swift-version', '5', '-default-isolation', 'MainActor', '-target', platform.machine() + '-apple-macos26.5', *sources, '-o', str(binary.with_suffix('.building'))], stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    print((folder / 'build.log').read_text())
    raise SystemExit(result.returncode)
binary.with_suffix('.building').replace(binary)
with (contents / 'Info.plist').open('wb') as f:
    plistlib.dump(dict(CFBundleIdentifier='Rex.Review-Today.DictationPrototype', CFBundleDisplayName='Review Today · 听写对照', CFBundleName='DictationPrototype', CFBundleExecutable='DictationPrototype', CFBundlePackageType='APPL', LSMinimumSystemVersion='26.5', NSHighResolutionCapable=True, PreviewProjectRoot=str(root)), f)
subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
print(app)
PY
