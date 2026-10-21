"""Offline zero-web guard, retained receipt projection, and HOLD bootstrap checks."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT))
from quota_zero_web import Quota, QuotaBlocked, install


def read(path): return json.loads(Path(path).read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(directory): return {str(p.relative_to(directory)): digest(p) for p in Path(directory).rglob('*') if p.is_file()}
def write(path, value): Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    setup = read(OUT / 'setup.json')
    held = Path(setup['directory']).resolve()
    temporary = Path(tempfile.mkdtemp(prefix='review-today-save-query-guard-', dir='/tmp')).resolve()
    blocked_network = []
    def audit(event, args):
        if event == 'socket.connect':
            blocked_network.append(event)
            raise AssertionError('Offline check cannot connect')
        if event == 'sqlite3.connect' and args[0] != ':memory:':
            name = unquote(urlsplit(args[0]).path) if str(args[0]).startswith('file:') else args[0]
            assert Path(name).resolve().is_relative_to(temporary) or Path(name).resolve().is_relative_to(held)
    sys.addaudithook(audit)
    cases = []
    original_files = files(held)
    for operation in (lambda: Quota(held), lambda: install(held)):
        try: operation()
        except QuotaBlocked: pass
        else: raise AssertionError('pending/HOLD must block')
        assert files(held) == original_files
    cases.append('pending_and_hold_block_before_writes')
    fixture = temporary / 'quota'
    fixture.mkdir()
    write(fixture / 'authorization.json', dict(status='approved', batch_id=str(uuid.uuid4()),
        actual_model_request_limit=12, provider_web_operation_limit=0))
    quota = Quota(fixture)
    try: quota.admit('web')
    except QuotaBlocked: pass
    else: raise AssertionError('web must be blocked before transport')
    assert not quota.ledger.exists()
    cases.append('zero_web_denied_without_consuming_model_allowance')
    for number in range(12):
        token = quota.admit('model')
        quota.bind(token, str(uuid.uuid4()))
        quota.dispatch(token)
        quota.finish(token, outcome='offline_simulated', usage=dict(total_tokens=1))
        assert read(quota.ledger)['model_requests'] == number + 1
    assert (fixture / 'STOP').is_file()
    for kind in ('model', 'web'):
        try: quota.admit(kind)
        except QuotaBlocked: pass
        else: raise AssertionError('cap must prevent further admissions')
    assert read(quota.ledger)['web_operations'] == 0
    cases.append('twelve_model_cap_stops_further_admissions')
    # The installed SDK/web hooks must reject all real web backends even when configured.
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(fixture / 'checkpoint.sqlite3'),
        REVIEW_TODAY_LLM_PROVIDER='deepseek', REVIEW_TODAY_JEV_TEST='0',
        DEEPSEEK_API_KEY='offline-fixture', OPENAI_API_KEY='offline-fixture',
        REVIEW_TODAY_SEARCH_PROVIDER='deepseek', REVIEW_TODAY_SEARCH_FALLBACKS='exa,tavily',
        REVIEW_TODAY_READ_PROVIDER='exa', REVIEW_TODAY_READ_FALLBACKS='tavily,deepseek',
        REVIEW_TODAY_CONTEXT_PROVIDER='none', REVIEW_TODAY_BROWSER_FALLBACK='0')
    sys.path.insert(0, str(ROOT / 'agent-service'))
    fresh = temporary / 'installed'
    fresh.mkdir()
    write(fresh / 'authorization.json', dict(status='approved', batch_id=str(uuid.uuid4()),
        actual_model_request_limit=12, provider_web_operation_limit=0))
    os.environ['REVIEW_TODAY_HARNESS_DB'] = str(fresh / 'checkpoint.sqlite3')
    from agent_service import web_tools
    from agent_service.call_errors import WebToolError
    backend_calls = []
    class NeverBackend:
        def __init__(self, name): self.name = name
        def search(self, *args, **kwargs): backend_calls.append(self.name); raise AssertionError('No web transport')
        read = context = search
    web_tools._backend = NeverBackend
    installed = install(fresh)
    for provider in ('deepseek', 'exa', 'tavily'):
        for operation in ('search', 'read', 'context'):
            try: getattr(web_tools._backend(provider), operation)('fixture')
            except WebToolError as error: assert error.code == 'RT.WEB.CANCELLED'
            else: raise AssertionError('zero-web installed guard did not block')
    assert backend_calls == [] and not installed.ledger.exists()
    cases.append('all_nine_provider_operation_entries_block_before_backend')
    from agent_service.knowledge_capture_status import facts, reply
    projection_dir = temporary / 'projection'
    projection_dir.mkdir()
    for item in held.glob('checkpoint.sqlite3*'):
        if item.is_file(): shutil.copy2(item, projection_dir / item.name)
    with sqlite3.connect(f'file:{projection_dir}/checkpoint.sqlite3?mode=ro', uri=True) as db:
        data = json.loads(db.execute('select payload from agent_sessions_v2 where session_id=?', (setup['session_id'],)).fetchone()[0])
        data['tasks'] = {r['task_id']: r for row in db.execute('select payload from harness_tasks')
            if (r := json.loads(row[0])).get('session_id') == setup['session_id']}
    projection = facts(data)
    assert len(projection['save_operations']) == 1
    candidate = projection['save_operations'][0]
    assert candidate['task_id'] == setup['checks']['service']['save_task'] and candidate['version'] == 4
    query = '刚才保存的 RAG 知识卡存好了吗？这次一共保存了几张，分别叫什么？只查询这次的真实保存结果，不新增或修改知识卡，也不要推进学习。'
    # This is only an expected-result assertion, never substituted for real model output.
    expected = facts(data, save_operation=dict(task_id=candidate['task_id'], version=4,
        evidence='这次一共保存了几张，分别叫什么'), current_request=query)
    assert expected['stage'] == 'saved' and len(expected['current_cards']) == 5
    assert all(card['title'] in reply(expected) for card in setup['checks']['service']['expected_cards'])
    cases.append('current_retained_state_exposes_one_bound_five_card_receipt')
    environment = dict(os.environ, REVIEW_TODAY_HARNESS_DB=str(held / 'checkpoint.sqlite3'),
        PYTHONDONTWRITEBYTECODE='1')
    code = f'import sys; sys.path.insert(0,{str(OUT)!r}); import bootstrap; bootstrap.install({str(held)!r},{str(ROOT)!r})'
    result = subprocess.run([sys.executable, '-B', '-c', code], env=environment, cwd=temporary,
        capture_output=True, text=True, timeout=20)
    assert result.returncode != 0 and 'pending/HOLD' in result.stderr
    assert files(held) == original_files
    cases.append('actual_bootstrap_refuses_pending_before_service_import')
    assert files(Path(setup['prior_directory'])) == setup['prior_runtime_files']
    assert files(Path(setup['prior_native_app'])) == setup['prior_app_files']
    assert not (held / 'quota.json').exists() and not (held / 'live-events.jsonl').exists()
    assert not blocked_network
    result = dict(outcome='PASS', cases=cases, actual_new_model_requests=0, actual_new_web_operations=0,
        simulated_model_admissions=12, rejected_provider_operations=9,
        prepared_batch_pending_and_hold=True, old_runtime_and_app_unchanged=True,
        native_bundle_built_and_signature_verified=True, app_launched=False, service_started=False,
        model_selection_verified=False, native_input_verified=False,
        caveat='Offline checks and a held native bundle cannot certify real model selection or native reply.')
    write(OUT / 'check-result.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
