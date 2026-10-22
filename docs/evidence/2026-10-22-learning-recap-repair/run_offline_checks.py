"""Run unit checks with all non-loopback socket connections denied."""
import atexit,os,re,shutil,sys,tempfile
from urllib.parse import urlsplit,unquote
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
scratch=Path(tempfile.mkdtemp(prefix='review-today-recap-tests-',suffix='.noindex'))
selected_provider=os.environ.get('REVIEW_TODAY_LLM_PROVIDER','openai_compatible')
# Reuse the project's existing literal test-environment contract; never load
# real keys/fallbacks from local dotenv settings into this controlled suite.
exports=dict(re.findall(r"^export ([A-Z_]+)='([^']*)'$",(ROOT/'agent-service/run-controlled.sh').read_text(),re.M))
assert exports.get('REVIEW_TODAY_READ_FALLBACKS')=='' and exports.get('OPENAI_API_KEY')==''
os.environ.update(exports)
os.environ['REVIEW_TODAY_LLM_PROVIDER']=selected_provider
os.environ['REVIEW_TODAY_HARNESS_DB']=str(scratch/'import.sqlite3')
os.environ['REVIEW_TODAY_REVIEW_DB']=str(scratch/'review.sqlite3')
atexit.register(lambda:shutil.rmtree(scratch,ignore_errors=True))
DAILY=Path.home()/'Library/Application Support/Review Today'
def audit(event,args):
    if event=='sqlite3.connect':
        value=str(args[0]);path=Path(unquote(urlsplit(value).path) if value.startswith('file:') else value).expanduser().resolve()
        if path.is_relative_to(DAILY):raise AssertionError('Daily SQLite forbidden in offline validation')
    if event=='socket.connect':
        address=args[1]
        if isinstance(address,tuple) and address[0] not in {'127.0.0.1','::1','localhost'}:
            raise AssertionError('External network is forbidden in this offline validation')
sys.addaudithook(audit)
os.chdir(ROOT/'agent-service');sys.path.insert(0,str(ROOT/'agent-service'))
print('Offline check provider: '+os.environ['REVIEW_TODAY_LLM_PROVIDER'],flush=True)
if len(sys.argv)>1 and sys.argv[1]=='--script':
    import runpy
    target=Path(sys.argv[2]).resolve();assert target.is_relative_to(ROOT/'agent-service/tests')
    sys.argv=[str(target),*sys.argv[3:]]
    runpy.run_path(str(target),run_name='__main__')
else:
    import pytest
    raise SystemExit(pytest.main(sys.argv[1:] or ['-q']))
