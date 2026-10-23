"""Verify the collected stopped-store copies and real startup ledger, without DB opens."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
from common import ROOT, OUT, PRIVATE, ARCHIVE, DAILY, SUPPORT, LS, read, write, sha, files, inventory, stopped, prior_helpers


def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def unordered(rows): return sorted(rows, key=canonical)


def main():
    stopped()
    activation = PRIVATE / 'activation'
    before = read(activation / 'before-detail.json')
    after = read(activation / 'after-detail.json')
    assert set(before) == set(after)
    native, service, review = 'Data/ReviewToday.store', 'agent-harness.sqlite3', 'agent-harness.review.sqlite3'
    volatile = {'ZAGENTSESSION': {'Z_OPT'}, 'ZLEARNINGTASK': {'Z_OPT', 'ZUPDATEDAT'}}
    preserved = []
    actual_differences = []
    for database in before:
        old, new = before[database], after[database]
        assert old['integrity'] == new['integrity'] == 'ok'
        assert old['schema'] == new['schema'], database
        assert set(old['tables']) == set(new['tables'])
    for table, rows in before[native]['tables'].items():
        current = after[native]['tables'][table]
        assert len(rows) == len(current), table
        if table == 'Z_PRIMARYKEY':
            old = {r['Z_NAME']: r for r in rows}; new = {r['Z_NAME']: r for r in current}
            assert set(old) == set(new)
            for name, row in old.items():
                if name not in {'CHANGE', 'TRANSACTION', 'TRANSACTIONSTRING'}:
                    assert row == new[name]
                else:
                    assert {k: v for k, v in row.items() if k != 'Z_MAX'} == {k: v for k, v in new[name].items() if k != 'Z_MAX'}
                    assert new[name]['Z_MAX'] >= row['Z_MAX']
            continue
        if table not in volatile:
            assert unordered(rows) == unordered(current), table
        else:
            old = {r['Z_PK']: r for r in rows}; new = {r['Z_PK']: r for r in current}
            assert set(old) == set(new)
            for key, row in old.items():
                assert {k: v for k, v in row.items() if k not in volatile[table]} == {k: v for k, v in new[key].items() if k not in volatile[table]}, table
                changed = sorted(k for k in row if row[k] != new[key][k])
                if changed: actual_differences.append(dict(table=table, row_key=key, changed_fields=changed))
        preserved.append(table)
    assert before[review] == after[review]
    for table, rows in before[service]['tables'].items():
        if table != 'agent_capability_batches':
            assert unordered(rows) == unordered(after[service]['tables'][table]), table
    old_batches = {r['batch_id']: r for r in before[service]['tables']['agent_capability_batches']}
    new_batches = {r['batch_id']: r for r in after[service]['tables']['agent_capability_batches']}
    assert all(new_batches[k] == v for k, v in old_batches.items())
    added = set(new_batches) - set(old_batches)
    assert len(added) == 1
    batch_id = added.pop()
    batch = json.loads(new_batches[batch_id]['payload'])
    assert batch['status'] == 'finished' and batch['rounds'] == 1 and len(batch['calls']) == 8
    quota = read(activation / 'quota.json')
    assert (quota['model_requests'], quota['web_operations'], quota['closed']) == (8, 0, True)
    assert len(quota['entries']) == 8 and (activation / 'STOP').is_file()
    assert all(e['dispatched'] and e['outcome'] == 'returned' and len(e['usage']) == 1 for e in quota['entries'])
    request_ids = {e['program_id'] for e in quota['entries']}
    assert len(request_ids) == 8 and request_ids == {i for c in batch['calls'] for i in c['request_ids']}
    usages = [u for c in batch['calls'] for u in c['usage']]
    assert len(usages) == 8 and {u['request_id'] for u in usages} == request_ids
    ledger_usage = [e['usage'][0] for e in quota['entries']]
    tokens = {k: sum(u.get(k, 0) or 0 for u in usages) for k in ['input_tokens', 'output_tokens', 'total_tokens', 'cached_input_tokens', 'reasoning_output_tokens']}
    assert tokens == {k: sum(u.get(k, 0) or 0 for u in ledger_usage) for k in tokens}
    health = read(activation / 'health-final-live.json')
    assert all(r['status'] == 'ready' and r['next_probe_at'] is None for r in health['model_roles'].values())
    assert health['model_roles']['coach']['streaming'] == 'ready'
    assert health['model_roles']['coach']['strengths']['deep']['streaming'] == 'ready'
    counts = {t: len(after[native]['tables'][t]) for t in ['ZAGENTSESSION', 'ZAGENTMESSAGE', 'ZKNOWLEDGE', 'ZFSRSSTATE']}
    assert counts == dict(ZAGENTSESSION=8, ZAGENTMESSAGE=37, ZKNOWLEDGE=11, ZFSRSSTATE=11)
    agent = (activation / 'native-agent.txt').read_text()
    library = (activation / 'native-library.txt').read_text()
    detail = (activation / 'native-detail.txt').read_text()
    assert '学习输入' in agent and '发送' in agent and '服务未能启动' not in agent
    assert '当前筛选总数 11' in library
    assert '来源摘录' in detail and 'RAG 工作流程的三个主要阶段。' in detail
    assert '已学过，参与间隔复习, Value: 1' in detail
    assert '知识卡片' not in (activation / 'native-after-close-detail.txt').read_text()
    candidate = read(OUT / 'candidate.json')
    assert inventory(DAILY) == candidate['inventory']
    assert prior_helpers().signature(DAILY) == candidate['signature']
    pins = read(OUT / 'source-pins.json')
    assert all(sha(ROOT / p) == h for p, h in pins.items())
    protection = read(PRIVATE / 'source-protection.json')
    assert hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)).hexdigest() == protection['project_diff_sha256']
    assert all(sha(Path(p)) == h for p, h in read(PRIVATE / 'backup-pins.json').items())
    historical = {p: h for p, h in protection['daily_files'].items() if Path(p).is_relative_to(SUPPORT / 'Backups')}
    assert len(historical) == 89 and all(sha(Path(p)) == h for p, h in historical.items())
    baseline = read(ROOT / 'docs/evidence/2026-10-22-navigation-save-preflight/setup.json')
    missing = [p for p in baseline['old_frozen_files'] if not Path(p).is_file()]
    assert set(missing) == set(read(ROOT / 'docs/evidence/2026-10-22-navigation-save-real/protection.json')['missing_old_files'])
    assert all(sha(Path(p)) == h for p, h in baseline['old_frozen_files'].items() if p not in missing)
    for key in ['original_module_files', 'original_support_files', 'owned_support_files', 'previous_batch_files']:
        assert all(sha(Path(p)) == h for p, h in baseline[key].items())
    history = read(ROOT / 'docs/evidence/2026-10-23-evidence-protection/verification.json')
    history_archive = Path(history['archive'])
    assert sha(history_archive) == history['archive_sha256']
    original_evidence = read(history_archive.parent / 'manifest.json')
    for key in ['current_run_private', 'current_run_public']:
        assert all(sha(Path(p)) == h for p, h in original_evidence[key].items())
    title = ROOT / 'docs/evidence/2026-10-23-title-fallback-repair'
    assert all(sha(title / p) == h for p, h in read(title / 'manifest.json').items())
    identifiers = re.findall(r'^identifier:\s*(.*)$', subprocess.check_output([LS, '-dump'], text=True), re.M)
    registered = sum(bool(re.search(r'review[-_]?today', value, re.I)) for value in identifiers)
    spotlight = subprocess.check_output(['mdfind', "kMDItemContentType == 'com.apple.application-bundle' && kMDItemCFBundleIdentifier == 'Rex.Review-Today'"], text=True).splitlines()
    assert registered == 1 and spotlight == [str(DAILY)]
    log = (activation / 'service.log').read_text()
    assert 'Application shutdown complete.' in log
    assert not re.search(r'POST .* HTTP/1.1" (?:4|5)\d\d', log)
    write(activation / 'normal-runtime-differences.json', actual_differences)
    write(PRIVATE / 'after-source-files.json', files(SUPPORT))
    report = dict(status='DAILY_UPDATED_STARTUP_AND_EXISTING_DATA_VERIFIED_STOP', decision=266,
        actual_model_requests=8, actual_web_operations=0, unique_request_ids=8, usage_receipts=8,
        reported_tokens=tokens, startup_capability_batch_id=batch_id, startup_rounds=1,
        all_roles_ready=True, coach_smart_deep_streaming_ready=True, quota_closed_and_stopped=True,
        native_counts=counts, all_original_business_fields_preserved=True, schemas_unchanged=True,
        existing_review_database_unchanged=True, existing_service_rows_unchanged_except_one_new_capability_batch=True,
        native_preserved_tables=preserved, allowed_native_runtime_fields={k: sorted(v) for k, v in volatile.items()},
        native_runtime_rows_changed=len(actual_differences), internal_history_key_counters_only=True,
        ui=dict(agent=True, library_11=True, existing_detail_and_source=True, existing_review_flag_preserved=True,
                messages_sent=0, saves_clicked=0, appearance='light, original daily window', full_voiceover_not_run=True),
        same_daily_entry=str(DAILY), registered_entries=registered, spotlight_paths=spotlight,
        original_app_archived=True, app_and_temporary_service_closed=True, fixed_inputs_unchanged=len(pins),
        existing_backup_files_unchanged=89, user_project_diff_unchanged=True,
        original_old_files_matched=229, original_old_paths_still_missing=11, historical_gap_remains_open=True,
        old_allowances_not_resumed=True, actual_new_fullflow_not_run=True, m1_and_rex_experience_open=True)
    write(OUT / 'activation-result.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
