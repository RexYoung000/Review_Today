#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 - <<'PY'
import pathlib, plistlib, shutil, subprocess
root = pathlib.Path.cwd()
folder = root / 'output/ingestion-preview'
app = folder / 'KnowledgeIngestionPreview.app'
contents = app / 'Contents'
binary = contents / 'MacOS/KnowledgeIngestionPreview'
resources = contents / 'Resources'
binary.parent.mkdir(parents=True, exist_ok=True)
resources.mkdir(parents=True, exist_ok=True)
sources = sorted(str(p) for p in pathlib.Path('Review_Today').glob('*.swift') if p.name != 'Review_TodayApp.swift')
commands = [
    ['xcrun', 'swiftc', '-parse-as-library', '-D', 'DEBUG', '-swift-version', '5', '-default-isolation', 'MainActor', '-target', 'arm64-apple-macos26.5', *sources, 'tests/mac/KnowledgeIngestionFixture.swift', 'tests/mac/KnowledgeIngestionPreview.swift', '-o', str(binary)],
    ['xcrun', 'actool', 'Review_Today/Assets.xcassets', '--compile', str(resources), '--platform', 'macosx', '--minimum-deployment-target', '26.5', '--target-device', 'mac', '--app-icon', 'AppIcon', '--output-partial-info-plist', str(folder / 'asset-info.plist')]
]
with (folder / 'build.log').open('w') as log:
    for command in commands:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            log.flush(); print((folder / 'build.log').read_text()); raise SystemExit(result.returncode)
info = dict(CFBundleIdentifier='Rex.Review-Today.IngestionPreview', CFBundleName='LibrarySessionPreview', CFBundleDisplayName='知识入库原生验收', CFBundleExecutable=binary.name, CFBundlePackageType='APPL', LSMinimumSystemVersion='26.5', NSHighResolutionCapable=True, PreviewProjectRoot=str(root))
info.update(plistlib.loads((folder / 'asset-info.plist').read_bytes()))
for resource in pathlib.Path('Review_Today').glob('*.html'):
    shutil.copy2(resource, resources / resource.name)
fonts = pathlib.Path('Review_Today/Fonts')
if fonts.exists():
    # Match Xcode's flattened resource bundle and BrandTypography's lookup.
    for font_resource in fonts.iterdir():
        if font_resource.is_file():
            shutil.copy2(font_resource, resources / font_resource.name)
for localized in pathlib.Path('Review_Today').glob('*.lproj'):
    shutil.copytree(localized, resources / localized.name, dirs_exist_ok=True)
with (contents / 'Info.plist').open('wb') as file:
    plistlib.dump(info, file)
subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
print(app)
PY
