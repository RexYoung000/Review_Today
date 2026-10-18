"""Opt-in fixed public sample comparison: at most 15 web operations, no model calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

PROVIDERS = ('deepseek', 'exa', 'tavily')
QUERIES = (
    ('zh', 'Python 列表 append extend 区别 site:docs.python.org'),
    ('en', 'Python list append extend difference site:docs.python.org'),
)
PAGES = (
    ('python_zh', 'https://docs.python.org/zh-cn/3/tutorial/datastructures.html', ('append', 'extend', '列表')),
    ('python_en', 'https://docs.python.org/3/tutorial/datastructures.html', ('append', 'extend', 'list')),
    ('deepseek_search', 'https://api-docs.deepseek.com/zh-cn/guides/search/', ('need_content', '128', 'Fetch')),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists; retain the previous comparison')
    # Import only the common tool layer. It loads the ignored web configuration.
    from agent_service import web_tools as web, web_resilience as policy
    from agent_service.call_errors import CallError
    if not os.getenv('DEEPSEEK_WEB_API_KEY', '').strip():
        parser.error('DEEPSEEK_WEB_API_KEY is required; model credentials are not used')
    report = dict(started_at=datetime.now(timezone.utc).isoformat(), max_operations=15,
                  model_requests=0, automatic_retries=False, fallback_enabled=False,
                  boundary='Fixed public samples only. Marker coverage is not semantic completeness or correctness.',
                  records=[])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as out:
        json.dump(report, out, ensure_ascii=False, indent=2)

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    def measure(provider, kind, sample, value, markers=()):
        if len(report['records']) >= report['max_operations']:
            raise RuntimeError('comparison operation budget exhausted')
        record = dict(provider=provider, operation=kind, sample=sample,
                      query=value if kind == 'search' else None, url=value if kind == 'read' else None,
                      status='started', events=[])
        report['records'].append(record)
        save()  # A killed request remains recorded as started, never silently re-run.
        started = time.monotonic()
        try:
            with policy.web_round_scope(on_event=record['events'].append):
                if kind == 'search':
                    result = json.loads(web.web_search_text(value))
                    record['results'] = result['results']
                    record['result_count'] = len(result['results'])
                    from urllib.parse import urlsplit
                    record['official_domain_results'] = sum(
                        (urlsplit(r['url']).hostname or '') == 'docs.python.org' for r in result['results'])
                else:
                    result = web.read_public_url(value)
                    record.update(title=result[0], body_characters=len(result[1]),
                                  body_sha256=hashlib.sha256(result[1].encode()).hexdigest(),
                                  marker_hits={marker: marker.casefold() in result[1].casefold() for marker in markers},
                                  excerpt=result[1][:1600], read_details=getattr(result, 'details', {}))
            record['status'] = 'ok'
        except CallError as error:
            record.update(status='failed', error_code=error.code)
            # route() only returns allowlisted RT.WEB.* causes, never raw provider bodies.
            if error.diagnostic.startswith('RT.WEB.'):
                record['cause'] = error.diagnostic
        except ValueError:
            record.update(status='failed', error_code='INVALID_PUBLIC_RESULT')
        finally:
            record['elapsed_seconds'] = round(time.monotonic() - started, 3)
            save()
        print(json.dumps({k: record[k] for k in ('provider', 'operation', 'sample', 'status', 'elapsed_seconds')},
                         ensure_ascii=False), flush=True)

    for provider in PROVIDERS:
        with patch.dict(os.environ, dict(REVIEW_TODAY_SEARCH_PROVIDER=provider,
            REVIEW_TODAY_READ_PROVIDER=provider, REVIEW_TODAY_SEARCH_FALLBACKS='',
            REVIEW_TODAY_READ_FALLBACKS='', REVIEW_TODAY_BROWSER_FALLBACK='0',
            REVIEW_TODAY_CONTEXT_PROVIDER='none')):
            for sample, query in QUERIES:
                measure(provider, 'search', sample, query)
            for sample, url, markers in PAGES:
                measure(provider, 'read', sample, url, markers)
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    report['operations'] = len(report['records'])
    report['deepseek_possible_cost_cny_upper_bound'] = .025
    save()


if __name__ == '__main__':
    main()
