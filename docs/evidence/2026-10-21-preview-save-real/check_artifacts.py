"""Validate the archived decision-255 evidence without paid or UI operations."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    changed = subprocess.check_output(['git', 'diff', '--name-only'], cwd=ROOT, text=True).splitlines()
    documents = [ROOT / name for name in changed if name.endswith('.md')] + [OUT / 'README.md']
    checked_links = 0
    for path in documents:
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text()):
            if target.startswith(('https:', 'http:', 'app:', '#')):
                continue
            target = target.split('#', 1)[0].strip('<>')
            assert (path.parent / target).exists(), f'Broken local link in {path.name}: {target}'
            checked_links += 1
    for path in OUT.glob('*.json'):
        json.loads(path.read_text())
    for path in OUT.glob('*.jsonl'):
        for line in path.read_text().splitlines():
            json.loads(line)
    for path in OUT.glob('*.py'):
        ast.parse(path.read_text(), filename=str(path))

    secrets = set()
    for name in ('agent-service/.env', 'agent-service/providers/deepseek/.env', 'agent-service/providers/web/.env'):
        for key, value in dotenv_values(ROOT / name).items():
            if value and len(value) >= 12 and any(part in key.upper() for part in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
                secrets.add(value.encode())
    for path in OUT.iterdir():
        if path.is_file():
            content = path.read_bytes()
            assert not any(value in content for value in secrets), f'Credential match in artifact {path.name}'
    for path in OUT.glob('*.log'):
        path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines()) + ('\n' if path.stat().st_size else ''))
    prepared = ROOT / 'docs/evidence/2026-10-21-preview-save-preflight'
    manifest = json.loads((prepared / 'manifest.json').read_text())
    manifest['README.md'] = digest(prepared / 'README.md')
    assert all(digest(prepared / name) == expected for name, expected in manifest.items())
    write(prepared / 'manifest.json', manifest)
    result = dict(outcome='PASS', local_markdown_links_checked=checked_links,
        json_and_jsonl_parse=True, python_parse=True, configured_credential_scan='PASS_NO_VALUES_EMITTED',
        prepared_manifest_preserved_except_status_link_readme=True, paid_calls=0,
        note='Only evidence .log trailing whitespace normalized; semantic JSON and outputs preserved.')
    write(OUT / 'artifact-check.json', result)
    manifest = {path.name: digest(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != 'manifest.json'}
    write(OUT / 'manifest.json', manifest)
    assert all(digest(OUT / name) == expected for name, expected in manifest.items())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
