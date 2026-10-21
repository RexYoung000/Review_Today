"""Run existing controlled suite with extra network/daily-SQLite fences."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent


def main():
    directory=Path(tempfile.mkdtemp(prefix='review-today-save-query-checks-',dir='/tmp'))
    (directory/'sitecustomize.py').write_text('''import sys,ipaddress,json,os
from pathlib import Path
def audit(event,args):
    blocked=False
    if event=='socket.connect':
        address=args[1]
        try: allowed=isinstance(address,tuple) and ipaddress.ip_address(address[0]).is_loopback
        except ValueError: allowed=False
        blocked=not allowed
    elif event=='sqlite3.connect' and args[0]!=':memory:':
        value=str(args[0]).removeprefix('file:').split('?',1)[0]
        blocked=not Path(value).resolve().is_relative_to('/private/tmp')
    if blocked:
        with (Path(__file__).parent/'denied.jsonl').open('a') as f: f.write(json.dumps(dict(pid=os.getpid(),event=event))+'\\n')
        raise RuntimeError('Offline checks disallow external sockets and daily SQLite')
sys.addaudithook(audit)
''')
    env=os.environ.copy();env.update(PYTHONPATH=str(directory),TMPDIR=str(directory))
    with (OUT/'controlled.log').open('w') as log:
        result=subprocess.run(['bash','run-controlled.sh'],cwd=ROOT/'agent-service',env=env,
                              stdout=log,stderr=subprocess.STDOUT)
    denied=(directory/'denied.jsonl').read_text().splitlines() if (directory/'denied.jsonl').exists() else []
    report=dict(exit_code=result.returncode,guard_directory=str(directory),denied_operations=[json.loads(x) for x in denied],
                actual_model_requests=0,actual_provider_web_operations=0)
    (OUT/'controlled-result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    raise SystemExit(result.returncode)


if __name__=='__main__': main()
