"""Offline validation of recorded evidence; truncated logs are never PASS."""
import json


def read_report(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(rows) < 2 or rows[0].get('type') != 'header' or rows[-1].get('type') != 'summary':
        raise ValueError('incomplete report: header and final summary required')
    header, summary = rows[0], rows[-1]
    if header.get('schema_version') != 1 or header.get('layer') not in {'live_fixed_context', 'live_generated_flow'}:
        raise ValueError('unsupported evidence schema/layer')
    if not (isinstance(header.get('code'), dict) and header['code'].get('source_sha256')
            and isinstance(header.get('models'), dict) and header['models'].get('router')
            and 'fixture' in header and header.get('started_at')):
        raise ValueError('missing version, model, fixture or time metadata')
    planned = header.get('planned')
    if not isinstance(planned, list) or not planned or any(type(x) is not str or not x for x in planned) or len(set(planned)) != len(planned):
        raise ValueError('invalid execution plan')
    results, errors = [], []
    for row in rows[1:-1]:
        if row.get('type') == 'case_error' and row.get('id') in planned:
            errors.append(row['id'])
        elif row.get('type') == 'result' and row.get('id') in planned:
            checks = row.get('checks')
            if not isinstance(checks, dict) or not {'completed', 'real_intent', 'no_blocked_tool_attempt'} <= checks.keys() or any(type(v) is not bool for v in checks.values()):
                raise ValueError('missing or invalid check results')
            if not all(k in row for k in ('before', 'after', 'input', 'run', 'replies', 'model_calls', 'tool_attempts')):
                raise ValueError('missing actual input/state/execution record')
            actual = dict(completed=row['run'].get('status') == 'completed' and bool(row['replies']),
                          real_intent=any(c.get('schema') == 'IntentDecision' and 'output' in c for c in row['model_calls']),
                          no_blocked_tool_attempt=not row['tool_attempts'])
            if any(checks[key] != value for key, value in actual.items()):
                raise ValueError('execution checks disagree with recorded facts')
            expected = 'PASS' if all(checks.values()) else 'FAIL'
            if row.get('automatic_result') != expected:
                raise ValueError('result disagrees with its checks')
            results.append(row)
        else:
            raise ValueError('unknown record or case ID')
    ids = [r['id'] for r in results]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate result')
    missing = [x for x in planned if x not in ids]
    failed = [r['id'] for r in results if r['automatic_result'] == 'FAIL']
    expected = 'FAIL' if missing or failed or errors or summary.get('error_type') else 'PASS'
    if (summary.get('planned') != len(planned) or summary.get('executed') != len(results)
            or summary.get('missing') != missing or summary.get('failed') != failed
            or summary.get('automatic_result') != expected):
        raise ValueError('summary disagrees with actual coverage/results')
    return dict(summary, layer=header['layer'])
