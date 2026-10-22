"""Complete only the retained pre-start preparation after the lazy-table check."""
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit,unquote
from prepare import OUT, PRIVATE, read, complete_held_archive

state=read(OUT/'setup.json');directory=Path(state['directory']).resolve()
assert state['status']=='PREPARING_HOLD'
assert not (PRIVATE/'setup-before-empty-table-fix.json').exists()
shutil.copy2(OUT/'setup.json',PRIVATE/'setup-before-empty-table-fix.json')
def audit(event,args):
    if event=='socket.connect':raise RuntimeError('No network during held preparation')
    if event=='sqlite3.connect':
        raw=str(args[0]);path=Path(unquote(urlsplit(raw).path) if raw.startswith('file:') else raw).resolve()
        assert path.is_relative_to(directory),'No SQLite outside the new runtime'
sys.addaudithook(audit)
complete_held_archive(state)
