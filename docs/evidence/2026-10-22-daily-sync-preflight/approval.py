"""Human approval is recorded separately; preparation never authorizes execution."""
import json
from pathlib import Path
from prepare import ROOT, OUT, PRIVATE, DAILY, SUPPORT, sha


def require_approved():
    operation = json.loads((PRIVATE/'operation-authorization.json').read_text())
    activation = json.loads((PRIVATE/'activation/authorization.json').read_text())
    if operation.get('status') != 'approved' or (PRIVATE/'OPERATION_HOLD').exists():
        raise PermissionError('Daily update and historical cleanup are pending explicit approval')
    if activation.get('status') != 'approved' or (PRIVATE/'activation/HOLD').exists() or (PRIVATE/'activation/STOP').exists():
        raise PermissionError('The new startup allowance is not active')
    if operation.get('daily_app') != str(DAILY) or operation.get('backend_database') != str(SUPPORT/'agent-harness.sqlite3'):
        raise PermissionError('Daily destination differs from the reviewed plan')
    if operation.get('pending_sessions') != 37 or operation.get('compatibility_scope_sha256') != sha(ROOT/'tools/legacy-deletion-lifecycle-scope.json'):
        raise PermissionError('Historical scope differs from the reviewed plan')
    if (activation.get('actual_model_request_limit'),activation.get('provider_web_operation_limit')) != (8,0):
        raise PermissionError('Only the reviewed new 8/0 startup batch is supported')
    if activation.get('database_path') != str(SUPPORT/'agent-harness.sqlite3'):
        raise PermissionError('Startup database differs from the reviewed daily destination')
    pins = json.loads((OUT/'source-pins.json').read_text())
    if not all(sha(ROOT/p)==value for p,value in pins.items()):
        raise PermissionError('A pinned source or configuration changed')
    return operation,activation
