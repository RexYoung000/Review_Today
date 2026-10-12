"""Reproduce two commit/stop service boundaries with synthetic temporary data.

This checks the current defect, not a successful native save/recovery flow.
Run with agent-service/.venv/bin/python from any working directory.
"""
import os
import sys
import tempfile
from pathlib import Path

# Isolate imports too: some service modules create global stores on import.
audit_temp = tempfile.TemporaryDirectory(prefix="review-today-save-recovery-")
os.environ.update({
    "REVIEW_TODAY_HARNESS_DB": str(Path(audit_temp.name) / "import.sqlite3"),
    "TMPDIR": audit_temp.name,
    "PYTHONDONTWRITEBYTECODE": "1",
    "OPENAI_API_KEY": "",
    "DEEPSEEK_API_KEY": "",
    "TYPESAFE_API_KEY": "",
    "EXA_API_KEY": "",
    "TAVILY_API_KEY": "",
    "BRAVE_API_KEY": "",
    "REVIEW_TODAY_JEV_TEST": "0",
    "REVIEW_TODAY_SEARCH_FALLBACKS": "",
    "REVIEW_TODAY_READ_FALLBACKS": "",
    "REVIEW_TODAY_CONTEXT_PROVIDER": "none",
    "REVIEW_TODAY_TAVILY_KEYLESS": "0",
    "REVIEW_TODAY_BROWSER_FALLBACK": "0",
    "REVIEW_TODAY_SEARCH_PROVIDER": "none",
    "REVIEW_TODAY_READ_PROVIDER": "local",
    "REVIEW_TODAY_LLM_PROVIDER": "openai_compatible",
})
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "agent-service"))

import json
from tests.test_conversation_v2 import ConversationTests

results = []
for stage in ('mac_saved_ack_missing', 'claimed_before_mac_write'):
    fixture = ConversationTests()
    fixture.setUp()
    try:
        accepted, task_id = fixture.make_committable()
        claimed = fixture.harness.claim_commit(task_id)
        before = fixture.state()
        old_revision = before['runs'][accepted.run_id]['revision']
        package = before['tasks'][task_id]['memory_package']
        expected_ids = [item['id'] for item in package['knowledge']]
        assert expected_ids
        # In the first case these represent the already-persisted Mac IDs.
        # SwiftData and the native network client are not run by this script.
        fixture.control(accepted.run_id, 'stop')
        stopped = fixture.state()
        current_task = stopped['tasks'][task_id]
        assert stopped['runs'][accepted.run_id]['revision'] > old_revision
        assert current_task['status'] == 'committing'
        assert current_task['context']['commit_claimed'] is True
        claim_error = None
        try:
            fixture.harness.claim_commit(task_id)
        except ValueError as error:
            claim_error = str(error)
        assert claim_error == 'RT.TASK.COMMIT_REVOKED', claim_error
        row = dict(case=stage, initial_claim='success', stopped_task=current_task['status'],
                   commit_claimed=current_task['context']['commit_claimed'],
                   old_run_revision=old_revision,
                   stopped_run_revision=stopped['runs'][accepted.run_id]['revision'],
                   commit_revision=current_task['context']['commit_revision'],
                   reclaimed_error=claim_error, knowledge_ids=expected_ids,
                   mac_layer='not executed; native call order reviewed from source')
        if stage == 'mac_saved_ack_missing':
            ack = fixture.harness.acknowledge_task(task_id, len(current_task['events']), expected_ids)
            final = fixture.state()
            assert ack['status'] == 'completed'
            assert final['paused'] is True
            assert final['foreground'] is None
            row.update(direct_ack='success', task_after_ack=ack['status'],
                       session_after_ack_paused=final['paused'], foreground_after_ack=final['foreground'])
        else:
            row.update(direct_ack='not sent: no native write was assumed', memory_package_retained=bool(current_task['memory_package']))
        results.append(row)
    finally:
        fixture.tearDown()
print(json.dumps(results, ensure_ascii=False, indent=2))
