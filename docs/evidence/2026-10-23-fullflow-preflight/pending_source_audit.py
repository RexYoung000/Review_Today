"""External audit of the exact owned sitecustomize before its own catch handler."""
import os
import sys
from common import *

state=read(OUT/'setup.json');runtime=Path(state['directory']);before=files(runtime)
program='''import runpy,sys
def audit(event,args):
    if event in {'sqlite3.connect','socket.connect'}:raise AssertionError('Unauthorized runtime attempt')
sys.addaudithook(audit)
runpy.run_path(sys.argv[1],run_name='__main__')
raise AssertionError('Pending sitecustomize returned')
'''
result=subprocess.run([sys.executable,'-B','-c',program,str(runtime/'owned-project/agent-service/sitecustomize.py')],
    capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),timeout=20)
(OUT/'pending-source-audit.log').write_text(result.stdout+result.stderr)
assert result.returncode==74 and result.stdout.strip()=='QA_BOOTSTRAP_FAILED:PermissionError'
assert files(runtime)==before
check_protection(state)
write(OUT/'pending-source-audit.json',dict(status='PASS',external_audit_precedes_owned_audit=True,
    unexpected_sqlite_or_network_would_be_distinct_assertion_error=True,actual_requests=0,
    runtime_files_unchanged=True,source_sha256=sha(runtime/'owned-project/agent-service/sitecustomize.py')))
print('PASS exact owned entry externally audited: pending refusal, no SQLite or socket attempt.')
