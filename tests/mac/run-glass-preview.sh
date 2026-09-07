#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
preview_root="$PWD/output/glass-preview"
mkdir -p "$preview_root"
python3 - "$preview_root" <<'PY'
import pathlib, plistlib, shutil, subprocess, sys
folder = pathlib.Path(sys.argv[1])
app = folder / 'ReviewTodayGlassPreview.app'
contents = app / 'Contents'
binary = contents / 'MacOS' / 'ReviewTodayGlassPreview'
resources = contents / 'Resources'
binary.parent.mkdir(parents=True, exist_ok=True)
resources.mkdir(parents=True, exist_ok=True)
sources = sorted(str(p) for p in pathlib.Path('Review_Today').glob('*.swift') if p.name != 'Review_TodayApp.swift')
commands = [
    ['xcrun', 'swiftc', '-parse-as-library', '-D', 'DEBUG', '-swift-version', '5', '-default-isolation', 'MainActor',
     '-target', 'arm64-apple-macos26.5', *sources, 'tests/mac/GlassMaterialPreview.swift', '-o', str(binary)],
    ['xcrun', 'actool', 'Review_Today/Assets.xcassets', '--compile', str(resources), '--platform', 'macosx',
     '--minimum-deployment-target', '26.5', '--target-device', 'mac', '--app-icon', 'AppIcon',
     '--output-partial-info-plist', str(folder / 'asset-info.plist')],
]
with (folder / 'build.log').open('w') as log:
    for command in commands:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            log.flush()
            print((folder / 'build.log').read_text())
            raise SystemExit(result.returncode)
info = dict(CFBundleIdentifier='Rex.Review-Today.GlassPreview', CFBundleName='Review Today Glass Preview',
            CFBundleDisplayName='Review Today 玻璃小样', CFBundleExecutable=binary.name,
            CFBundlePackageType='APPL', CFBundleVersion='1', CFBundleShortVersionString='1.0',
            LSMinimumSystemVersion='26.5', NSHighResolutionCapable=True)
info.update(plistlib.loads((folder / 'asset-info.plist').read_bytes()))
# Shared native views may load bundled local HTML (for example the mascot view).
for resource in pathlib.Path('Review_Today').glob('*.html'):
    shutil.copy2(resource, resources / resource.name)
with (contents / 'Info.plist').open('wb') as file:
    plistlib.dump(info, file)
# A standalone preview identity; the project's daily signing configuration is untouched.
subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
print(app)
PY
