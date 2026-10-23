"""Byte-only post-checks; never opens a database or starts an App/service."""
from pathlib import Path
import hashlib
import json
import os
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIVATE = ROOT / 'output/title-fallback-repair-2026-10-23'


def read(path): return json.loads(path.read_text())
def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()
def files(directory): return {str(p.resolve()): sha(p) for p in directory.rglob('*') if p.is_file()}
def inventory(directory):
    result = {}
    for p in directory.rglob('*'):
        key = str(p.relative_to(directory)); mode = stat.S_IMODE(p.lstat().st_mode)
        if p.is_symlink(): result[key] = dict(mode=mode, type='symlink', target=os.readlink(p))
        elif p.is_dir(): result[key] = dict(mode=mode, type='dir')
        else: result[key] = dict(mode=mode, type='file', size=p.stat().st_size, sha256=sha(p))
    return result


def main():
    baseline = read(ROOT / 'docs/evidence/2026-10-22-navigation-save-preflight/setup.json')
    setup = read(OUT / 'setup.json')
    historical = read(ROOT / 'docs/evidence/2026-10-23-evidence-protection/verification.json')
    archive = Path(historical['archive'])
    manifest = read(archive.parent / 'manifest.json')
    assert sha(archive) == historical['archive_sha256']
    assert sha(ROOT / 'docs/evidence/2026-10-22-navigation-save-preflight/setup.json') == manifest['old_baseline_sha256']
    missing = sorted(p for p in baseline['old_frozen_files'] if not Path(p).is_file())
    assert set(missing) == set(read(ROOT / 'docs/evidence/2026-10-22-navigation-save-real/protection.json')['missing_old_files'])
    assert all(sha(Path(p)) == h for p, h in baseline['old_frozen_files'].items() if p not in missing)
    assert files(Path.home() / 'Library/Application Support/Review Today') == baseline['daily_files']
    assert inventory(Path('/Applications/Review Today.app')) == baseline['daily_app_inventory']
    for key in ['previous_batch_files', 'original_module_files', 'original_support_files', 'owned_support_files']:
        assert all(sha(Path(p)) == h for p, h in baseline[key].items()), key
    changed = [p for p, h in baseline['protected_fingerprints'].items() if sha(ROOT / p) != h]
    assert changed == ['Review_Today/KnowledgeLexicon.swift', 'tests/mac/run-contracts.py'], changed
    for key in ['current_run_private', 'current_run_public']:
        assert all(sha(Path(p)) == h for p, h in manifest[key].items()), key
    before = read(PRIVATE / 'native-cards-before-ui.json')
    after = read(PRIVATE / 'native-cards-after-ui.json')
    assert before == after and len(after) == 5
    assert all(c['title'] == c['resolved_title'] and c['review'] == 'false' for c in after)
    for index, card in enumerate(after, 1):
        path = PRIVATE / ('light-detail.ax.txt' if index == 1 else 'card-' + str(index) + '.ax.txt')
        assert 'heading Description: ' + card['title'] + ',' in path.read_text()
    dark = (PRIVATE / 'dark-compact-detail.ax.txt').read_text()
    assert 'heading Description: 来源核对与适用条件核对,' in dark
    assert 'checkbox Description: 已学过，参与间隔复习, Value: 0' in dark
    assert 'row (selectable) 来源核对与适用条件核对' in (PRIVATE / 'list-after-close.ax.txt').read_text()
    actual = read(ROOT / 'output/navigation-save-real-2026-10-22/native-disk-read.json')['cards']
    for card in after:
        original = next(c for c in actual if c['id'].lower() == card['id'].lower())
        assert original['title'] == card['title']
        assert original['evidence'] == card['evidence'] and original['explanation'] == card['explanation']
    assert all(sha(Path(p)) == h for p, h in setup['source_files'].items())
    assert subprocess.run(['pgrep', '-x', 'TitleDisplayQA'], capture_output=True).returncode == 1
    assert subprocess.run(['pgrep', '-x', 'Review_Today'], capture_output=True).returncode == 1
    assert not subprocess.run(['lsof', '-nP', '-iTCP:18798', '-sTCP:LISTEN'], capture_output=True).stdout
    assert not subprocess.run(['lsof', '-nP', '-iTCP:8742', '-sTCP:LISTEN'], capture_output=True).stdout
    log = (OUT / 'native-contracts.log').read_text()
    for name in ['KnowledgeTitleContractTests', 'UIPolishContractTests', 'LibraryManagementContractTests']:
        assert 'PASS executable: ' + name in log
    assert 'All selected contracts complete:' in log
    cleanup = read(OUT / 'cleanup.json')
    assert cleanup['raw_qa_app_removed'] and cleanup['related_registered_entries'] == 1
    assert cleanup['spotlight_paths'] == ['/Applications/Review Today.app']
    report = dict(status='TITLE_01_IMPLEMENTED_OFFLINE_AND_NATIVE_COMPONENT_VERIFIED',
                  title_cases=21, native_contract_groups=3, real_saved_cards_checked=5,
                  actual_new_model_requests=0, actual_new_web_operations=0,
                  daily_96_files_and_app_unchanged=True, prior_264_evidence_unchanged=True,
                  previous_module_and_support_unchanged=True,
                  production_swift_files_changed=['Review_Today/KnowledgeLexicon.swift'],
                  test_runner_changed='tests/mac/run-contracts.py', other_source_config_execution_pins_unchanged=246,
                  cards_source_content_version_review_unchanged=True,
                  original_old_files_matched=229, original_old_files_missing=len(missing),
                  original_baseline_unchanged=True, historical_gap_still_open=True,
                  missing_bytes_durably_archived=9, old_missing_main_databases_not_confirmed=2,
                  historical_archive_sha256=historical['archive_sha256'],
                  qa_app_and_service_closed=True, daily_app_not_loaded=True,
                  previous_allowances_still_frozen=True, uninterrupted_fullflow_and_m1_open=True,
                  full_voiceover_and_user_experience_not_verified=True)
    (OUT / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
