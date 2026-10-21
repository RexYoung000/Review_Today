"""Read only this batch's SQLite payloads; no production imports or requests."""
import json
from pathlib import Path
import sqlite3
import sys

OUT = Path(__file__).resolve().parent


def snapshot(phase):
    setup = json.loads((OUT / 'setup.json').read_text())
    directory = Path(setup['directory'])
    with sqlite3.connect(f'file:{directory}/checkpoint.sqlite3?mode=ro', uri=True) as db:
        data = json.loads(db.execute('SELECT payload FROM agent_sessions_v2 WHERE session_id=?',
                                   (setup['session_id'],)).fetchone()[0])
        data['tasks'] = {r['task_id']: r for row in db.execute('SELECT payload FROM harness_tasks')
                         if (r := json.loads(row[0])).get('session_id') == setup['session_id']}
        batches = [json.loads(row[0]) for row in db.execute('SELECT payload FROM agent_capability_batches')]
    (OUT / (phase + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    (OUT / 'capability-ledger.json').write_text(json.dumps(batches, ensure_ascii=False, indent=2) + '\n')
    quota = json.loads((directory / 'quota.json').read_text()) if (directory / 'quota.json').exists() else {}
    summary = dict(phase=phase, model_requests=quota.get('model_requests', 0), web_operations=quota.get('web_operations', 0),
        stop=(directory/'STOP').exists(), runs=[dict(id=k, status=v['status'], error=v.get('error_code')) for k,v in data['runs'].items()],
        active_task=data['active_task_id'], messages=[dict(role=m['role'], content=m['content']) for m in data['messages'][-2:]],
        offers=[dict(id=k, version=o.get('version'), status=o.get('status'), points=len(o.get('preview_points',[])))
                for k,o in data['capture_offers'].items()], tasks=len(data['tasks']))
    (OUT / (phase+'-summary.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return data


if __name__ == '__main__': snapshot(sys.argv[1])
