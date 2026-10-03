#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
# Build only. Open the resulting .app through native UI automation.
# Reuse an existing current-source contract module instead of recompiling the app.
python3 - "$@" <<'PY'
import json, pathlib, plistlib, shutil, subprocess, sys
root = pathlib.Path.cwd()
if len(sys.argv) != 2:
    raise SystemExit('Usage: bash tests/mac/run-dictation-integration.sh <shared-contract-directory>\nFirst run contracts with an isolated home:\n  CFFIXED_USER_HOME="$(mktemp -d /tmp/review-today-contract-home.XXXXXX)" bash tests/mac/run-contracts.sh DictationContractTests\nThen pass the printed isolated contract directory, or reuse a completed current-source contract run.')
shared = pathlib.Path(sys.argv[1]).resolve()
required = ['ReviewTodayContractSupport.swiftmodule', 'libReviewTodayContractSupport.dylib', 'FSRS.swiftmodule', 'libFSRS.dylib']
if any(not (shared / name).is_file() for name in required):
    raise SystemExit('Pass a completed current-source shared contract directory as the first argument; no app build was started.')
folder = root / 'output/dictation-integration'
app = folder / 'DictationIntegration.app'
contents = app / 'Contents'
binary = contents / 'MacOS/DictationIntegrationBin'
frameworks = contents / 'Frameworks'
home = folder / 'isolated-home'
binary.parent.mkdir(parents=True, exist_ok=True)
frameworks.mkdir(parents=True, exist_ok=True)
home.mkdir(parents=True, exist_ok=True)
for name in ['libFSRS.dylib', 'libReviewTodayContractSupport.dylib']:
    target = frameworks / name
    shutil.copy2(shared / name, target)
    subprocess.run(['install_name_tool', '-id', '@rpath/' + name, str(target)], check=True)
support = frameworks / 'libReviewTodayContractSupport.dylib'
# /tmp resolves to /private/tmp, while the shared library may retain /tmp in
# its load command. Rewrite the actual dependency instead of guessing spelling.
dependencies = subprocess.check_output(['otool', '-L', str(support)], text=True).splitlines()[1:]
for line in dependencies:
    dependency = line.strip().split(' (', 1)[0]
    if dependency.endswith('/libFSRS.dylib') and dependency != '@rpath/libFSRS.dylib':
        subprocess.run(['install_name_tool', '-change', dependency, '@rpath/libFSRS.dylib', str(support)], check=True)
sources = sorted(str(p) for p in (root / 'tools/dictation-integration').glob('*.swift'))
flags = ['-parse-as-library', '-D', 'DEBUG', '-swift-version', '5', '-default-isolation', 'MainActor', '-enable-upcoming-feature', 'MemberImportVisibility']
with (folder / 'build.log').open('w') as log:
    result = subprocess.run(['xcrun', 'swiftc', *flags, '-I', str(shared), '-L', str(frameworks), '-lReviewTodayContractSupport', '-lFSRS', '-Xlinker', '-rpath', '-Xlinker', '@executable_path/../Frameworks', *sources, '-o', str(binary)], stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    print((folder / 'build.log').read_text())
    raise SystemExit(result.returncode)
subprocess.run(['xcrun', 'clang', '-DINTEGRATION_HOME=' + json.dumps(str(home)), str(root / 'tools/dictation-integration/Launcher.c'), '-o', str(binary.parent / 'DictationIntegration')], check=True)
with (contents / 'Info.plist').open('wb') as file:
    plistlib.dump(dict(CFBundleIdentifier='Rex.Review-Today.DictationIntegration', CFBundleName='DictationIntegration', CFBundleDisplayName='Review Today · 听写集成验收', CFBundleExecutable='DictationIntegration', CFBundlePackageType='APPL', NSHighResolutionCapable=True, PreviewProjectRoot=str(root), DictationIntegrationHome=str(home), LSEnvironment=dict(CFFIXED_USER_HOME=str(home), REVIEW_TODAY_M1_UI_FIXTURE='1')), file)
for path in [frameworks / 'libFSRS.dylib', frameworks / 'libReviewTodayContractSupport.dylib', binary, app]:
    subprocess.run(['codesign', '--force', '--sign', '-', str(path)], check=True)
subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
(folder / 'build-provenance.json').write_text(json.dumps(dict(shared=str(shared), isolated_home=str(home), note='Real production module, injected transport and synthetic volume; build only.'), ensure_ascii=False, indent=2) + '\n')
print(app)
PY
