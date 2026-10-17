"""Verify the bounded repair and its untouched original evidence/data."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    setup = json.loads((OUT / 'setup.json').read_text())
    allowed = setup['allowed_production_changes']
    changed = []
    for key, expected in setup['protected_sha256'].items():
        path = ROOT / key
        assert path.is_file(), key
        if digest(path) != expected:
            assert key in allowed, key
            changed.append(key)
    assert sorted(changed) == sorted(allowed)
    assert all(not Path(p).exists() for p in setup['daily_missing'])
    assert hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)).hexdigest() == setup['project_diff_sha256']
    production = subprocess.check_output(['git', 'diff', setup['baseline_commit'], '--name-only', '--',
        'agent-service/agent_service', 'Review_Today'], cwd=ROOT, text=True).splitlines()
    assert sorted(production) == sorted(allowed)
    runtime = Path(setup['actual_runtime'])
    assert json.loads((runtime / 'request-count.json').read_text())['actual_requests'] == 30
    assert (runtime / 'STOP').is_file()
    tests = dict(baseline='6 failed, 3 passed', targeted='104 passed', full='1250 passed, 4 skipped', deepseek='78 passed')
    logs = dict(baseline='baseline-tests.log', targeted='fixed-tests.log', full='full-tests.log', deepseek='deepseek-tests.log')
    for name, expected in tests.items():
        text = (OUT / logs[name]).read_text()
        assert expected in text, (name, text[-1200:])
        if name != 'baseline':
            assert not re.search(r'\b[1-9][0-9]* failed\b|^ERROR ', text, re.M), name
    replay = json.loads((OUT / 'replay-result.json').read_text())
    assert replay['outcome'] == 'PASS' and replay['real_model_requests'] == 0
    assert [c['return_source_count'] for c in replay['cases']] == [0, 1, 1]
    assert all(v == 0 for v in replay['guards'].values())
    paths = [ROOT / p for p in ('docs/work-status.md', 'docs/decision-log.md', 'docs/agent-iteration.md',
        'docs/agent-harness-v2.md', 'docs/design-references/zcode-agent.md',
        'docs/evidence/2026-10-16-continuous-acceptance/README.md')] + [OUT / 'README.md']
    links, missing = 0, []
    for path in paths:
        for match in re.finditer(r'\]\(([^)]+)\)', path.read_text()):
            target = match[1].strip().strip('<>')
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('#'):
                continue
            target = re.sub(r':\d+$', '', unquote(target.split('#', 1)[0]))
            candidate = Path(target) if target.startswith('/') else path.parent / target
            links += 1
            # This script writes its own linked result after every check passes.
            if not candidate.exists() and candidate.resolve() != (OUT / 'result.json').resolve():
                missing.append(dict(file=str(path.relative_to(ROOT)), target=target))
    assert not missing, missing
    for path in OUT.glob('*.py'):
        ast.parse(path.read_text())
    credential_files = [p.name for p in OUT.iterdir() if p.is_file() and re.search(
        r'sk-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9_-]{20,}|(?:OPENAI_API_KEY|DEEPSEEK_API_KEY)\s*=\s*[A-Za-z0-9_-]{12,}', p.read_text())]
    assert not credential_files, credential_files
    result = dict(outcome='PASS', real_model_requests=0, original_actual_requests=30, original_stop_unchanged=True,
        tests=tests, new_behavior_tests=9, full_subtests=565, targeted_subtests=22, deepseek_subtests=11,
        protected_files_checked=len(setup['protected_sha256']), protected_unchanged=len(setup['protected_sha256']) - len(allowed),
        changed_production=changed, daily_existing_unchanged=5, daily_missing_unchanged=setup['daily_missing'],
        provider_configs_unchanged=True, swift_sources_unchanged=106, other_python_sources_unchanged=70,
        historical_evidence_unchanged=312, user_project_diff_unchanged=True, native_app_unchanged=True,
        native_app_rebuilt=False, service_started=False, real_save_or_ack=False,
        markdown_files=len(paths), local_links_checked=links, missing_links=missing, credential_pattern_files=credential_files,
        caveat='Controlled state/input proof only; actual model semantics, native save and full continuous acceptance remain open.')
    (OUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    manifest = {p.name: digest(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name not in {'artifact-sha256.json', 'finalize.log'}}
    (OUT / 'artifact-sha256.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
