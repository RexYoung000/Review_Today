#!/usr/bin/env python3
"""Export the saved Icon Composer document with Apple's own renderer."""
import hashlib
import argparse
import json
from pathlib import Path
import struct
import subprocess

base = Path(__file__).resolve().parent
root = base.parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--version', choices=['v1', 'v2', 'v3'], default='v3')
version = parser.parse_args().version
document = base / ('ReviewToday-Glass-v1.icon' if version == 'v1' else f'ReviewToday-MetalGlass-{version}.icon')
developer = Path(subprocess.check_output(['xcode-select', '-p'], text=True).strip())
renderer = developer.parent / 'Applications/Icon Composer.app/Contents/Executables/ictool'
source = root / 'brand/refresh-2026-09/masters/mark-alpha.png'
imported = document / 'Assets/mark-alpha.png'
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert digest(source) == digest(imported), 'The accepted R source must remain byte-identical'
out = base / ('icon-renders' if version == 'v1' else f'icon-renders-{version}')
out.mkdir(exist_ok=True)
exports = []
for name, rendition in [('default', 'Default'), ('dark', 'Dark'), ('mono', 'Mono')]:
    for size in [16, 32, 64, 128, 256, 512, 1024]:
        file = out / f'{name}-{size}.png'
        subprocess.run([str(renderer), str(document), '--export-image', '--output-file', str(file),
                        '--platform', 'macOS', '--rendition', rendition,
                        '--width', str(size), '--height', str(size), '--scale', '1'], check=True, capture_output=True)
        data = file.read_bytes()
        assert data[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II', data[16:24]) == (size, size)
        exports.append({'file': file.name, 'size': size, 'rendition': rendition})
light_checks = []
if version != 'v1':
    saved = json.loads((document / 'icon.json').read_text())
    mark_layers = [layer for group in saved['groups'] for layer in group['layers']
                   if layer.get('image-name') == 'mark-alpha.png']
    assert len(mark_layers) == 2
    assert mark_layers[0]['position'] == mark_layers[1]['position']
    assert mark_layers[0]['opacity'] == 0.65 and not mark_layers[0]['glass']
    if version == 'v3':
        previous = json.loads((base / 'ReviewToday-MetalGlass-v2.icon/icon.json').read_text())
        assert saved['groups'][1:] == previous['groups'][1:], 'Both satin-metal R groups must remain unchanged'
        assert saved['fill'] == previous['fill'], 'Keep the approved neutral background fill'
        assert saved['groups'][0]['shadow']['opacity'] == 0
        assert not saved['groups'][0]['translucency']['enabled']
    for rendition in ['Default', 'Dark']:
        for angle in [-90, 0, 45]:
            file = out / f'{rendition.lower()}-light-{angle}.png'
            subprocess.run([str(renderer), str(document), '--export-image', '--output-file', str(file),
                            '--platform', 'macOS', '--rendition', rendition, '--width', '512',
                            '--height', '512', '--scale', '1', '--light-angle', str(angle)],
                           check=True, capture_output=True)
            light_checks.append({'file': file.name, 'light_angle': angle, 'rendition': rendition})
report = {'renderer': str(renderer), 'renderer_version': json.loads(subprocess.check_output([str(renderer), '--version'], text=True)),
          'master_sha256': digest(source), 'imported_master_identical': True, 'document_sha256': digest(document / 'icon.json'),
          'asset_sha256': {p.name: digest(p) for p in sorted((document / 'Assets').iterdir()) if p.is_file()},
          'exports': exports, 'light_checks': light_checks, 'platform': 'macOS', 'note': 'Native icon rendering, not Dock or macOS 27 integration acceptance.'}
(base / ('icon-validation.json' if version == 'v1' else f'icon-validation-{version}.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(f'PASS: {len(exports)} native size exports and {len(light_checks)} light checks; accepted R source unchanged')
