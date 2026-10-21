"""Offline checks for decision 255 after STOP and graceful native shutdown.

Reads only retained runtime state; never resumes the app, provider, or workflow.
The fresh SwiftData reader writes its own evidence JSON, not product records.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def files(path):
    return {str(p.relative_to(path)): digest(p) for p in Path(path).rglob('*') if p.is_file()}


def main():
    setup = read(OUT / 'setup.json')
    directory, support = Path(setup['directory']), Path(setup['support_dir'])
    assert (directory / 'STOP').exists()
    assert not subprocess.run(['pgrep', '-fl', str(directory / 'ContinuousResumeQA.app/Contents/MacOS/')],
        capture_output=True, text=True).stdout.strip()
    listener = subprocess.run(['lsof', '-nP', f'-iTCP:{setup["port"]}', '-sTCP:LISTEN'], capture_output=True, text=True)
    assert listener.returncode == 1 and not listener.stdout.strip()
    reader_source = ROOT / 'docs/evidence/2026-10-16-status-native-input/NativeDiskRead.swift'
    reader = directory / 'final-native-reader'
    flags = ['xcrun', 'swiftc', '-parse-as-library', '-D', 'DEBUG', '-swift-version', '5',
        '-default-isolation', 'MainActor', '-enable-upcoming-feature', 'MemberImportVisibility',
        '-I', str(support), '-L', str(support), '-lReviewTodayContractSupport', '-lFSRS',
        '-Xlinker', '-rpath', '-Xlinker', str(support)]
    with (OUT / 'native-disk-read-build.log').open('w') as log:
        subprocess.run(flags + [str(reader_source), '-o', str(reader)], stdout=log, stderr=subprocess.STDOUT, check=True)
    with (OUT / 'native-disk-read.log').open('w') as log:
        subprocess.run([str(reader), str(directory)], stdout=log, stderr=subprocess.STDOUT, check=True)
    shutil.copy2(directory / 'native-disk-read.json', OUT / 'native-disk-read.json')

    native, data = read(OUT / 'native-disk-read.json'), read(OUT / 'after-status-query.json')
    start, pre_save, saved = [read(OUT / n) for n in ('before-start.json', 'after-return-rag.json', 'save-check.json')]
    quota = read(directory / 'quota.json')
    rows = [json.loads(line) for line in (directory / 'live-events.jsonl').read_text().splitlines()]
    entries = [e for e in quota['entries'] if e['kind'] == 'model']
    assert quota['model_requests'] == len(entries) == 25 and quota['web_operations'] == 4
    assert all(e['dispatched'] and len(e['usage']) == 1 and e['outcome'] == 'returned' for e in entries)
    ids = {e['program_id'] for e in entries}
    assert len(ids) == 25 and all(e['program_id'] == e['usage'][0]['request_id'] for e in entries)
    assert len([r for r in rows if r['type'] == 'sdk_wire_request']) == 25
    responses = [r for r in rows if r['type'] == 'sdk_wire_response']
    assert len(responses) == 25 and all(r['status'] == 200 for r in responses)
    assert not any(r['type'] == 'semantic_error' for r in rows)
    web = [r for r in rows if r['type'] == 'web_entry']
    assert [(w['provider'], w['operation']) for w in web] == [('deepseek', 'search')] + [('exa', 'read')] * 3
    assert len([r for r in rows if r['type'] == 'web_return']) == 4
    fresh = [b for b in read(OUT / 'capability-ledger.json') if any(set(c['request_ids']) & ids for c in b['calls'])]
    assert len(fresh) == 1 and fresh[0]['rounds'] == 1 and fresh[0]['status'] == 'finished'
    probe_ids = {i for c in fresh[0]['calls'] for i in c['request_ids']}
    assert len(probe_ids) == 8
    new_runs = [run for rid, run in data['runs'].items() if rid not in start['runs']]
    calls = [c for run in new_runs for c in run['model_calls']]
    run_ids = {i for c in calls for i in c['request_ids']}
    assert len(new_runs) == 5 and len(run_ids) == 17
    assert [sum(c['transport_requests'] for c in r['model_calls']) for r in new_runs] == [3, 3, 3, 7, 1]
    assert run_ids | probe_ids == ids and not run_ids & probe_ids
    assert all(c['usage_state'] == 'reported' for c in calls)

    offer = next(iter(data['capture_offers'].values()))
    assert offer['version'] == 3 and offer['status'] == 'saved' and len(offer['knowledge_ids']) == 4
    assert data['capture_offers'] == saved['capture_offers'] and data['tasks'] == saved['tasks']
    origin = offer['origin_task_id']
    assert data['tasks'][origin]['context']['learning_plan'] == start['tasks'][origin]['context']['learning_plan']
    selection = new_runs[-1]['intent']['knowledge_save_operation']
    assert selection['version'] == 3 and selection['task_id'] != origin
    assert '4 张知识卡' in data['messages'][-1]['content']

    extracts = [r for r in rows if r['type'] == 'semantic_start' and r['schema'] == 'ExtractPayload']
    assert len(extracts) == 2
    marker = '检查不符合项（待修正数据，只修正这些问题并保留原文依据）：\n'
    assert marker in extracts[1]['input']
    issues = json.loads(extracts[1]['input'].split(marker, 1)[1])
    assert len(issues) == 2 and all('必须是原文的非空连续子串' in issue for issue in issues)
    verdict = [r['output'] for r in rows if r['type'] == 'semantic_output' and r['schema'] == 'VerifyVerdict']
    assert len(verdict) == 1 and verdict[0]['verdict'] == 'confirmed'
    write(OUT / 'repair-and-verification.json', dict(actual_automatic_payload_repairs=1,
        concrete_issues=issues, original_outputs_retained=True,
        replacement_output_from_real_model=True, public_verdict=verdict[0]))

    assert len(data['messages']) == len(native['messages']) == 15
    assert len(data['runs']) == len(native['runs']) == 8
    assert all(r['status'] == 'completed' for r in data['runs'].values())
    assert native['knowledge_count'] == native['fsrs_count'] == 4 and native['source_count'] == 1
    assert len(native['sessions']) == 1 and len(data['tasks']) == 2
    messages = {m['id']: m for m in native['messages']}
    for message in data['messages']:
        actual = messages[message['message_id']]
        assert actual['text'] == message['content'] and actual['run_id'] == message['run_id']
    assert {r['id']: r['status'] for r in native['runs']} == {rid: r['status'] for rid, r in data['runs'].items()}
    assert {c['id'] for c in native['cards']} == set(offer['knowledge_ids'])
    assert all(not c['review'] and c['questions'] and c['origin_session'] == setup['session_id']
        and c['origin_task'] == selection['task_id'] and 'Python' not in c['title'] + c['explanation']
        for c in native['cards'])
    assert all(c['title'] in data['messages'][-1]['content'] for c in native['cards'])
    for index, title in enumerate(('检索相似度', '生成不忠实', '核对来源与适用条件', '适用边界丢失'), 1):
        detail = (OUT / f'detail-{index}.txt').read_text()
        assert title in detail and '仅保存资料 · 未参与复习' in detail and '来源证据' in detail
    progress = (OUT / 'native-progress.txt').read_text()
    assert progress.count('待学习, Help:') == 3 and '区分检索相似度与答案正确性, 已讲解' in progress
    with sqlite3.connect(f'file:{directory}/app.store?mode=ro', uri=True) as db:
        native_offers = json.loads(db.execute('select ZCAPTUREOFFERSJSON from ZAGENTSESSION').fetchone()[0])
    actual_offer = next(o for o in native_offers if o['id'].lower() == offer['id'])
    assert actual_offer['version'] == 3 and actual_offer['status'] == 'saved'
    assert actual_offer['preview_points'] == offer['preview_points'] and actual_offer['preview_summary'] == offer['preview_summary']
    assert {i.lower() for i in actual_offer['knowledge_ids']} == set(offer['knowledge_ids'])
    write(OUT / 'native-durable-offers.json', native_offers)
    journal = [json.loads(line) for line in (directory / 'native-recheck-events.jsonl').read_text().splitlines()]
    receipts = [row for row in journal if row['phase'] == 'durable_receipt']
    assert len(receipts) == 1 and receipts[0]['receipt_already_durable'] is True
    receipt = receipts[0]
    assert {i.lower() for i in receipt['receipt_card_ids']} == set(offer['knowledge_ids'])
    assert {c['id'].lower(): c['explanation'] for c in receipt['knowledge']} == {c['id']: c['explanation'] for c in native['cards']}
    raw_text = receipt['sources'][0]['raw_text']
    assert 'Python' not in raw_text and all(c['evidence'] in raw_text for c in native['cards'])
    assert all(f['text'] in raw_text for f in pre_save['capture_offers'][offer['id']]['fragments'])

    for name, expected in setup['protected_runtime_files'].items():
        assert files(Path(name)) == expected
    assert files(Path(setup['prior_app'])) == setup['prior_app_files']
    assert all(digest(ROOT / name) == value for name, value in setup['protected_fingerprints'].items())
    assert hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)).hexdigest() == setup['project_diff_sha256']
    totals = {k: sum(e['usage'][0].get(k, 0) or 0 for e in entries) for k in ('input_tokens', 'output_tokens', 'total_tokens')}
    assert totals['total_tokens'] == totals['input_tokens'] + totals['output_tokens']
    for name in ('quota.json', 'STOP', 'live-events.jsonl', 'native-recheck-events.jsonl'):
        shutil.copy2(directory / name, OUT / name)
    gates = read(OUT / 'gates.json')
    gates['disk_readback'] = dict(outcome='PASS', fresh_native_process=True, native_messages=15,
        native_runs=8, knowledge=4, sources=1, fsrs=4, native_offer_matches_service=True,
        native_and_service_messages_match=True, app_and_service_closed=True)
    write(OUT / 'gates.json', gates)
    result = dict(outcome='PASS_POST_PREVIEW_SCOPE_STOP', decision=255,
        actual_model_requests=25, model_limit=32, unused_model_allowance_frozen=7,
        actual_provider_web_operations=4, web_limit=16, unused_web_allowance_frozen=12,
        startup_requests=8, startup_rounds=1, new_run_requests=[3, 3, 3, 7, 1],
        sdk_wire_requests=25, usage_reported=25, unknown_usage=0, reported_tokens=totals,
        actual_provider_bill_verified=False, automatic_payload_repairs=1, format_repairs=0,
        missing_preview_repair_triggered=False, copied_real_history=True, empty_start=False,
        old_probe_state_reused=False, model_outputs_substituted=False,
        all_scope_gates_pass=True, native_offer_version=3, native_card_count=4,
        native_source_count=1, native_fsrs_count=4, native_messages=15, native_runs=8,
        card_titles=[c['title'] for c in native['cards']], matching_service_messages_and_runs=True,
        new_save_receipts=1, all_actual_details_opened=True, actual_query_selection_matched=True,
        review_disabled=True, original_learning_plan_unchanged=True, fresh_process_native_read=True,
        protected_source_configuration_files=len(setup['protected_fingerprints']),
        protected_old_runtime_files=sum(len(v) for v in setup['protected_runtime_files'].values()),
        original_qa_app_unchanged=True, user_project_diff_preserved=True,
        native_app_and_service_closed=True, daily_app_updated=False, production_modified=False,
        full_uninterrupted_acceptance=False, user_experience_accepted=False,
        next_step='Post-preview scope passed. Keep all STOPs and frozen remainders. Separate future scope: daily activation/user experience or one fresh-empty uninterrupted full chain; neither authorized by this completion.')
    write(OUT / 'result.json', result)
    setup.update(status='COMPLETED_POST_PREVIEW_PASS_STOP', actual_new_model_requests=25,
        actual_new_web_operations=4, native_app_launched=True, service_started=True,
        native_app_closed=True, service_closed=True)
    write(OUT / 'setup.json', setup)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
