"""Explicit opt-in, bounded full-conversation comparison; never uses daily data."""
import argparse
from collections import Counter
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
from unittest.mock import patch
import uuid


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


class Admission:
    """Reserve before transport; failures and normal repairs retain their slots."""
    def __init__(self, spec, report, save):
        self.spec, self.report, self.save = spec, report, save
        self.lock = threading.RLock()

    def model(self, step, job, model, schema):
        with self.lock:
            requests = self.report['model_requests']
            if (step.get('requests', 0) >= self.spec['max_requests_per_model_step']
                    or sum(r['job'] == job for r in requests) >= self.spec['max_model_requests_per_job']
                    or len(requests) >= self.spec['max_model_requests']):
                raise RuntimeError('RT.EVALUATION.MODEL_ADMISSION_STOPPED')
            step['requests'] = step.get('requests', 0) + 1
            record = dict(id=str(uuid.uuid4()), job=job, node=step['node'], step_id=step['id'],
                          attempt=step['requests'], model=model, schema=schema, started_at=now())
            requests.append(record)
            self.save()
            return record

    def web(self, job, provider, operation, value):
        with self.lock:
            requests = self.report['web_requests']
            if (len(requests) >= self.spec['max_web_requests']
                    or sum(r['job'] == job for r in requests) >= self.spec['max_tool_requests_per_job']):
                raise RuntimeError('RT.EVALUATION.WEB_ADMISSION_STOPPED')
            record = dict(id=str(uuid.uuid4()), job=job, provider=provider, operation=operation,
                          value=value, status='started', started_at=now())
            requests.append(record)
            self.save()
            return record


def production_hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / 'agent-service/agent_service').rglob('*.py'))}


def mask_labels(value):
    """Remove infrastructure metadata, retaining public sources and actual prose."""
    if isinstance(value, dict):
        return {k: mask_labels(v) for k, v in value.items()
                if k not in {'provider', 'providers', 'model', 'runtime_models', 'configuration',
                             'provider_events', 'usage', 'elapsed_seconds', 'source_selection'}}
    if isinstance(value, list):
        return [mask_labels(v) for v in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.manifest.read_text())
    assert (spec['frozen_before_execution'] and len(spec['cases']) == 8 and spec['jobs'] == 16
            and spec['repeats'] == 1 and spec['max_model_requests'] == 192
            and spec['max_web_requests'] == 160 and spec['max_model_requests_per_job'] == 12
            and spec['max_requests_per_model_step'] == 2 and spec['max_tool_requests_per_job'] == 10)
    if args.directory.exists():
        parser.error('retain prior evidence; existing directories cannot be resumed or overwritten')
    directory = args.directory.resolve()
    directory.mkdir(parents=True, mode=0o700)
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory / 'import.sqlite3'),
                      REVIEW_TODAY_JEV_TEST='0', REVIEW_TODAY_CONTEXT_PROVIDER='none',
                      REVIEW_TODAY_BROWSER_FALLBACK='1' if spec['browser'] else '0')

    def sqlite_fence(event, values):
        if event == 'sqlite3.connect' and not Path(values[0]).resolve().is_relative_to(directory):
            raise RuntimeError('RT.EVALUATION.DATABASE_OUTSIDE_ISOLATED_DIRECTORY')
    sys.addaudithook(sqlite_fence)

    # All service imports follow the database fence. No app or startup hooks.
    from agent_service import config, conversation, web_tools as web, model_capabilities
    from agent_service.conversation_store import ConversationStore
    from agent_service.harness_store import HarnessStore
    from agent_service.schemas import SessionMessageRequest
    from agent_service.certs import ssl_context
    import httpx

    if config.PROVIDER != 'deepseek' or not config.openai_key() or not os.getenv('DEEPSEEK_WEB_API_KEY', '').strip():
        parser.error('existing production role and independent web credentials are required')
    root = Path(__file__).resolve().parents[2]
    frozen_hashes = production_hashes(root)
    report = dict(started_at=now(), manifest_sha256=digest(args.manifest.read_text()),
                  code_hashes=frozen_hashes, startup_probes=0,
                  models=dict(router=config.ROUTER_MODEL, coach=config.COACH_MODEL, evidence=config.RISK_MODEL),
                  model_requests=[], web_requests=[], jobs=[], guards=[], balance_reads=[])
    captures = dict(steps=[], web=[])
    balance = dict()
    lock = threading.RLock()

    def write(filename, value):
        path = directory / filename
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(path)

    def save():
        with lock:
            write('results.json', report)
            write('captures.json', captures)

    def balances(label):
        # Read-only official endpoint; never print or publish absolute balances.
        balance[label] = []
        for namespace, key in [('model', config.openai_key()), ('web', os.getenv('DEEPSEEK_WEB_API_KEY', '').strip())]:
            entry = dict(namespace=namespace, captured_at=now())
            try:
                with httpx.Client(verify=ssl_context(), follow_redirects=False, timeout=10) as client:
                    response = client.get('https://api.deepseek.com/user/balance',
                                          headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
                    response.raise_for_status()
                    entry.update(status='ok', result=response.json())
            except Exception as error:
                entry.update(status='unavailable', error=type(error).__name__)
            balance[label].append(entry)
            report['balance_reads'].append(dict(label=label, namespace=namespace, status=entry['status']))
            write('balances-private.json', balance)
            save()

    admission = Admission(spec, report, save)
    step_scope = ContextVar('web_ab_step')
    job_scope = ContextVar('web_ab_job')
    real_parse, real_backend = conversation.parse_model, web._backend

    def observed_parse(system, prompt, schema, **kwargs):
        step, job = step_scope.get(), job_scope.get()
        original_request, original_usage = kwargs.get('on_request'), kwargs.get('on_usage')
        current_request = {}

        def request():
            record = admission.model(step, job['id'], kwargs.get('model'), schema.__name__)
            current_request['record'] = record
            # Preserve the Harness identity so durable usage attribution stays real.
            identity = original_request() if original_request else record['id']
            record['harness_request_id'] = identity
            save()
            return identity

        def usage(value):
            record = current_request.get('record')
            if record is not None:
                record.setdefault('usage', []).append(value)
            if original_usage:
                original_usage(value)
            save()

        kwargs.update(on_request=request, on_usage=usage)
        try:
            result = real_parse(system, prompt, schema, **kwargs)
            if current_request:
                current_request['record']['status'] = 'returned'
            return result
        except Exception as error:
            if current_request:
                current_request['record'].update(status='failed', error=getattr(error, 'code', type(error).__name__))
            raise
        finally:
            save()

    class ObservedBackend:
        def __init__(self, provider):
            self.inner, self.name = real_backend(provider), provider

        def invoke(self, operation, value, **kwargs):
            record = admission.web(job_scope.get()['id'], self.name, operation, value)
            started = time.monotonic()
            try:
                result = getattr(self.inner, operation)(value, **kwargs)
                record['status'] = 'ok'
                if operation == 'read':
                    record.update(body_sha256=digest(result[1]), body_chars=len(result[1]),
                                  details=getattr(result, 'details', {}))
                    capture = dict(title=result[0], content=result[1])
                else:
                    record['result_count'] = len(result)
                    capture = [vars(item) for item in result]
                captures['web'].append(dict(request_id=record['id'], job=record['job'], provider=self.name,
                                           operation=operation, value=value, result=capture))
                return result
            except Exception as error:
                record.update(status='failed', error_code=getattr(error, 'code', type(error).__name__))
                raise
            finally:
                record['elapsed_seconds'] = round(time.monotonic() - started, 3)
                save()

        def search(self, query, **kwargs):
            return self.invoke('search', query, **kwargs)

        def read(self, url, **kwargs):
            return self.invoke('read', url, **kwargs)

    def blocked(name):
        def stop(*args, **kwargs):
            report['guards'].append(dict(kind=name, job=job_scope.get(None), at=now()))
            save()
            raise RuntimeError('RT.EVALUATION.OUT_OF_SCOPE_' + name.upper())
        return stop

    class ComparisonHarness(conversation.ConversationHarness):
        def _call(self, sid, rid, rev, node, system, prompt, schema, model=config.COACH_MODEL, **kwargs):
            if node not in {'intent', 'teaching_preparation', 'source_candidates', 'evidence_assessment', 'answer'}:
                return blocked('model_node_' + node)()
            step = dict(id=str(uuid.uuid4()), job=job_scope.get()['id'], node=node,
                        model=model, system=system, prompt=prompt, requests=0)
            token = step_scope.set(step)
            captures['steps'].append(step)
            try:
                result = super()._call(sid, rid, rev, node, system, prompt, schema, model, **kwargs)
                step['output'] = result.model_dump()
                return result
            finally:
                step_scope.reset(token)
                save()

        def _schedule_summary(self, sid):
            # Empty one-turn sessions do not need maintenance; no extra model call.
            report.setdefault('summary_schedules_suppressed', 0)
            report['summary_schedules_suppressed'] += 1

    save()
    balances('before')
    jobs = [(case, name) for index, case in enumerate(spec['cases'])
            for name in (['exa_first', 'deepseek_first'] if index % 2 == 0 else ['deepseek_first', 'exa_first'])]
    with patch.object(conversation, 'parse_model', side_effect=observed_parse), \
            patch.object(web, '_backend', side_effect=ObservedBackend), \
            patch.object(conversation, 'run_capture', side_effect=blocked('capture')), \
            patch.object(model_capabilities, 'start_probe', side_effect=blocked('probe')), \
            patch.object(model_capabilities, 'probe', side_effect=blocked('probe')):
        for case, name in jobs:
            if production_hashes(root) != frozen_hashes or digest(args.manifest.read_text()) != report['manifest_sha256']:
                raise RuntimeError('RT.EVALUATION.FROZEN_INPUT_CHANGED')
            job = dict(id=case['id'] + ':' + name, case=case['id'], configuration=name)
            report['jobs'].append(job)
            token = job_scope.set(job)
            started = time.monotonic()
            order = spec['orders'][name]
            with patch.dict(os.environ, dict(REVIEW_TODAY_SEARCH_PROVIDER=order[0],
                    REVIEW_TODAY_SEARCH_FALLBACKS=','.join(order[1:]), REVIEW_TODAY_READ_PROVIDER='exa',
                    REVIEW_TODAY_READ_FALLBACKS='tavily,deepseek')):
                harness = ComparisonHarness(ConversationStore(HarnessStore(str(directory / (case['id'] + '-' + name + '.sqlite3')))))
                sid = str(uuid.uuid4())
                try:
                    accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
                        content=case['question'], thinking_strength='smart'))
                    harness.drain(sid)
                    data = harness.store.get(sid)
                    run = data['runs'][accepted.run_id]
                    job.update(status=run['status'], search_state=run.get('search_state'), error=run.get('error_code'),
                        intent=run.get('intent'), evidence=run.get('teaching_evidence'),
                        quality_supplement=run.get('quality_supplement'),
                        model_calls=run.get('model_calls', []), source_selection=run.get('source_selection_records', {}),
                        provider_events=[e['payload'] for e in data['events'] if e['stage'] == 'web_provider'],
                        failure_events=[dict(stage=e['stage'], error=e.get('error'), detail=e.get('detail'))
                                        for e in data['events'] if e.get('error')],
                        replies=[m['content'] for m in data['messages'] if m['role'] == 'coach'],
                        source_urls=[s['url'] for s in run.get('teaching_sources', [])],
                        tasks=len(data['tasks']), capture_offers=len(data.get('capture_offers', [])))
                    write(case['id'] + '-' + name + '-run.json', run)
                    if data['tasks'] or data.get('capture_offers'):
                        job['unexpected_side_effect'] = True
                except Exception as error:
                    job.update(status='comparison_failed', error=getattr(error, 'code', str(error) if str(error).startswith('RT.') else type(error).__name__))
            job['elapsed_seconds'] = round(time.monotonic() - started, 3)
            save()
            job_scope.reset(token)
            # Progress intentionally omits provider labels and answer contents.
            print(json.dumps(dict(completed=len(report['jobs']), total=16, case=case['id'],
                                  status=job['status'], elapsed_seconds=job['elapsed_seconds']), ensure_ascii=False), flush=True)
    balances('after')
    report.update(finished_at=now(), final_code_unchanged=production_hashes(root) == frozen_hashes)
    save()

    # Random identities and shuffled presentation prevent explicit supplier labels
    # from influencing review. Runtime packets stay private and independently hashed.
    shuffled = list(report['jobs'])
    secrets.SystemRandom().shuffle(shuffled)
    key, packets = {}, []
    for job in shuffled:
        blind_id = secrets.token_hex(4)
        key[blind_id] = job['id']
        case = next(c for c in spec['cases'] if c['id'] == job['case'])
        reads = [dict(url=c['value'], **c['result']) for c in captures['web']
                 if c['job'] == job['id'] and c['operation'] == 'read']
        inputs = [dict(node=s['node'], payload=mask_labels(json.loads(s['prompt']))) for s in captures['steps']
                  if s['job'] == job['id'] and s['node'] in {'evidence_assessment', 'answer'}]
        packets.append(dict(blind_id=blind_id, case=job['case'], question=case['question'], checks=case['checks'],
                            required_domains=case['required_domains'], status=job['status'],
                            error=job.get('error'), replies=job.get('replies', []),
                            reads=reads, actual_inputs=inputs))
    write('blind-key.json', key)
    write('blind-packets.json', packets)
    write('blind-packet-hash.json', dict(sha256=digest((directory / 'blind-packets.json').read_text())))
    print(json.dumps(dict(finished=True, models=len(report['model_requests']), web=len(report['web_requests']),
                          jobs=len(report['jobs']), code_unchanged=report['final_code_unchanged'])), flush=True)


if __name__ == '__main__':
    main()
