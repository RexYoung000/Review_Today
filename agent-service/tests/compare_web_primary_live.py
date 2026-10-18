"""Opt-in isolated production source/assessment/answer regression, with fixed routing."""
import argparse
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch
import uuid


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Admission:
    """Reserve before dispatch, including failed requests, and forbid step retries."""
    def __init__(self, report, save, *, max_models=20, max_web=40):
        self.report, self.save = report, save
        self.max_models, self.max_web = max_models, max_web
        self.lock = threading.RLock()

    def model(self, step, job, model, schema):
        with self.lock:
            if step.get('used') or len(self.report['model_requests']) >= self.max_models:
                raise RuntimeError('independent model admission stopped')
            step['used'] = True
            identity = str(uuid.uuid4())
            self.report['model_requests'].append(dict(id=identity, job=job, model=model,
                schema=schema, started_at=datetime.now(timezone.utc).isoformat()))
            self.save()
            return identity

    def web(self, job, provider, operation, value):
        with self.lock:
            if len(self.report['web_requests']) >= self.max_web:
                raise RuntimeError('independent web admission stopped')
            record = dict(job=job, provider=provider, operation=operation, value=value, status='started')
            self.report['web_requests'].append(record)
            self.save()
            return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--prior-results', type=Path)
    args = parser.parse_args()
    spec = json.loads(args.manifest.read_text())
    assert spec['frozen_before_execution']
    post_guard = spec.get('mode') == 'post_guard_validation'
    if post_guard:
        assert len(spec['cases']) == 1 and spec['max_model_requests'] == 5 and spec['max_web_requests'] == 10
        assert args.prior_results and digest(args.prior_results.read_text()) == spec['prior_results_sha256']
        prior = json.loads(args.prior_results.read_text())
        assert prior.get('finished_at') and len(prior['model_requests']) + 5 <= 20
        assert len(prior['web_requests']) + 10 <= 40
    else:
        assert len(spec['cases']) == 2 and spec['max_model_requests'] == 20 and spec['max_web_requests'] == 40
    if args.directory.exists():
        parser.error('retain prior evidence and use a new directory')
    args.directory.mkdir(parents=True)
    directory = args.directory.resolve()
    os.environ['REVIEW_TODAY_HARNESS_DB'] = str(directory / 'import.sqlite3')
    os.environ['REVIEW_TODAY_JEV_TEST'] = '0'
    os.environ['REVIEW_TODAY_CONTEXT_PROVIDER'] = 'none'
    os.environ['REVIEW_TODAY_BROWSER_FALLBACK'] = '0'

    def sqlite_fence(event, values):
        if event == 'sqlite3.connect' and not Path(values[0]).resolve().is_relative_to(directory):
            raise RuntimeError('database outside independent comparison directory')
    sys.addaudithook(sqlite_fence)

    from agent_service import config, conversation, web_tools as web, web_resilience as policy
    from agent_service.conversation_store import ConversationStore
    from agent_service.execution_policy import budget_scope
    from agent_service.harness_store import HarnessStore
    from agent_service.schemas import IntentDecision, SessionMessageRequest, TeachingPreparation
    if config.PROVIDER != 'deepseek' or not config.openai_key() or not os.getenv('DEEPSEEK_WEB_API_KEY', '').strip():
        parser.error('configured production role models and independent web credentials required')

    report = dict(manifest_sha256=digest(args.manifest.read_text()), started_at=datetime.now(timezone.utc).isoformat(),
        models=dict(coach=config.COACH_MODEL, evidence=config.RISK_MODEL),
        fixed_nodes=['intent', 'teaching_preparation'], startup_probes=0,
        model_requests=[], web_requests=[], jobs=[])
    if post_guard:
        report.update(prior_model_requests=len(prior['model_requests']), prior_web_requests=len(prior['web_requests']),
            prior_results_sha256=spec['prior_results_sha256'])
    captures = dict(steps=[], web=[])
    io_lock = threading.RLock()
    def save():
        with io_lock:
            for filename, value in [('results.json', report), ('captures.json', captures)]:
                path = directory / filename
                temp = path.with_suffix('.tmp')
                temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
                temp.replace(path)
    admission = Admission(report, save, max_models=spec['max_model_requests'], max_web=spec['max_web_requests'])
    step_scope = ContextVar('comparison_model_step')
    job_scope = ContextVar('comparison_job')
    real_parse, real_backend = conversation.parse_model, web._backend

    def observed_parse(system, prompt, schema, **kwargs):
        step, job = step_scope.get(), job_scope.get()
        # Catch the Harness's format/transport retry before it dispatches again.
        if step.get('used'):
            raise RuntimeError('independent step already made one request')
        original_request, original_usage = kwargs.get('on_request'), kwargs.get('on_usage')
        def request():
            identity = admission.model(step, job['id'], kwargs.get('model'), schema.__name__)
            if original_request:
                harness_identity = original_request()
                report['model_requests'][-1]['harness_request_id'] = harness_identity
                save()
                return harness_identity
            return identity
        def usage(value):
            job.setdefault('usage', []).append(value)
            if original_usage:
                original_usage(value)
            save()
        kwargs.update(on_request=request, on_usage=usage, timeout=min(kwargs.get('timeout', 45), 45))
        with budget_scope(seconds=kwargs['timeout'], limit=1, isolated=True):
            return real_parse(system, prompt, schema, **kwargs)

    class ObservedBackend:
        def __init__(self, provider):
            self.inner = real_backend(provider)
            self.name = provider
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
                captures['web'].append(dict(job=record['job'], provider=self.name, operation=operation,
                    value=value, result=capture))
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

    class ComparisonHarness(conversation.ConversationHarness):
        def _call(self, sid, rid, rev, node, system, prompt, schema, model=config.COACH_MODEL, **kwargs):
            job = job_scope.get()
            case = next(c for c in spec['cases'] if c['id'] == job['case'])
            if node == 'intent':
                return IntentDecision(intents=['question'], scope='conversation', relation='new_topic',
                    needs_verification=True, public_search_query=case['query'], rationale='Fixed public regression scope')
            if node == 'teaching_preparation':
                return TeachingPreparation(public_query=case['query'], official_sources_required=True,
                    source_domains=[case['domain']], concepts=case['concepts'])
            if node not in {'source_candidates', 'evidence_assessment', 'answer'}:
                raise RuntimeError('unexpected comparison model node: ' + node)
            token = step_scope.set({})
            step = dict(job=job['id'], node=node, model=model, system=system, prompt=prompt)
            captures['steps'].append(step)
            try:
                result = super()._call(sid, rid, rev, node, system, prompt, schema, model, **kwargs)
                step['output'] = result.model_dump()
                return result
            finally:
                step_scope.reset(token)
                save()

    save()
    # Rotate the two orders; provider cooldowns and upstream caches are retained.
    orders = [('exa_first', 'exa', 'tavily,deepseek'), ('deepseek_first', 'deepseek', 'exa,tavily')]
    if post_guard:
        orders = orders[1:]
    for index, case in enumerate(spec['cases']):
        for name, primary, fallbacks in orders[index % 2:] + orders[:index % 2]:
            job = dict(id=case['id'] + ':' + name, case=case['id'], configuration=name, usage=[])
            report['jobs'].append(job)
            job_token = job_scope.set(job)
            started = time.monotonic()
            with patch.dict(os.environ, dict(REVIEW_TODAY_SEARCH_PROVIDER=primary,
                    REVIEW_TODAY_SEARCH_FALLBACKS=fallbacks, REVIEW_TODAY_READ_PROVIDER='exa',
                    REVIEW_TODAY_READ_FALLBACKS='tavily,deepseek')):
                with patch.object(conversation, 'parse_model', side_effect=observed_parse), \
                        patch.object(web, '_backend', side_effect=ObservedBackend):
                    harness = ComparisonHarness(ConversationStore(HarnessStore(str(directory / (case['id'] + '-' + name + '.sqlite3')))))
                    harness.judgments = None
                    sid = str(uuid.uuid4())
                    try:
                        accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
                            content=case['question'], thinking_strength='smart'))
                        harness.drain(sid)
                        data = harness.store.get(sid)
                        run = data['runs'][accepted.run_id]
                        job.update(status=run['status'], search_state=run.get('search_state'), error=run.get('error_code'),
                            evidence=run.get('teaching_evidence'), quality_supplement=run.get('quality_supplement'),
                            model_calls=run.get('model_calls', []), source_selection=run.get('source_selection_records', {}),
                            provider_events=[e['payload'] for e in data['events'] if e['stage'] == 'web_provider'],
                            replies=[m['content'] for m in data['messages'] if m['role'] == 'coach'],
                            source_urls=[s['url'] for s in run.get('teaching_sources', [])])
                        assert not data['tasks'] and not data.get('capture_offers'), 'unexpected save/learning side effect'
                    except Exception as error:
                        job.update(status='comparison_failed', error=getattr(error, 'code', type(error).__name__))
            job['elapsed_seconds'] = round(time.monotonic() - started, 3)
            save()
            job_scope.reset(job_token)
            print(json.dumps({k: job.get(k) for k in ('id', 'status', 'search_state', 'error', 'elapsed_seconds')}, ensure_ascii=False), flush=True)
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    save()


if __name__ == '__main__':
    main()
