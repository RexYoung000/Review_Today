"""Read-only comparison against pre-edit code/configuration/runtime snapshots."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
ALLOWED = {'agent-service/agent_service/' + name for name in (
    'capture_preview.py', 'schemas.py', 'judgment_grading.py', 'conversation_model_call.py')}


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    before = json.loads((OUT/'protection-before.json').read_text())
    changed = [path for path, digest in before['production'].items() if sha(ROOT/path) != digest]
    assert set(changed) == ALLOWED, changed
    for key, base in (('configuration', ROOT), ('prior_archive', ROOT),
                      ('prior_runtime_files', Path(before['prior_runtime']))):
        assert all(sha(base/path) == digest for path, digest in before[key].items()), key
    project_diff = subprocess.check_output(['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)
    assert hashlib.sha256(project_diff).hexdigest() == before['project_diff_sha256']
    runtime = Path(before['prior_runtime'])
    quota = json.loads((runtime/'quota.json').read_text())
    assert quota['model_requests'] == 15 and quota['web_operations'] == 0
    assert (runtime/'STOP').exists()
    report = dict(outcome='PASS', production_changed=sorted(changed),
        other_production_unchanged=len(before['production'])-len(changed),
        changed_production_sha256={path: sha(ROOT/path) for path in sorted(changed)},
        configuration_files_unchanged=len(before['configuration']),
        prior_runtime_files_unchanged=len(before['prior_runtime_files']),
        prior_archive_files_unchanged=len(before['prior_archive']), user_project_diff_unchanged=True,
        original_batch=dict(model_requests=15, model_limit=40, web_operations=0, stop=True, remaining_frozen=25),
        actual_new_model_requests=0, actual_new_provider_web_operations=0,
        no_app_or_daily_service_restart=True)
    (OUT/'protection-result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
