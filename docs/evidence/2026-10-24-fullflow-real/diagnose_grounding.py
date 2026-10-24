"""Replay the retained lesson through existing validation, with no runtime access."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
archive_record = json.loads((OUT / 'archive.json').read_text())
archive = Path(archive_record['archive'])
with archive.open('rb') as stream:
    assert hashlib.file_digest(stream, 'sha256').hexdigest() == archive_record['sha256']


def audit(event, args):
    if event in {'socket.connect', 'sqlite3.connect'}:
        raise AssertionError('Offline diagnosis cannot connect to networks or stores')


sys.addaudithook(audit)
sys.path.insert(0, str(ROOT / 'agent-service'))
from agent_service.schemas import TeachingConversationOutput
from agent_service.openai_client import ModelCallError

with zipfile.ZipFile(archive) as retained:
    events = [json.loads(line) for line in retained.read('live-events.jsonl').decode().splitlines()]
output = next(row for row in reversed(events)
              if row['type'] == 'semantic_output' and row.get('schema') == 'TeachingConversationOutput')
request = next(row for row in events
               if row['type'] == 'semantic_start' and row['call_id'] == output['call_id'])
original = deepcopy(output['output'])
lesson = TeachingConversationOutput.model_validate(deepcopy(original))
lesson.validate_request(request['input'])

negative = TeachingConversationOutput.model_validate(deepcopy(original))
negative.check_binding.evidence_quotes = ['OFFLINE NEGATIVE CONTROL: this quote is not in the lesson.']
try:
    negative.validate_request(request['input'])
except ModelCallError as error:
    assert error.code == 'RT.MODEL.SCHEMA'
else:
    raise AssertionError('The existing literal grounding guard must reject a fabricated quote')

assert output['output'] == original
report = {
    'status': 'RETAINED_OUTPUT_ACCEPTED_BY_EXISTING_STRUCTURAL_VALIDATION',
    'retained_real_output_accepted': True,
    'fabricated_evidence_quote_negative_control_rejected': True,
    'bound_concepts': original['check_binding']['concepts'],
    'question': original['check_question'],
    'scope': original['check_binding']['scope'],
    'durable_execution_archive_sha256': archive_record['sha256'],
    'validation_source': 'agent-service/agent_service/schemas.py',
    'validation_source_sha256': hashlib.sha256(
        (ROOT / 'agent-service/agent_service/schemas.py').read_bytes()).hexdigest(),
    'does_not_prove_semantic_question_coverage': True,
    'original_model_output_modified': False,
    'runtime_or_daily_database_opened': False,
    'actual_model_requests': 0,
    'actual_web_operations': 0,
    'answer_evaluation_or_saving_tested': False,
}
(OUT / 'grounding-diagnosis.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('Retained output accepted; fabricated quote rejected; zero requests, no stores opened.')
