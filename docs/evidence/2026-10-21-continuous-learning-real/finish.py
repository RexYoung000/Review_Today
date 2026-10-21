"""Verify the stopped real batch and fresh native disk evidence without new calls."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
def read(path): return json.loads(Path(path).read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(path): return {str(p.relative_to(path)): digest(p) for p in Path(path).rglob('*') if p.is_file()}
def write(path, data): Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def main():
    setup = read(OUT / 'setup.json')
    directory, support = Path(setup['directory']), Path(setup['support_dir'])
    assert (directory / 'STOP').exists()
    assert not subprocess.run(['pgrep', '-fl', str(directory / 'ContinuousResumeQA.app/Contents/MacOS/')], capture_output=True, text=True).stdout.strip()
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
    native, data = read(OUT / 'native-disk-read.json'), read(OUT / 'complete-answer-final.json')
    quota = read(directory / 'quota.json')
    entries = quota['entries']
    rows = [json.loads(line) for line in (directory / 'live-events.jsonl').read_text().splitlines()]
    assert quota['model_requests'] == 15 and quota['web_operations'] == 0
    assert len(entries) == 15 and all(e['dispatched'] and len(e['usage']) == 1 and e['outcome'] == 'returned' for e in entries)
    ids = {e['program_id'] for e in entries}
    assert len(ids) == 15 and all(e['program_id'] == e['usage'][0]['request_id'] for e in entries)
    assert len([r for r in rows if r['type'] == 'sdk_wire_request']) == 15
    responses = [r for r in rows if r['type'] == 'sdk_wire_response']
    assert len(responses) == 15 and all(r['status'] == 200 for r in responses)
    assert not any(r['type'] in ('web_entry', 'semantic_error') for r in rows)
    fresh = [b for b in read(OUT / 'capability-ledger.json') if any(set(c['request_ids']) & ids for c in b['calls'])]
    assert len(fresh) == 1 and fresh[0]['rounds'] == 1 and fresh[0]['status'] == 'finished'
    probe_ids = {i for c in fresh[0]['calls'] for i in c['request_ids']}
    assert len(probe_ids) == 8
    assert len(data['runs']) == len(native['runs']) == 3
    assert all(r['status'] == 'completed' for r in data['runs'].values())
    calls = [call for run in data['runs'].values() for call in run['model_calls']]
    run_ids = {i for c in calls for i in c['request_ids']}
    assert len(run_ids) == 7 and run_ids | probe_ids == ids and not run_ids & probe_ids
    assert [sum(c['transport_requests'] for c in r['model_calls']) for r in data['runs'].values()] == [3, 2, 2]
    assert all(c['usage_state'] == 'reported' for c in calls)
    assert len(data['messages']) == len(native['messages']) == 6
    assert len(data['tasks']) == 1 and len(native['sessions']) == 1
    assert native['knowledge_count'] == native['source_count'] == native['fsrs_count'] == 0
    messages = {m['id']: m for m in native['messages']}
    assert sum(m['role'] == 'user' for m in native['messages']) == 3
    assert {r['id']: r['status'] for r in native['runs']} == {rid: r['status'] for rid, r in data['runs'].items()}
    for message in data['messages']:
        actual = messages[message['message_id']]
        assert actual['text'] == message['content'] and actual['run_id'] == message['run_id']
    partial = read(OUT / 'partial-complete.json')
    assert partial['capture_offers'] == {} and partial['tasks'][partial['active_task_id']]['context']['understanding'] == 'unknown'
    evaluations = [r['output'] for r in rows if r['type'] == 'semantic_output' and r['schema'] == 'MasteryEvaluation']
    assert len(evaluations) == 2 and evaluations[0]['passed'] is False and evaluations[1]['passed'] is True
    assert evaluations[1]['capture_preview'] is None
    offer = next(iter(data['capture_offers'].values()))
    assert offer['status'] == 'offered' and offer['version'] == 1 and offer['knowledge_ids'] == []
    assert not offer.get('preview_points') and not offer.get('preview_summary')
    assert read(OUT / 'preview-diagnosis.json')['original_null_passes_request_validation']
    native_events = [json.loads(line) for line in (directory / 'native-recheck-events.jsonl').read_text().splitlines()]
    assert not any(row['phase'] == 'durable_receipt' for row in native_events)
    assert all(row['knowledge_count'] == 0 for row in native_events)
    for name, expected in setup['protected_runtime_files'].items(): assert files(Path(name)) == expected
    assert files(Path(setup['prior_app'])) == setup['prior_app_files']
    assert all(digest(ROOT / name) == value for name, value in setup['protected_fingerprints'].items())
    assert hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)).hexdigest() == setup['project_diff_sha256']
    totals = {k: sum(e['usage'][0].get(k, 0) or 0 for e in entries) for k in ('input_tokens', 'output_tokens', 'total_tokens')}
    assert totals['total_tokens'] == totals['input_tokens'] + totals['output_tokens']
    for name in ('authorization.json', 'quota.json', 'STOP', 'live-events.jsonl', 'native-recheck-events.jsonl'):
        shutil.copy2(directory / name, OUT / name)
    gates = read(OUT / 'gates.json')
    gates['complete_answer'] = dict(outcome='FAIL_STRUCTURED_PREVIEW_MISSING',
        correctness_feedback='PASS', parsed_evaluation_passed=True, capture_invitation_shown=True,
        preview_points=0, preview_summary=None, visible_fallback_scope_summary=True,
        no_persisted_card=True, cumulative_model_requests=15)
    gates['remaining'] = dict(outcome='NOT_RUN_AFTER_FAILURE',
        stages=['same_topic_update', 'independent_question', 'return_to_rag', 'native_save', 'details_and_status', 'progress_and_disk_as_full_flow'])
    write(OUT / 'gates.json', gates)
    result = dict(outcome='STOPPED_ON_INITIAL_STRUCTURED_PREVIEW_FAILURE', decision=252,
        actual_model_requests=15, model_limit=40, unused_model_allowance_frozen=25,
        actual_provider_web_operations=0, web_limit=16, startup_requests=8, startup_rounds=1,
        learning_run_requests=[3, 2, 2], sdk_wire_requests=15, usage_reported=15, unknown_usage=0,
        reported_tokens=totals, actual_provider_bill_verified=False, format_repairs=0,
        empty_start=True, old_probe_state_reused=False, model_outputs_substituted=False,
        new_lesson_gate='PASS', incomplete_answer_gate='PASS', complete_answer_feedback='PASS',
        structured_preview_gate='FAIL_ZERO_POINTS_NO_SUMMARY', native_card_count=0,
        native_source_count=0, native_fsrs_count=0, native_messages=6, native_runs=3,
        matching_service_messages_and_runs=True, same_topic_through_save_and_status_not_run=True,
        fresh_process_native_read=True, no_save_clicked=True, new_save_receipts=0,
        protected_source_configuration_files=len(setup['protected_fingerprints']),
        protected_old_runtime_files=sum(len(v) for v in setup['protected_runtime_files'].values()),
        original_qa_app_unchanged=True, user_project_diff_preserved=True,
        native_app_and_service_closed=True, daily_app_updated=False, production_modified=False,
        full_uninterrupted_acceptance=False, user_experience_accepted=False,
        raw_provider_preview_recorded=False,
        next_step='Align only missing structured-preview validation/repair for new passed-answer invitations; zero-new-request controlled reproduction first. No live allowance is resumed by this result.')
    write(OUT / 'result.json', result)
    setup.update(status='STOPPED_PREVIEW_GATE_FAILURE', actual_new_model_requests=15, actual_new_web_operations=0,
        native_app_launched=True, service_started=True, native_app_closed=True, service_closed=True)
    write(OUT / 'setup.json', setup)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
