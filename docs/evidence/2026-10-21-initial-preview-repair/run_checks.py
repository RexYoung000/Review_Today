"""Run existing controlled suite with extra network/daily-SQLite fences."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent


def main():
    directory=Path(tempfile.mkdtemp(prefix='review-today-initial-preview-checks-',dir='/tmp'))
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
    name='deepseek' if '--deepseek' in sys.argv else 'targeted' if '--targeted' in sys.argv else 'controlled'
    command=['bash','run-controlled.sh']
    if name in ('targeted','deepseek'):
        env.update(REVIEW_TODAY_HARNESS_DB=str(directory/'isolated.sqlite3'),
            OPENAI_API_KEY='',DEEPSEEK_API_KEY='',DEEPSEEK_WEB_API_KEY='',TYPESAFE_API_KEY='',
            EXA_API_KEY='',TAVILY_API_KEY='',BRAVE_API_KEY='',REVIEW_TODAY_JEV_TEST='0',
            REVIEW_TODAY_LLM_PROVIDER='openai_compatible',REVIEW_TODAY_CONTEXT_PROVIDER='none',
            REVIEW_TODAY_SEARCH_PROVIDER='none',REVIEW_TODAY_READ_PROVIDER='local',
            REVIEW_TODAY_SEARCH_FALLBACKS='',REVIEW_TODAY_READ_FALLBACKS='',
            REVIEW_TODAY_TAVILY_KEYLESS='0',REVIEW_TODAY_BROWSER_FALLBACK='0')
        command=['.venv/bin/python','-m','pytest','-q',
            'tests/test_initial_capture_preview_repair.py','tests/test_knowledge_invitation.py',
            'tests/test_knowledge_invitation_preview.py','tests/test_capture_evaluation_quotes.py',
            'tests/test_structured_recovery.py','tests/test_update_preview_repair.py',
            'tests/test_ordinary_check_coverage.py']
    if name=='deepseek':
        env['REVIEW_TODAY_LLM_PROVIDER']='deepseek'
        command.remove('tests/test_structured_recovery.py')
    with (OUT/(name+'.log')).open('w') as log:
        result=subprocess.run(command,cwd=ROOT/'agent-service',env=env,
                              stdout=log,stderr=subprocess.STDOUT)
    logfile=OUT/(name+'.log')
    logfile.write_text('\n'.join(line.rstrip() for line in logfile.read_text().splitlines())+'\n')
    denied=(directory/'denied.jsonl').read_text().splitlines() if (directory/'denied.jsonl').exists() else []
    report=dict(exit_code=result.returncode,guard_directory=str(directory),denied_operations=[json.loads(x) for x in denied],
                actual_model_requests=0,actual_provider_web_operations=0)
    (OUT/(name+'-result.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    raise SystemExit(result.returncode)


if __name__=='__main__': main()
