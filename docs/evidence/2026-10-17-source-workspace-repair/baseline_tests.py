"""Run the same regressions with the baseline answer function in memory only."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def baseline_respond(namespace):
    setup = json.loads((OUT / 'setup.json').read_text())
    path = 'agent-service/agent_service/conversation.py'
    source = subprocess.check_output(['git', 'show', setup['baseline_commit'] + ':' + path], cwd=ROOT)
    assert hashlib.sha256(source).hexdigest() == setup['protected_sha256'][path]
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'ConversationHarness')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_respond')
    namespace = dict(namespace)
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<baseline _respond>', 'exec'), namespace)
    return namespace['_respond']


class BaselineAnswer:
    def pytest_collection_finish(self, session):
        # Existing runner has already isolated storage/keys and blocked public
        # sockets before collection imports any production module.
        from agent_service import conversation
        conversation.ConversationHarness._respond = baseline_respond(conversation.__dict__)


def main():
    import pytest
    original = pytest.main
    spec = importlib.util.spec_from_file_location('existing_controlled_tests',
        ROOT / 'docs/evidence/2026-10-16-preview-repair/test_runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    if not sys.argv[1:]:
        sys.argv += ['-q', str(ROOT / 'agent-service/tests/test_independent_question_sources.py')]
    with patch.object(pytest, 'main', lambda arguments: original(arguments, plugins=[BaselineAnswer()])):
        runner.main()


if __name__ == '__main__':
    main()
