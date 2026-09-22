"""Recompute observed counts/cost ranges without running models or reading user data."""
import collections
import json
from pathlib import Path
import statistics
import sys

FOLDER = Path(__file__).resolve().parent
ROOT = FOLDER.parents[2]
sys.path.insert(0, str(ROOT / 'agent-service'))
from tests.judgment_comparison.reporting import price_range

prices = json.loads((ROOT / 'agent-service/tests/fixtures/judgment_comparison/prices.json').read_text())


def summarize(rows):
    calls = [c for r in rows for c in r['run'].get('model_calls', [])]
    cost = [price_range(c['model'], u, prices) for c in calls for u in c.get('usage', [])]
    known = [c for c in cost if c is not None]
    elapsed = [r['run']['elapsed_ms'] for r in rows if isinstance(r['run'].get('elapsed_ms'), (int, float))]
    return dict(turns=len(rows), passed=sum(r['automatic_result'] == 'PASS' for r in rows),
        failed=[dict(id=r['id'], checks=[k for k,v in r['checks'].items() if not v]) for r in rows if r['automatic_result'] != 'PASS'],
        requests=sum(c.get('transport_requests', 0) for c in calls),
        jev_requests=sum(c.get('transport_requests', 0) for c in calls if c['model'].startswith('jev-')),
        by_node=dict(collections.Counter(c['node'] for c in calls)),
        scope_reply_sources=dict(collections.Counter(r['run']['scope_reply']['source'] for r in rows if r['run'].get('scope_reply'))),
        missing_usage_requests=sum(max(0,c.get('transport_requests',0)-len(c.get('usage',[]))) for c in calls),
        input_tokens=sum(u.get('input_tokens',0) for c in calls for u in c.get('usage',[])),
        output_tokens=sum(u.get('output_tokens',0) for c in calls for u in c.get('usage',[])),
        known_cost_usd_range=[round(sum(c[i] for c in known),8) for i in (0,1)],
        median_ms=statistics.median(elapsed) if elapsed else None,
        range_ms=[min(elapsed),max(elapsed)] if elapsed else None)

reports = {}
all_rows = []
for path in sorted(FOLDER.glob('live-v*.jsonl')):
    data = [json.loads(line) for line in path.read_text().splitlines()]
    rows = [r for r in data if r.get('type') == 'result']
    all_rows.extend(rows)
    reports[path.name] = dict(total=summarize(rows), variants={v:summarize([r for r in rows if r['id'].startswith(v + '/')]) for v in ('baseline','jev')})
native = {}
for path in sorted(FOLDER.glob('native-v*.json')):
    data = json.loads(path.read_text())
    rows = []
    for index, run in enumerate(data['session']['runs'].values()):
        checks = dict(completed=run['status']=='completed', scope_path=index >= 3 or bool(run.get('scope_reply')))
        rows.append(dict(id=path.stem+'/'+str(index+1), run=run, checks=checks,
            automatic_result='PASS' if all(checks.values()) else 'FAIL'))
    native[path.name] = summarize(rows)
output = dict(price_snapshot=prices, reports=reports, development_total=summarize(all_rows), native=native,
    note='Known usage only; missing usage is not zero. Excludes model capability probes. Paired order is not a controlled latency benchmark; no savings claim.')
(FOLDER / 'summary.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(reports['live-v5.jsonl'],ensure_ascii=False,indent=2))
