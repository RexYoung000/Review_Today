"""Read the closed QA store in a fresh native process and verify the real query."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIOR = ROOT / 'docs/evidence/2026-10-21-learning-save-real'
def read(path): return json.loads(Path(path).read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(path): return {str(p.relative_to(path)): digest(p) for p in Path(path).rglob('*') if p.is_file()}
def write(path, value): Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    setup = read(OUT / 'setup.json')
    directory, support = Path(setup['directory']), Path(setup['support_dir'])
    assert (directory / 'STOP').is_file()
    assert not subprocess.run(['pgrep', '-fl', '/ContinuousResumeQA.app/Contents/MacOS/'], capture_output=True, text=True).stdout.strip()
    listener = subprocess.run(['lsof', '-nP', f'-iTCP:{setup["port"]}', '-sTCP:LISTEN'], capture_output=True, text=True)
    assert listener.returncode == 1 and not listener.stdout.strip()
    source = ROOT / 'docs/evidence/2026-10-16-status-native-input/NativeDiskRead.swift'
    reader = directory / 'native-disk-reader'
    cmd = ['xcrun', 'swiftc', '-parse-as-library', '-D', 'DEBUG', '-swift-version', '5',
        '-default-isolation', 'MainActor', '-enable-upcoming-feature', 'MemberImportVisibility',
        '-I', str(support), '-L', str(support), '-lReviewTodayContractSupport', '-lFSRS',
        '-Xlinker', '-rpath', '-Xlinker', str(support), str(source), '-o', str(reader)]
    with (OUT / 'native-disk-read-build.log').open('w') as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (OUT / 'native-disk-read.log').open('w') as log:
        subprocess.run([str(reader), str(directory)], stdout=log, stderr=subprocess.STDOUT, check=True)
    shutil.copy2(directory / 'native-disk-read.json', OUT / 'native-disk-read.json')
    before, after = read(OUT / 'before-query.json'), read(OUT / 'after-query.json')
    native, native_before = read(OUT / 'native-disk-read.json'), read(PRIOR / 'native-disk-read.json')
    quota = read(directory / 'quota.json')
    rows = [json.loads(line) for line in (directory / 'live-events.jsonl').read_text().splitlines()]
    assert quota['model_requests'] == 9 and quota['web_operations'] == 0
    entries = quota['entries']
    assert len(entries) == 9 and all(e['dispatched'] and len(e['usage']) == 1 and e['outcome'] == 'returned' for e in entries)
    identities = {e['program_id'] for e in entries}
    assert len(identities) == 9 and all(e['usage'][0]['request_id'] == e['program_id'] for e in entries)
    assert len([r for r in rows if r['type'] == 'sdk_wire_request']) == 9
    responses = [r for r in rows if r['type'] == 'sdk_wire_response']
    assert len(responses) == 9 and all(r['status'] == 200 for r in responses)
    assert not any(r['type'] in ('web_entry', 'semantic_error') for r in rows)
    batches = read(OUT / 'capability-ledger.json')
    fresh = [b for b in batches if any(set(c['request_ids']) & identities for c in b['calls'])]
    assert len(fresh) == 1 and fresh[0]['status'] == 'finished' and fresh[0]['rounds'] == 1
    probe_ids = {i for c in fresh[0]['calls'] for i in c['request_ids']}
    assert len(probe_ids) == 8
    new_runs = {rid: r for rid, r in after['runs'].items() if rid not in before['runs']}
    assert len(new_runs) == 1
    rid, run = next(iter(new_runs.items()))
    assert run['status'] == 'completed' and run['intent']['knowledge_card_status'] is True
    offer = next(iter(before['capture_offers'].values()))
    selected = run['knowledge_status_save_operation']
    assert selected['task_id'] == offer['save_task_id'] and selected['version'] == 4
    assert run['intent']['knowledge_save_operation']['task_id'] == offer['save_task_id']
    model_calls = run['model_calls']
    run_ids = {i for call in model_calls for i in call['request_ids']}
    assert len(run_ids) == 1 and run_ids | probe_ids == identities and not run_ids & probe_ids
    assert all(call['usage_state'] == 'reported' for call in model_calls)
    semantic_outputs = [r for r in rows if r['type'] == 'semantic_output' and r['schema'] == 'IntentDecision']
    assert len(semantic_outputs) == 1 and semantic_outputs[0]['output']['knowledge_save_operation']['task_id'] == offer['save_task_id']
    text = after['messages'][-1]['content']
    assert '已成功写入 5 张知识卡' in text and '保存范围不完全一致' not in text
    assert all(card['title'] in text for card in setup['checks']['service']['expected_cards'])
    for key in ('tasks', 'capture_offers', 'draft', 'pending', 'active_task_id', 'focus_goal'):
        assert after[key] == before[key], key
    assert after['messages'][:-2] == before['messages']
    assert all(after['runs'][key] == value for key, value in before['runs'].items())
    assert native['knowledge_count'] == 5 and native['source_count'] == 1 and native['fsrs_count'] == 5
    assert len(native['messages']) == 19 and len(native['runs']) == 10
    assert {c['id']: c for c in native['cards']} == {c['id']: c for c in native_before['cards']}
    messages = {m['id']: m for m in native['messages']}
    assert all(messages[m['id']] == m for m in native_before['messages'])
    assert {r['id']: r for r in native['runs'] if r['id'] != rid} == {r['id']: r for r in native_before['runs']}
    for message in after['messages']:
        actual = messages[message['message_id']]
        assert actual['text'] == message['content'] and actual['run_id'] == message['run_id']
    new_messages = [m for m in native['messages'] if m['id'] not in {x['id'] for x in native_before['messages']}]
    assert len(new_messages) == 2 and sum(m['role'] == 'user' for m in new_messages) == 1
    assert any(m['text'] == text for m in new_messages)
    assert text in (OUT / 'native-query.txt').read_text()
    assert all(c['review'] is False for c in native['cards'])
    native_events = [json.loads(line) for line in (directory / 'native-recheck-events.jsonl').read_text().splitlines()]
    assert not any(r['phase'] == 'durable_receipt' for r in native_events)
    # Compare critical tables to a copied old store; never open the original file.
    comparison = directory / 'comparison-original'
    comparison.mkdir(exist_ok=True)
    for item in Path(setup['prior_directory']).glob('app.store*'):
        if item.is_file(): shutil.copy2(item, comparison / item.name)
    compared = []
    with sqlite3.connect(comparison / 'app.store') as left, sqlite3.connect(directory / 'app.store') as right:
        for table in ('ZKNOWLEDGE', 'ZSOURCE', 'ZQUESTION', 'ZFSRSSTATE', 'ZREVIEWATTEMPT', 'ZREVIEWSESSION'):
            assert left.execute('select * from ' + table + ' order by Z_PK').fetchall() == right.execute('select * from ' + table + ' order by Z_PK').fetchall(), table
            compared.append(table)
    assert files(Path(setup['prior_directory'])) == setup['prior_runtime_files']
    assert files(Path(setup['prior_native_app'])) == setup['prior_app_files']
    assert all(digest(ROOT / name) == value for name, value in setup['protected_fingerprints'].items())
    assert hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)).hexdigest() == setup['project_diff_sha256']
    totals = {key: sum(e['usage'][0].get(key, 0) or 0 for e in entries) for key in ('input_tokens', 'output_tokens', 'total_tokens')}
    assert totals['total_tokens'] == totals['input_tokens'] + totals['output_tokens']
    for name in ('authorization.json', 'quota.json', 'STOP', 'live-events.jsonl', 'native-recheck-events.jsonl', 'NativeSaveQueryQA.swift'):
        shutil.copy2(directory / name, OUT / name)
    result = dict(outcome='PASS_REAL_NATIVE_SAVE_OPERATION_QUERY', decision=251,
        actual_model_requests=9, model_limit=12, unused_model_allowance_frozen=3,
        actual_provider_web_operations=0, web_limit=0, fresh_startup_probe_requests=8,
        fresh_startup_rounds=1, native_query_requests=1, format_repairs=0,
        unique_request_ids=9, usage_reported=9, unknown_usage=0, reported_tokens=totals,
        reply=text, save_version=4, saved_cards=5, actual_model_operation_selection=True,
        model_outputs_substituted=False, native_input_and_reply=True, new_user_inputs=1,
        service_messages=18, native_messages=19, service_runs=10, native_runs=10,
        cards_sources_questions_and_review_tables_unchanged=compared, new_save_receipts=0,
        old_history_and_failed_query_preserved=True, learning_progress_preserved=True,
        fresh_native_process_disk_read=True, old_22_of_24_stop_and_remaining_two_preserved=True,
        protected_source_and_configuration_files=len(setup['protected_fingerprints']),
        user_project_difference_preserved=True, original_qa_app_unchanged=True,
        native_app_closed=True, owned_service_closed=True, daily_app_updated=False,
        production_modified=False, uninterrupted_full_learning_flow_verified=False,
        user_experience_accepted=False, actual_provider_bill_verified=False,
        next_step='Prepare a fresh uninterrupted learning-to-save acceptance scope; daily App still has not loaded STATUS-02.')
    write(OUT / 'result.json', result)
    setup.update(status='COMPLETED_PASS_STOP', actual_new_model_requests=9, actual_new_web_operations=0,
        native_app_launched=True, service_started=True, native_app_closed=True, service_closed=True)
    write(OUT / 'setup.json', setup)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
