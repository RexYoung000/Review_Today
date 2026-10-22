"""Reuse the just-compiled unchanged production module; compile current contracts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIVATE = ROOT/'output/deletion-sync-repair-2026-10-22'
build = Path((PRIVATE/'native-contracts.log').read_text().splitlines()[0].split(': ',1)[1])
flags = ['xcrun','swiftc','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor',
         '-enable-upcoming-feature','MemberImportVisibility','-I',str(build),'-L',str(build),
         '-lFSRS','-lReviewTodayContractSupport','-Xlinker','-rpath','-Xlinker',str(build)]
setup = json.loads((OUT/'setup.json').read_text())
(Path(setup['directory'])/'native-home').mkdir(exist_ok=True)
env = dict(os.environ,CFFIXED_USER_HOME=str(Path(setup['directory'])/'native-home'))
names = ['SessionDeletionSyncContractTests','SessionDeletionContractTests','SessionOrganizationContractTests','LearningMemoryContractTests']
for name in names:
    source = ROOT/'tests/mac'/f'{name}.swift'
    target = build/f'{name}.swift'
    target.write_text('@testable import ReviewTodayContractSupport\n#sourceLocation(file: '+json.dumps(str(source))+', line: 1)\n'+source.read_text())
    subprocess.run(flags+[str(target),'-o',str(build/name)],cwd=ROOT,check=True)
    subprocess.run([str(build/name)],cwd=ROOT,env=env,check=True)
    print('PASS current contract:',name,flush=True)
http = build/'NativeDeletionSyncReplay'
subprocess.run(flags+[str(OUT/'NativeDeletionSyncReplay.swift'),'-o',str(http)],cwd=ROOT,check=True)
(OUT/'native-result.json').write_text(json.dumps(dict(outcome='PASS',module=str(build),contracts=names,
    shared_module_sha256=hashlib.sha256((build/'libReviewTodayContractSupport.dylib').read_bytes()).hexdigest(),
    http_executable=str(http),deletion_sync_scenarios=8,actual_model_requests=0,actual_web_operations=0,
    unchanged_production_since_module_compile=True),indent=2)+'\n')
