#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
test_dir="$(mktemp -d /tmp/review-today-python-tests.XXXXXX)"
export REVIEW_TODAY_HARNESS_DB="$test_dir/checkpoints.sqlite3"
export OPENAI_API_KEY=''
export DEEPSEEK_API_KEY=''
export TAVILY_API_KEY=''
export BRAVE_API_KEY=''
export REVIEW_TODAY_SEARCH_FALLBACKS=''
export REVIEW_TODAY_READ_FALLBACKS=''
export REVIEW_TODAY_CONTEXT_PROVIDER='none'
export REVIEW_TODAY_TAVILY_KEYLESS='0'
export REVIEW_TODAY_SEARCH_PROVIDER='none'
export REVIEW_TODAY_READ_PROVIDER='local'
export REVIEW_TODAY_LLM_PROVIDER='openai_compatible'
python_bin="${REVIEW_TODAY_TEST_PYTHON:-.venv/bin/python}"
# pytest also collects unittest.TestCase. unittest alone silently omits the
# parameterized dictation tests even when their modules import successfully.
"$python_bin" -m pytest tests -q
printf 'Isolated test database: %s\n' "$test_dir"
