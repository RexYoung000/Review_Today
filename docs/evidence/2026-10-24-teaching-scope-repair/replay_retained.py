"""No-network/no-store replay of the immutable decision-268 output."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def audit(event, args):
    if event in {'socket.connect', 'sqlite3.connect', 'subprocess.Popen', 'os.system'}:
        raise AssertionError('Retained replay forbids network, databases and subprocesses')


sys.addaudithook(audit)
sys.path.insert(0, str(ROOT / 'agent-service'))
from agent_service.schemas import TeachingConversationOutput
from agent_service.openai_client import ModelCallError

record = json.loads((OUT.parent / '2026-10-24-fullflow-real/archive.json').read_text())
assert digest(record['archive']) == record['sha256']
with zipfile.ZipFile(record['archive']) as archive:
    events = [json.loads(line) for line in archive.read('live-events.jsonl').decode().splitlines()]
real = next(row for row in reversed(events)
            if row['type'] == 'semantic_output' and row.get('schema') == 'TeachingConversationOutput')
request = next(row for row in events if row['type'] == 'semantic_start' and row['call_id'] == real['call_id'])
fixtures = ROOT / 'agent-service/tests/fixtures'
retained = json.loads((fixtures / 'teaching_scope_268.json').read_text())
controlled = json.loads((fixtures / 'teaching_scope_repaired.json').read_text())
assert real['output'] == retained['output']
assert controlled['kind'] == 'controlled_candidate_not_a_real_model_output'
assert retained['provenance']['source_model_output_sha256'] == hashlib.sha256(
    json.dumps(real['output'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
results = []


def check(name, value, expected, diagnostic=None):
    try:
        output = TeachingConversationOutput.model_validate(deepcopy(value))
        output.validate_request(request['input'])
    except ModelCallError as error:
        actual, details = 'REJECT', json.loads(error.diagnostic)
        assert error.code == 'RT.MODEL.SCHEMA'
    else:
        actual, details = 'ACCEPT', []
    assert actual == expected, (name, actual, expected)
    if diagnostic:
        assert any(row['type'] == diagnostic for row in details), (name, details)
    results.append(dict(case=name, expected=expected, actual=actual, diagnostics=details))


check('exact_retained_real_failure', real['output'], 'REJECT', 'teaching_check_coverage_missing')
positive = controlled['output']
assert positive['check_question'] == real['output']['check_question']
check('controlled_complete_lesson_same_full_question', positive, 'ACCEPT')
partial = deepcopy(positive)
partial['question_coverage'].pop()
check('last_question_requirement_omitted', partial, 'REJECT', 'teaching_check_coverage_question')
untaught = deepcopy(positive)
untaught['question_coverage'][1].update(taught=False, evidence_quote_indices=[])
check('generation_requirement_declared_untaught', untaught, 'REJECT', 'teaching_check_coverage_untaught')
unbound = deepcopy(positive)
unbound['question_coverage'][1]['concepts'] = [positive['learning_concepts'][0]]
check('question_concept_missing_from_frozen_scope', unbound, 'REJECT', 'teaching_check_coverage_binding')
future = deepcopy(positive)
quote = '生成没有忠实依据资料'
future['message'] = '## 学习地图\n\n- 后续：' + quote + '\n\n### 当前第一步：相似度\n只解释相似度。'
future['check_binding']['evidence_quotes'] = [quote] * 4
check('literal_future_map_label_is_not_taught_evidence', future, 'REJECT', 'teaching_check_coverage_evidence')
fabricated = deepcopy(positive)
fabricated['check_binding']['evidence_quotes'][2] = 'This excerpt was never taught.'
check('fabricated_lesson_excerpt', fabricated, 'REJECT', 'teaching_check_grounding')
index = deepcopy(positive)
index['question_coverage'][1]['evidence_quote_indices'] = [-1]
check('negative_evidence_index', index, 'REJECT', 'teaching_check_coverage_evidence')

result = dict(status='OFFLINE_CONTRACT_REPLAY_PASS', decision=269, cases=results,
    immutable_archive_sha256=record['sha256'], retained_fixture_matches_actual_model_output=True,
    original_model_output_modified=False, positive_is_controlled_not_real_generation=True,
    corrected_question_keeps_all_original_requirements=True,
    independent_semantic_verification=False, model_owns_semantic_correspondence=True,
    database_connections=0, actual_model_requests=0, actual_web_operations=0,
    audit_blocks=['socket.connect', 'sqlite3.connect', 'subprocess.Popen', 'os.system'],
    source_sha256={str(path.relative_to(ROOT)): digest(path) for path in (
        ROOT / 'agent-service/agent_service/schemas.py', ROOT / 'agent-service/agent_service/teaching_check.py',
        ROOT / 'agent-service/agent_service/answer_style.py')},
    fixture_sha256={path.name: digest(path) for path in (fixtures / 'teaching_scope_268.json', fixtures / 'teaching_scope_repaired.json')})
(OUT / 'replay-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print('PASS: exact retained failure rejected; controlled full correction accepted; six negative controls rejected. Zero connections or requests.')
