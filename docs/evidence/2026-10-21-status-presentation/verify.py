"""Verify this offline presentation change and retained data protection."""
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root):
    return {str(p.relative_to(root)): digest(p) for p in root.rglob('*') if p.is_file()}


def main():
    setup = read(OUT / 'setup.json')
    native = Path(setup['native_directory'])
    support = Path(setup['support_dir'])
    assert not subprocess.run(['pgrep', '-fl', str(native / 'StatusPresentationQA.app/Contents/MacOS/')],
        capture_output=True, text=True).stdout.strip()
    # Reuse the reader with the newly compiled module; no App or service starts.
    reader = native / 'final-native-reader'
    flags = ['xcrun', 'swiftc', '-parse-as-library', '-D', 'DEBUG', '-swift-version', '5',
        '-default-isolation', 'MainActor', '-enable-upcoming-feature', 'MemberImportVisibility',
        '-I', str(support), '-L', str(support), '-lReviewTodayContractSupport', '-lFSRS',
        '-Xlinker', '-rpath', '-Xlinker', str(support)]
    with (OUT / 'native-readback.log').open('w') as log:
        subprocess.run(flags + [str(ROOT / 'docs/evidence/2026-10-16-status-native-input/NativeDiskRead.swift'),
            '-o', str(reader)], check=True, stdout=log, stderr=subprocess.STDOUT)
        subprocess.run([str(reader), str(native)], check=True, stdout=log, stderr=subprocess.STDOUT)
    shutil.copy2(native / 'native-disk-read.json', OUT / 'native-disk-read.json')
    actual = read(OUT / 'native-disk-read.json')
    original = read(OUT.parent / '2026-10-21-preview-save-real/native-disk-read.json')
    assert actual == original
    assert actual['knowledge_count'] == 4 and all(not c['review'] for c in actual['cards'])
    for name, expected in setup['protected_fingerprints'].items():
        assert digest(ROOT / name) == expected, name
    for directory, expected in setup['protected_runtime_files'].items():
        assert files(Path(directory)) == expected, directory
    assert files(Path(setup['prior_app'])) == setup['prior_app_files']
    assert hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'],
        cwd=ROOT)).hexdigest() == setup['project_diff_sha256']
    comparison = read(OUT / 'reply-comparison.json')
    assert comparison['prior_characters'] == 166 and comparison['corrected_characters'] == 57
    assert comparison['real_model_requests'] == comparison['real_web_operations'] == 0
    for name in ('native-list-light.txt', 'native-list-dark-compact.txt'):
        text = (OUT / name).read_text()
        for index, title in enumerate(('检索相似度', '生成不忠实', '核对来源与适用条件', '适用边界丢失'), 1):
            assert f'{index}. {title}' in text
    for name in ('native-source-dark.txt', 'native-paper-dark.txt'):
        text = (OUT / name).read_text()
        assert '来源摘录' in text and '来自你提交的原文' not in text
        assert '仅保存资料 · 未参与复习' in text
    assert '85 passed' in (OUT / 'service-checks.log').read_text()
    assert '60 subtests passed' in (OUT / 'service-checks.log').read_text()
    contract_log = (OUT / 'native-contracts.log').read_text()
    for name in ('AnswerDocumentContractTests', 'TopicCaptureContractTests'):
        assert f'PASS executable: {name}' in contract_log
    changed = subprocess.check_output(['git', 'diff', setup['baseline_commit'], '--name-only'], cwd=ROOT, text=True).splitlines()
    production = {name for name in changed if name.startswith(('Review_Today/', 'agent-service/agent_service/'))}
    assert production == set(setup['expected_changed_production_files'])
    for path in OUT.glob('*.log'):
        value = path.read_text()
        path.write_text('\n'.join(line.rstrip() for line in value.splitlines()) + ('\n' if value else ''))
    docs = [ROOT / name for name in changed if name.endswith('.md')] + [OUT / 'README.md']
    links = 0
    local_targets = []
    for path in docs:
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text()):
            if target.startswith(('http:', 'https:', '#', 'app:')):
                continue
            local = (path.parent / target.split('#', 1)[0].strip('<>')).resolve()
            # result.json is generated below, after the substantive checks.
            assert local.exists() or local == OUT / 'result.json', (path.name, target)
            local_targets.append(local)
            links += 1
    secrets = set()
    for name in ('agent-service/.env', 'agent-service/providers/deepseek/.env', 'agent-service/providers/web/.env'):
        secrets.update(value.encode() for key, value in dotenv_values(ROOT / name).items()
            if value and len(value) >= 12 and any(t in key.upper() for t in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')))
    for path in OUT.iterdir():
        if path.is_file():
            assert not any(value in path.read_bytes() for value in secrets), path.name
        if path.suffix == '.json':
            json.loads(path.read_text())
        if path.suffix == '.py':
            ast.parse(path.read_text())
    result = dict(outcome='PASS_IMPLEMENTED_OFFLINE_AND_NATIVE_COMPONENTS', decision=256,
        production_files=sorted(production), added_service_tests=3, service_tests_passed=85,
        service_subtests_passed=60, native_contract_groups=2,
        controlled_real_intent_replay=True, native_list_and_source_components=True,
        list_ax_names_present=True, light_regular_and_dark_compact_checked=True,
        native_readback_unchanged=True, native_cards=4, native_messages=15, native_runs=8,
        source_reference_inference_removed=True, prior_reply_characters=166, corrected_reply_characters=57,
        real_model_requests=0, real_web_operations=0,
        protected_source_configuration_files=len(setup['protected_fingerprints']),
        protected_old_runtime_files=sum(len(v) for v in setup['protected_runtime_files'].values()),
        original_qa_app_unchanged=True, project_diff_preserved=True,
        daily_app_updated=False, native_qa_closed=True, real_model_new_decision_verified=False,
        full_voiceover_not_run=True, user_experience_accepted=False, m1_closed=False,
        local_markdown_links_checked=links, credential_scan='PASS_NO_VALUES_EMITTED')
    write(OUT / 'result.json', result)
    assert all(path.exists() for path in local_targets)
    setup['status'] = 'COMPLETED_OFFLINE_NATIVE_PASS_DAILY_NOT_UPDATED'
    write(OUT / 'setup.json', setup)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    write(OUT / 'manifest.json', {p.name: digest(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != 'manifest.json'})


if __name__ == '__main__':
    main()
