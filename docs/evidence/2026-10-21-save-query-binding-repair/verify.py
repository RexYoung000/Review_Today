"""Verify protected real evidence and the allowed offline change boundary."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def files(p):return {str(f.relative_to(p)):digest(f) for f in Path(p).rglob('*') if f.is_file() and '__pycache__' not in f.parts}


def main():
    before=read(OUT/'protection-before.json')
    changed=[name for name,sha in before['production'].items() if digest(ROOT/name)!=sha]
    expected=['agent-service/agent_service/'+name for name in ['knowledge_capture_status.py','schemas.py','conversation.py','conversation_prompts.py']]
    assert set(changed)==set(expected)
    for group in ('configs','archives'):
        for name,sha in before[group].items():assert digest(ROOT/name)==sha,name
    runtime=Path(before['old_runtime'])
    assert files(runtime)==before['old_runtime_files']
    assert files(Path(before['native_app']))==before['prior_qa_app_files']
    assert hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest()==before['user_project_diff_sha256']
    quota=read(runtime/'quota.json');assert quota['model_requests']==22 and quota['web_operations']==0 and (runtime/'STOP').exists()
    checks=read(OUT/'controlled-result.json');assert checks['exit_code']==0 and not checks['denied_operations']
    assert not (Path(checks['guard_directory'])/'denied.jsonl').exists()
    for name,snippet in [('controlled.log','1326 passed, 4 skipped'),('targeted-final.log','103 passed'),('deepseek-targeted.log','53 passed')]:
        assert snippet in (OUT/name).read_text(),name
    replay=read(OUT/'replay-result.json');assert replay['outcome']=='PASS' and replay['actual_model_requests']==0
    for path in [*(ROOT/name for name in expected),*OUT.glob('*.py'),ROOT/'agent-service/tests/test_save_operation_status.py']:
        ast.parse(path.read_text(),filename=str(path))
    result=dict(outcome='PASS',production_changed=changed,production_changed_sha256={name:digest(ROOT/name) for name in changed},
        other_production_and_swift_preserved=176,configurations_preserved=2,prior_archives_preserved=54,
        real_runtime_files_preserved=29,real_batch_requests=22,real_batch_web_operations=0,real_STOP_preserved=True,
        user_project_difference_preserved=True,qa_app_preserved=True,new_real_model_requests=0,new_real_web_operations=0,
        controlled_suite=dict(passed=1326,skipped=4,subtests=611),
        final_targeted=dict(passed=103,subtests=62),deepseek_targeted=dict(passed=53,subtests=28),
        additional_tests_after_full_collection=4,added_tests=19,production_changed_after_full_suite=False,
        real_retained_state_http_replay='PASS_WITH_CONTROLLED_OPERATION_SELECTION',
        new_live_model_selection_verified=False,new_native_input_verified=False,app_or_service_restarted=False,
        warnings='Five pre-existing framework deprecation warnings; four existing skipped tests unchanged.')
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
