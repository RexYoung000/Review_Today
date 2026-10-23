"""One pending authorization covers only this prepared App and startup allowance."""
from common import ROOT, OUT, PRIVATE, DAILY, SUPPORT, read, sha


def require_approved():
    directory = PRIVATE / 'activation'
    spec = read(directory / 'authorization.json')
    if spec.get('status') != 'approved' or (directory / 'HOLD').exists() or (directory / 'STOP').exists():
        raise PermissionError('Daily update and new 8/0 startup allowance are pending explicit approval')
    plan = read(OUT / 'plan.json')
    if (spec.get('batch_id'), spec.get('actual_model_request_limit'), spec.get('provider_web_operation_limit')) != (plan['batch_id'], 8, 0):
        raise PermissionError('Startup batch or limits differ from reviewed plan')
    if spec.get('daily_app') != str(DAILY) or spec.get('database_path') != str(SUPPORT / 'agent-harness.sqlite3'):
        raise PermissionError('Unexpected daily App or database')
    if spec.get('scope') != plan['scope']:
        raise PermissionError('Scope differs from reviewed update-only plan')
    if not all(sha(ROOT / p) == h for p, h in read(OUT / 'source-pins.json').items()):
        raise PermissionError('Prepared source, configuration or execution pin changed')
    return spec
