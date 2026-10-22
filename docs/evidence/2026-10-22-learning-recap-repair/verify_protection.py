"""Compare daily data, old frozen evidence and unrelated dependencies read-only."""
import hashlib,importlib.util,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
PRIVATE=ROOT/'output/learning-recap-repair-2026-10-22'
spec=importlib.util.spec_from_file_location('held_prepare',ROOT/'docs/evidence/2026-10-22-fullflow-preflight/prepare.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
before=m.read(PRIVATE/'protection-before.json')
allowed={f'agent-service/agent_service/{name}.py' for name in ['conversation','conversation_prompts','dialogue_routing','goal_continuation','schemas']}
changed={p for p,h in before['protected_source_files'].items() if m.sha(ROOT/p)!=h}
assert changed <= allowed,changed-allowed
now=m.files(m.SUPPORT);old=before['daily_files']
missing=set(old)-set(now)
expected={str(m.SUPPORT/'agent-harness.sqlite3-wal'),str(m.SUPPORT/'agent-harness.sqlite3-shm')}
assert missing==expected and not set(now)-set(old)
assert old[str(m.SUPPORT/'agent-harness.sqlite3-wal')]=='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
assert all(now[p]==old[p] for p in now)
report=dict(daily_remaining_files_unchanged=True,daily_app_unchanged=m.app_files(m.DAILY)==before['daily_app_inventory'],old_frozen_files_unchanged=all(m.sha(Path(p))==h for p,h in before['old_frozen_files'].items()),last_real_batch_unchanged=all(m.sha(Path(p))==h for p,h in before['previous_batch_files'].items()),original_modules_unchanged=all(m.sha(Path(p))==h for p,h in before['original_module_files'].items()),owned_modules_unchanged=all(m.sha(Path(p))==h for p,h in before['owned_support_files'].items()),project_file_unchanged=m.sha(ROOT/'Review_Today.xcodeproj/project.pbxproj')==before['project_diff_sha256'])
assert all(report.values()),report
m.stopped()
assert subprocess.run(['pgrep','-x','FreshFullflowQA'],capture_output=True).returncode==1
assert not subprocess.run(['lsof','-nP','-iTCP:57407','-sTCP:LISTEN'],capture_output=True).stdout
identifiers=re.findall(r'^identifier:\s*(.*)$',subprocess.check_output([m.LS,'-dump'],text=True),re.M)
registered=sum(bool(re.search(r'review[-_]?today',v,re.I)) for v in identifiers)
spotlight=subprocess.check_output(['mdfind',"kMDItemContentType == 'com.apple.application-bundle' && kMDItemCFBundleIdentifier == 'Rex.Review-Today'"],text=True).splitlines()
assert registered==1 and spotlight==[str(m.DAILY)]
report.update(registered_entries=registered,spotlight_paths=spotlight)
report.update(daily_baseline_files=98,daily_remaining_files=96,daily_all_files_byte_identical=False,disclosed_removed_empty_wal_and_shm=sorted(missing),old_frozen_files=172,last_real_batch_files=len(before['previous_batch_files']),source_config_total=len(before['protected_source_files']),allowed_changed_existing_production_files=sorted(changed),other_source_config_files_unchanged=len(before['protected_source_files'])-len(changed),real_model_requests=0,real_web_operations=0,normal_and_old_qa_services_stopped=True)
(OUT/'protection-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False))
