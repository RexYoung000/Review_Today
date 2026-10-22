"""Restore the archived QA only after this batch is approved; never launch it."""
import subprocess
from pathlib import Path
from bootstrap import check_approved
from common import *
def main():
    state=read(OUT/'setup.json');runtime=Path(state['directory']);check_approved(runtime,ROOT)
    check_protection(state)
    held=read(PRIVATE/'held-file-pins.json');current=files(runtime)
    assert set(current)==set(held)-{str(runtime/'HOLD')}
    assert all(sha(Path(p))==h for p,h in held.items() if p not in {str(runtime/'HOLD'),str(runtime/'authorization.json')})
    assert all(sha(Path(p))==h for p,h in state['owned_support_files'].items())
    assert sha(Path(state['native_zip']))==state['native_zip_sha256']
    app=Path(state['native_app']);assert not app.exists()
    subprocess.run(['ditto','-x','-k',state['native_zip'],str(runtime)],check=True)
    assert app_files(app)==state['native_bundle_inventory'];subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
    print('Approved QA archive restored; App/service not started.')
if __name__=='__main__':main()
