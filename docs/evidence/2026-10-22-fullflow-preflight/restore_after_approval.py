"""Only after new allowance confirmation: restore QA archive, never launch it."""
from pathlib import Path
import subprocess
from bootstrap import check_approved
from prepare import ROOT, OUT, PRIVATE, DAILY, SUPPORT, read, sha, files, app_files, stopped


def main():
    state=read(OUT/'setup.json');directory=Path(state['directory'])
    check_approved(directory,ROOT)  # Pending/HOLD rejects before extraction or DB access.
    stopped()
    assert files(SUPPORT)==state['daily_files'] and app_files(DAILY)==state['daily_app_inventory']
    assert all(sha(Path(p))==h for p,h in state['old_frozen_files'].items())
    assert all(sha(Path(p))==h for p,h in state['owned_support_files'].items())
    held=read(PRIVATE/'held-file-pins.json');current=files(directory)
    assert set(current)==set(held)-{str(directory/'HOLD')}
    assert all(sha(Path(p))==h for p,h in held.items() if p not in {str(directory/'authorization.json'),str(directory/'HOLD')})
    assert sha(Path(state['native_zip']))==state['native_zip_sha256']
    target=Path(state['native_app']);assert not target.exists()
    subprocess.run(['ditto','-x','-k',state['native_zip'],str(directory)],check=True)
    assert app_files(target)==state['native_bundle_inventory']
    subprocess.run(['codesign','--verify','--deep','--strict',str(target)],check=True)
    print('Approved QA archive restored in .noindex; App/service have not started.')


if __name__=='__main__':main()
