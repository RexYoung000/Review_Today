"""After normal native exit, read durable QA data and restore prior QA app."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(path): return {str(p.relative_to(path)):digest(p) for p in Path(path).rglob('*') if p.is_file()}


def main():
    setup = json.loads((OUT/'setup.json').read_text())
    directory, app, support = Path(setup['directory']), Path(setup['native_app']), Path(setup['support_dir'])
    assert (directory/'STOP').exists()
    assert not subprocess.run(['pgrep','-fl','/ContinuousResumeQA.app/Contents/MacOS/'],capture_output=True,text=True).stdout.strip()
    listener = subprocess.run(['lsof','-nP',f'-iTCP:{setup["port"]}','-sTCP:LISTEN'],capture_output=True,text=True)
    assert listener.returncode==1 and not listener.stdout.strip()
    source = ROOT/'docs/evidence/2026-10-16-status-native-input/NativeDiskRead.swift'
    cmd = ['xcrun','swiftc','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor',
        '-enable-upcoming-feature','MemberImportVisibility','-I',str(support),'-L',str(support),
        '-lReviewTodayContractSupport','-lFSRS','-Xlinker','-rpath','-Xlinker',str(support),str(source),
        '-o',str(directory/'native-disk-reader')]
    with (OUT/'native-disk-read-build.log').open('w') as log:
        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
    with (OUT/'native-disk-read.log').open('w') as log:
        subprocess.run([str(directory/'native-disk-reader'),str(directory)],stdout=log,stderr=subprocess.STDOUT,check=True)
    shutil.copy2(directory/'native-disk-read.json',OUT/'native-disk-read.json')
    assert digest(app/'Contents/MacOS/ContinuousResumeQA')==setup['native_binary_sha256']
    shutil.move(str(app/'Contents'),str(directory/'used-native-contents'))
    shutil.copytree(directory/'prior-resume-app/Contents',app/'Contents')
    with (OUT/'native-restore.log').open('w') as log:
        subprocess.run(['codesign','--verify','--strict',str(app)],stdout=log,stderr=subprocess.STDOUT,check=True)
    assert files(app)==setup['prior_app_files']
    result=dict(native_app_closed=True,service_closed=True,prior_qa_app_restored=True,
        fresh_native_process_read=True,reader_source=str(source.relative_to(ROOT)),reader_sha256=digest(source),
        daily_app_replaced=False,model_requests=json.loads((directory/'quota.json').read_text())['model_requests'])
    (OUT/'cleanup.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
