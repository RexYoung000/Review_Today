"""Read-only protection comparison for this isolated batch. No runtime launch."""
import hashlib,importlib.util,json,subprocess,sys,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('held_prepare',ROOT/'docs/evidence/2026-10-22-fullflow-preflight/prepare.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
s=m.read(ROOT/'docs/evidence/2026-10-22-fullflow-preflight/setup.json')
m.stopped()
report=dict(daily_files_unchanged=m.files(m.SUPPORT)==s['daily_files'],daily_app_unchanged=m.app_files(m.DAILY)==s['daily_app_inventory'],old_frozen_files_unchanged=all(m.sha(Path(p))==h for p,h in s['old_frozen_files'].items()),source_config_unchanged=all(m.sha(ROOT/p)==h for p,h in s['protected_fingerprints'].items()),original_modules_unchanged=all(m.sha(Path(p))==h for p,h in s['original_module_files'].items()),owned_modules_unchanged=all(m.sha(Path(p))==h for p,h in s['owned_support_files'].items()),project_diff_unchanged=hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest()==s['project_diff_sha256'])
assert all(report.values()),report
identifiers=re.findall(r'^identifier:\s*(.*)$',subprocess.check_output([m.LS,'-dump'],text=True),re.M)
report['registered_entries']=sum(bool(re.search(r'review[-_]?today',v,re.I)) for v in identifiers)
report['spotlight_paths']=subprocess.check_output(['mdfind',"kMDItemContentType == 'com.apple.application-bundle' && kMDItemCFBundleIdentifier == 'Rex.Review-Today'"],text=True).splitlines()
assert report['registered_entries']==1 and report['spotlight_paths']==[str(m.DAILY)]
report.update(daily_files=98,old_frozen_files=172,source_config_files=238)
print(json.dumps(report,ensure_ascii=False,indent=2))
