"""Read only this batch's service database, quota and optional local health."""
import json
from pathlib import Path
import sqlite3
import sys
import urllib.request

OUT = Path(__file__).resolve().parent


def snapshot(phase):
    setup = json.loads((OUT / 'setup.json').read_text())
    directory = Path(setup['directory'])
    with sqlite3.connect(f'file:{directory}/checkpoint.sqlite3?mode=ro', uri=True) as db:
        row = db.execute('select payload from agent_sessions_v2 where session_id=?', (setup['session_id'],)).fetchone()
        data = json.loads(row[0]) if row else dict(session_id=setup['session_id'], runs={}, messages=[], capture_offers={}, active_task_id=None)
        data['tasks'] = {r['task_id']: r for row in db.execute('select payload from harness_tasks')
            if (r := json.loads(row[0])).get('session_id') == setup['session_id']}
        batches = [json.loads(row[0]) for row in db.execute('select payload from agent_capability_batches')]
    (OUT / (phase + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    (OUT / 'capability-ledger.json').write_text(json.dumps(batches, ensure_ascii=False, indent=2) + '\n')
    quota = json.loads((directory / 'quota.json').read_text()) if (directory / 'quota.json').exists() else {}
    summary = dict(phase=phase, model_requests=quota.get('model_requests', 0), web_operations=quota.get('web_operations', 0),
        stop=(directory / 'STOP').exists(), runs=[dict(id=k, status=r['status'], error=r.get('error_code'),
            action=(r.get('intent') or {}).get('action')) for k, r in data['runs'].items()],
        active_task=data.get('active_task_id'), messages=[dict(role=m['role'], content=m['content']) for m in data['messages'][-2:]],
        offers=[dict(id=k, version=o.get('version'), status=o.get('status'), title=o.get('title'),
            points=len(o.get('preview_points', [])), preview_summary=o.get('preview_summary')) for k, o in data.get('capture_offers', {}).items()], tasks=len(data['tasks']))
    (OUT / (phase + '-summary.json')).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return data


if __name__ == '__main__':
    if sys.argv[1] == 'health':
        setup = json.loads((OUT / 'setup.json').read_text())
        with urllib.request.urlopen(f'http://127.0.0.1:{setup["port"]}/healthz', timeout=3) as response:
            health = json.load(response)
        (OUT / 'startup-health.json').write_text(json.dumps(health, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(dict(status=health['status'], roles={role:{key:v.get(key) for key in ('status', 'error', 'streaming')}
            for role,v in health['model_roles'].items()}), ensure_ascii=False))
    else:
        snapshot(sys.argv[1])
